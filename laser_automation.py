import sqlite3
import pandas as pd
import gspread
import os
import json
import sys

from google.oauth2.service_account import Credentials

from parse_laser_xml import parse_xml
from gmail_fetch import fetch_latest_xml


# ---------- STEP 1 : FETCH XML FROM GMAIL ----------

xml_path = fetch_latest_xml()

if not xml_path:
    print("No XML found")
    sys.exit()

print(f"Using XML: {xml_path}")


# ---------- STEP 2 : PARSE XML ----------

rows, columns = parse_xml(
    xml_path,
    output_csv="laser_output.csv"
)

print(f"Parsed {len(rows)} rows")


# ---------- STEP 3 : LOAD CSV ----------

df = pd.read_csv("laser_output.csv")


# ---------- STEP 4 : BASIC CLEANING ----------

# Replace empty values
df = df.fillna("")

# Remove duplicate rows inside current XML
df = df.drop_duplicates()

# Clean column names
df.columns = df.columns.str.strip()

print("Data cleaned")


# ---------- STEP 5 : DATETIME CONVERSION ----------

required_columns = [
    "beginTimestamp",
    "endTimestamp",
    "job_name"
]

for col in required_columns:

    if col not in df.columns:
        print(f"Missing column: {col}")
        sys.exit()

df["beginTimestamp"] = pd.to_datetime(
    df["beginTimestamp"]
)

df["endTimestamp"] = pd.to_datetime(
    df["endTimestamp"]
)

print("Datetime conversion completed")


# ---------- STEP 6 : CALCULATE RUNTIME ----------

df["Runtime"] = (
    df["endTimestamp"]
    - df["beginTimestamp"]
)

# Runtime in Minutes
df["Runtime in Min"] = (
    df["Runtime"]
    .dt.total_seconds() / 60
).round(0)

print("Runtime calculated")


# ---------- STEP 7 : CALCULATE DOWNTIME ----------

# Previous row end time
previous_end = df["endTimestamp"].shift(1)

# Downtime
df["Downtime"] = (
    df["beginTimestamp"]
    - previous_end
)

# First row downtime = 0
df.loc[0, "Downtime"] = pd.Timedelta(seconds=0)

# Downtime in Minutes
df["Downtime in Min"] = (
    df["Downtime"]
    .dt.total_seconds() / 60
).fillna(0).round(0)

# If downtime > 300 min → set 0
df.loc[
    df["Downtime in Min"] > 300,
    "Downtime in Min"
] = 0

# Also reset downtime duration
df.loc[
    df["Downtime in Min"] == 0,
    "Downtime"
] = pd.Timedelta(seconds=0)

print("Downtime calculated")


# ---------- STEP 8 : EFFICIENCY ----------

df["Efficiency"] = (
    df["Runtime in Min"]
    /
    (
        df["Runtime in Min"]
        + df["Downtime in Min"]
    )
) * 100

df["Efficiency"] = (
    df["Efficiency"]
    .fillna(100)
    .round(2)
)

print("Efficiency calculated")


# ---------- STEP 9 : FILTER COLUMN ----------

df["Filter"] = df[
    "Downtime in Min"
].apply(
    lambda x:
    "Big Gap"
    if x > 10
    else "Normal"
)

print("Filter column created")


# ---------- STEP 10 : STORE IN SQLITE ----------

conn = sqlite3.connect(
    "laser_data.db"
)

df.to_sql(
    "laser_records",
    conn,
    if_exists="append",
    index=False
)

conn.close()

print("SQLite updated")


# ---------- STEP 11 : GOOGLE SHEETS CONNECTION ----------

creds_dict = json.loads(
    os.environ["GOOGLE_CREDENTIALS"]
)

creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
)

gc = gspread.authorize(creds)

sheet = gc.open(
    "Laser_Data"
).sheet1


# ---------- STEP 12 : GET EXISTING DATA ----------

existing_data = sheet.get_all_records()


# ---------- STEP 13 : FIRST TIME UPLOAD ----------

if not existing_data:

    # Add headers
    sheet.append_row(
        df.columns.tolist()
    )

    # Add all rows
    sheet.append_rows(
        df.astype(str).values.tolist()
    )

    print(
        "First upload completed"
    )


# ---------- STEP 14 : DUPLICATE PREVENTION ----------

else:

    existing_df = pd.DataFrame(
        existing_data
    )

    existing_df.columns = (
        existing_df.columns.str.strip()
    )

    # Create unique key
    df["unique_key"] = (
        df["beginTimestamp"].astype(str)
        + "_"
        + df["job_name"].astype(str)
    )

    existing_df["unique_key"] = (
        existing_df["beginTimestamp"].astype(str)
        + "_"
        + existing_df["job_name"].astype(str)
    )

    # Keep only new rows
    new_rows = df[
        ~df["unique_key"].isin(
            existing_df["unique_key"]
        )
    ]

    # Remove helper column
    new_rows = new_rows.drop(
        columns=["unique_key"]
    )

    # Append only new rows
    if not new_rows.empty:

        sheet.append_rows(
            new_rows.astype(str)
            .values.tolist()
        )

        print(
            f"Added {len(new_rows)} new rows"
        )

    else:

        print(
            "No new data found"
        )


print("\nPipeline completed successfully")
