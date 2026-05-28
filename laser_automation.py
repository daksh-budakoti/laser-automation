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


# ---------- STEP 5 : STORE IN SQLITE ----------

conn = sqlite3.connect("laser_data.db")

df.to_sql(
    "laser_records",
    conn,
    if_exists="append",
    index=False
)

conn.close()

print("SQLite updated")


# ---------- STEP 6 : GOOGLE SHEETS CONNECTION ----------

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

sheet = gc.open("Laser_Data").sheet1


# ---------- STEP 7 : GET EXISTING DATA ----------

existing_data = sheet.get_all_records()


# ---------- STEP 8 : FIRST TIME UPLOAD ----------

if not existing_data:

    # Add headers
    sheet.append_row(
        df.columns.tolist()
    )

    # Add all rows
    sheet.append_rows(
        df.values.tolist()
    )

    print("First upload completed")


# ---------- STEP 9 : DUPLICATE PREVENTION ----------

else:

    existing_df = pd.DataFrame(
        existing_data
    )

    existing_df.columns = (
        existing_df.columns.str.strip()
    )

    # IMPORTANT:
    # Use unique combination
    # beginTimestamp + job_name

    required_columns = [
        "beginTimestamp",
        "job_name"
    ]

    for col in required_columns:

        if col not in df.columns:
            print(f"Missing column: {col}")
            sys.exit()

        if col not in existing_df.columns:
            print(f"Missing column in sheet: {col}")
            sys.exit()

    # Convert to string for safe comparison
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

    # Keep only truly new rows
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
            new_rows.values.tolist()
        )

        print(
            f"Added {len(new_rows)} new rows"
        )

    else:

        print(
            "No new data found"
        )


print("\nPipeline completed successfully")
