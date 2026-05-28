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

# ---------- STEP 4 : BASIC DATA CLEANING ----------

# Replace empty values
df = df.fillna("")

# Remove duplicate rows
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


# ---------- STEP 6 : GOOGLE SHEETS UPDATE ----------

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

existing_data = sheet.get_all_values()

# Add headers if sheet is empty
if not existing_data:
    sheet.append_row(
        df.columns.tolist()
    )

# Append new rows below old data
sheet.append_rows(
    df.values.tolist()
)

print("Google Sheet updated")


print("\nPipeline completed successfully")
