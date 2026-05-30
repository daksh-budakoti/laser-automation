import sqlite3
import pandas as pd
import gspread
import os
import json
import sys
import logging
import time

from google.oauth2.service_account import Credentials
from parse_laser_xml import parse_xml
from gmail_fetch import fetch_latest_xml


# ============================================================
# LOGGING SETUP
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("pipeline.log"),
        logging.StreamHandler()
    ]
)

log = logging.getLogger(__name__)

# Pipeline timer
pipeline_start = time.time()


# ============================================================
# HELPER : FORMAT TIMEDELTA AS HH:MM:SS
# ============================================================

def format_timedelta(series):
    """Convert timedelta series to HH:MM:SS strings (no '0 days' prefix)."""
    return series.astype(str).str.split(" ").str[-1]


# ============================================================
# STEP 1 : FETCH XML FROM GMAIL
# ============================================================

try:
    xml_path = fetch_latest_xml()

    if not xml_path:
        raise FileNotFoundError(
            "No XML attachment found in Gmail. "
            "Check that the email arrived and has an XML attachment."
        )

    if not os.path.exists(xml_path):
        raise FileNotFoundError(
            f"XML file was returned but does not exist on disk: {xml_path}"
        )

    log.info(f"XML fetched: {xml_path}")

except FileNotFoundError as e:
    log.error(f"STEP 1 FAILED — {e}")
    sys.exit(1)


# ============================================================
# STEP 2 : PARSE XML -> DATAFRAME (no intermediate CSV)
# ============================================================

try:
    rows, columns = parse_xml(xml_path)

    if not rows:
        raise ValueError(
            "XML parsed successfully but contains zero records. "
            "The file may be empty or have an unexpected structure."
        )

    df = pd.DataFrame(rows, columns=columns)
    log.info(f"Parsed {len(df)} rows from XML")

except Exception as e:
    log.error(f"STEP 2 FAILED — {e}")
    sys.exit(1)


# ============================================================
# STEP 3 : BASIC CLEANING
# ============================================================

try:
    df.columns = df.columns.str.strip()
    df = df.drop_duplicates()

    str_cols = df.select_dtypes(include="object").columns
    df[str_cols] = df[str_cols].apply(lambda col: col.str.strip())

    log.info("Data cleaned")

except Exception as e:
    log.error(f"STEP 3 FAILED — {e}")
    sys.exit(1)


# ============================================================
# STEP 4 : VALIDATE REQUIRED COLUMNS
# ============================================================

try:
    required_columns = ["beginTimestamp", "endTimestamp", "job_name"]

    missing = [col for col in required_columns if col not in df.columns]

    if missing:
        raise ValueError(
            f"Missing required columns: {missing}. "
            f"Available columns: {df.columns.tolist()}"
        )

    log.info("Required columns validated")

except ValueError as e:
    log.error(f"STEP 4 FAILED — {e}")
    sys.exit(1)


# ============================================================
# STEP 5 : DATETIME CONVERSION + VALIDATION
# ============================================================

try:
    df["beginTimestamp"] = pd.to_datetime(
        df["beginTimestamp"], errors="coerce"
    )
    df["endTimestamp"] = pd.to_datetime(
        df["endTimestamp"], errors="coerce"
    )

    bad_rows = df[
        df["beginTimestamp"].isna() | df["endTimestamp"].isna()
    ]
    if not bad_rows.empty:
        raise ValueError(
            f"{len(bad_rows)} rows have invalid/unparseable timestamps. "
            f"Row indices: {bad_rows.index.tolist()}"
        )

    negative = df[df["endTimestamp"] < df["beginTimestamp"]]
    if not negative.empty:
        raise ValueError(
            f"{len(negative)} rows have endTimestamp before beginTimestamp. "
            f"Row indices: {negative.index.tolist()}"
        )

    log.info("Datetime conversion and validation completed")

except ValueError as e:
    log.error(f"STEP 5 FAILED — {e}")
    sys.exit(1)


# ============================================================
# STEP 6 : SORT BY START TIME
# ============================================================

df = df.sort_values(by="beginTimestamp").reset_index(drop=True)
log.info("Sorted by beginTimestamp")


# ============================================================
# STEP 7 : EXTRACT DATE & TIME COLUMNS
# ============================================================

df["Start Date"] = df["beginTimestamp"].dt.date
df["Start Time"] = df["beginTimestamp"].dt.strftime("%H:%M:%S")
df["End Date"]   = df["endTimestamp"].dt.date
df["End Time"]   = df["endTimestamp"].dt.strftime("%H:%M:%S")

log.info("Start Date, Start Time, End Date, End Time columns added")


# ============================================================
# STEP 8 : CALCULATE RUNTIME
# ============================================================

runtime_td = df["endTimestamp"] - df["beginTimestamp"]

