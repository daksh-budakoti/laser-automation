import sqlite3
import pandas as pd
import gspread
from gspread_dataframe import set_with_dataframe

from parse_laser_xml import parse_xml

# ---------- STEP 1 ----------
xml_path = r"downloads\Sample.XML"

print(f"Using XML: {xml_path}")

# ---------- STEP 2 ----------
rows, columns = parse_xml(
    xml_path,
    output_csv="laser_output.csv"
)

print(f"Parsed {len(rows)} rows")

# ---------- STEP 3 ----------
df = pd.read_csv("laser_output.csv")

# Replace empty values
df = df.fillna("")

conn = sqlite3.connect("laser_data.db")

df.to_sql(
    "laser_records",
    conn,
    if_exists="append",
    index=False
)

conn.close()

print("SQLite updated")


# ---------- STEP 4 ----------
gc = gspread.service_account(
    filename="service_account.json"
)

sheet = gc.open("Laser_Data").sheet1

sheet.clear()

set_with_dataframe(sheet, df)

print("Google Sheet updated")

print("\nPipeline completed successfully")