df["Runtime"]        = format_timedelta(runtime_td)
df["Runtime in Min"] = (runtime_td.dt.total_seconds() // 60).astype(int)

log.info("Runtime calculated")


# ============================================================
# STEP 9 : CALCULATE DOWNTIME
# ============================================================

previous_end = df["endTimestamp"].shift(1)
downtime_td  = df["beginTimestamp"] - previous_end

downtime_td.iloc[0] = pd.Timedelta(seconds=0)

df["Downtime in Min"] = (
    downtime_td.dt.total_seconds() // 60
).fillna(0).astype(int)

mask = df["Downtime in Min"] > 300
df.loc[mask, "Downtime in Min"] = 0
downtime_td.loc[mask] = pd.Timedelta(seconds=0)

df["Downtime"] = format_timedelta(downtime_td)

log.info("Downtime calculated")


# ============================================================
# STEP 10 : EFFICIENCY
# ============================================================

total_min = df["Runtime in Min"] + df["Downtime in Min"]

df["Efficiency"] = (
    df["Runtime in Min"] / total_min * 100
).fillna(100).round(2)

log.info("Efficiency calculated")


# ============================================================
# STEP 11 : FILTER COLUMN
# ============================================================

df["Filter"] = df["Downtime in Min"].apply(
    lambda x: "Big Gap" if x > 10 else "Normal"
)

log.info("Filter column created")


# ============================================================
# STEP 12 : DASHBOARD-READY DATE COLUMNS (Tableau friendly)
# ============================================================

df["Month"] = df["beginTimestamp"].dt.strftime("%B")
df["Year"]  = df["beginTimestamp"].dt.year
df["Day"]   = df["beginTimestamp"].dt.day_name()
df["Week"]  = df["beginTimestamp"].dt.isocalendar().week.astype(int)

log.info("Dashboard columns added: Month, Year, Day, Week")


# ============================================================
# STEP 13 : STORE IN SQLITE
# FIX #1 — let pandas create the full table automatically
# FIX #2 — deduplicate before insert so no IntegrityError
# FIX #3 — track processed XML filenames
# ============================================================

conn = None
try:
    conn = sqlite3.connect("laser_data.db")

    # --- FIX #2 : Remove duplicates before inserting ---
    df = df.drop_duplicates(subset=["beginTimestamp", "job_name"])

    # --- FIX #1 : Let pandas create the full table schema ---
    # if_exists="append" will create it on first run with all columns
    df.to_sql(
        "laser_records",
        conn,
        if_exists="append",
        index=False
    )

    log.info(f"SQLite updated — {len(df)} rows written")

    # --- FIX #3 : Track processed XML files ---
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processed_files (
            file_name    TEXT UNIQUE,
            processed_at TEXT
        )
    """)

    conn.execute(
        "INSERT OR IGNORE INTO processed_files VALUES (?, datetime('now'))",
        (os.path.basename(xml_path),)
    )

    conn.commit()
    log.info(f"Processed file logged: {os.path.basename(xml_path)}")

except Exception as e:
    raise RuntimeError(f"SQLite write failed: {e}")

finally:
    if conn:
        conn.close()


# ============================================================
# STEP 14 : GOOGLE SHEETS CONNECTION
# ============================================================

try:
    creds_dict = json.loads(os.environ["GOOGLE_CREDENTIALS"])

    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
    )

    gc    = gspread.authorize(creds)
    sheet = gc.open("Laser_Data").sheet1

    log.info("Google Sheets connected")

except KeyError:
    log.error("STEP 14 FAILED — GOOGLE_CREDENTIALS env variable not set")
    sys.exit(1)

except Exception as e:
    raise RuntimeError(f"Google Sheets connection failed: {e}")


# ============================================================
# STEP 15 : UPLOAD / DEDUPLICATE TO GOOGLE SHEETS
# ============================================================

try:
    existing_data = sheet.get_all_records()

    if not existing_data:

        sheet.append_row(df.columns.tolist())
        sheet.append_rows(df.astype(str).values.tolist())
        log.info("First upload completed")

    else:

        existing_df = pd.DataFrame(existing_data)
        existing_df.columns = existing_df.columns.str.strip()

        def make_key(frame):
            return (
                frame["beginTimestamp"].astype(str)
                + "_"
                + frame["job_name"].astype(str)
            )

        df["unique_key"]          = make_key(df)
        existing_df["unique_key"] = make_key(existing_df)

        new_rows = df[~df["unique_key"].isin(existing_df["unique_key"])]
        new_rows = new_rows.drop(columns=["unique_key"])

        if not new_rows.empty:
            sheet.append_rows(new_rows.astype(str).values.tolist())
            log.info(f"Added {len(new_rows)} new rows to Google Sheets")
        else:
            log.info("No new data — Google Sheets already up to date")

except Exception as e:
    raise RuntimeError(f"Google Sheets upload failed: {e}")


# ============================================================
# DONE — pipeline timer
# ============================================================

elapsed = time.time() - pipeline_start
log.info(f"Pipeline completed in {elapsed:.2f}s")
