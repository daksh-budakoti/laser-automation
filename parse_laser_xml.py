"""
parse_laser_xml.py  — Dynamic Laser XML Parser
================================================
AUTO-DETECTS all columns from any XML structure.
Works if future files have more or fewer fields.

Handles:
  - Flat fields: <name>, <beginTimestamp>, <thickness> ...
  - Nested fields: <originPosition><X> → originPosition_X
  - Large files (iterparse = low memory, ~constant RAM regardless of file size)
  - Computed columns: duration_seconds, job_name (just filename, no full path)

Output: returns list of dicts + writes CSV
Plug directly into laser_automation.py
"""

import xml.etree.ElementTree as ET
import csv
import os
import sys
from datetime import datetime
from pathlib import Path


# ─────────────────────────────────────────────────────────────
# CONFIG — only touch these
# ─────────────────────────────────────────────────────────────
RECORD_TAG       = "WorkReportData"       # Repeating element in your XML
TIMESTAMP_FIELDS = ["beginTimestamp", "endTimestamp"]  # Will be cleaned to YYYY-MM-DD HH:MM:SS

# Column order in output (unmatched columns go alphabetically after)
PRIORITY_COLS = [
    "job_name", "name", "beginTimestamp", "endTimestamp", "duration_seconds",
    "material", "technologyType", "thickness",
    "tracksNumber", "firstTrack", "lastTrack", "tracksLength",
    "isClosed", "isTechnologyLocked", "originAngle",
]
# ─────────────────────────────────────────────────────────────


def flatten_element(element, prefix=""):
    """
    Recursively flatten nested XML element into a flat dict.
    <originPosition><X>9.18</X></originPosition>  →  {"originPosition_X": "9.18"}
    """
    result = {}
    for child in element:
        tag  = child.tag
        key  = f"{prefix}_{tag}" if prefix else tag
        if len(child) == 0:
            result[key] = (child.text or "").strip()
        else:
            result.update(flatten_element(child, prefix=tag))
    return result


def clean_timestamp(ts_str):
    """Convert ISO 8601 with timezone to clean YYYY-MM-DD HH:MM:SS string."""
    if not ts_str:
        return ""
    try:
        clean = ts_str.strip()[:19].replace("T", " ")   # '2025-11-24T16:08:08...' → '2025-11-24 16:08:08'
        datetime.strptime(clean, "%Y-%m-%d %H:%M:%S")   # Validate
        return clean
    except Exception:
        return ts_str  # Fallback: return raw string if parsing fails


def compute_duration(row):
    """Seconds between begin and end timestamps."""
    try:
        fmt = "%Y-%m-%d %H:%M:%S"
        b   = datetime.strptime(row["beginTimestamp"], fmt)
        e   = datetime.strptime(row["endTimestamp"],   fmt)
        return round((e - b).total_seconds(), 1)
    except Exception:
        return ""


def extract_job_name(full_path):
    """'C:\\Shared\\Programs\\A1.nc'  →  'A1'"""
    if not full_path:
        return ""
    # Works on both Windows paths (from the XML) and Linux
    name = full_path.replace("\\", "/").split("/")[-1]  # Get filename
    return name.rsplit(".", 1)[0]                        # Strip extension


def parse_xml(xml_path, output_csv=None):
    """
    Parse XML and return list of flat dicts.
    Optionally write to CSV if output_csv path is given.

    Args:
        xml_path  (str): Path to the XML file
        output_csv (str): If given, write cleaned CSV here

    Returns:
        list[dict]: All records as flat dicts
    """
    print(f"[PARSER] Reading: {xml_path}")

    all_rows    = []
    all_columns = set()

    # iterparse = reads element by element, doesn't load entire XML into RAM
    context = ET.iterparse(xml_path, events=("end",))

    for _, elem in context:
        if elem.tag != RECORD_TAG:
            continue

        row = flatten_element(elem)

        # Clean timestamps
        for field in TIMESTAMP_FIELDS:
            if field in row:
                row[field] = clean_timestamp(row[field])

        # Add computed columns
        row["duration_seconds"] = compute_duration(row)
        row["job_name"]         = extract_job_name(row.get("name", ""))

        all_columns.update(row.keys())
        all_rows.append(row)
        elem.clear()   # ← free memory after each record (critical for large files)

    if not all_rows:
        print(
            f"[PARSER] WARNING: No <{RECORD_TAG}> records found. "
            f"Check RECORD_TAG in config."
        )
        return [], []

    # Build final column order
    other_cols    = sorted([c for c in all_columns if c not in PRIORITY_COLS])
    final_columns = [c for c in PRIORITY_COLS if c in all_columns] + other_cols

    print(f"[PARSER] {len(all_rows)} records | {len(final_columns)} columns detected")
    print(f"[PARSER] Columns: {', '.join(final_columns)}")

    # Write CSV if requested
    if output_csv:
        os.makedirs(os.path.dirname(os.path.abspath(output_csv)), exist_ok=True)
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=final_columns, extrasaction="ignore")
            writer.writeheader()
            for row in all_rows:
                writer.writerow(row)
        print(f"[PARSER] CSV saved → {output_csv}")

    return all_rows, final_columns


# ──────────────────────────────────────────
# Run directly to test: python parse_laser_xml.py myfile.xml
# ──────────────────────────────────────────
if __name__ == "__main__":
    xml_file = sys.argv[1] if len(sys.argv) > 1 else r"C:\laser_data\latest.xml"

    if not os.path.exists(xml_file):
        print(f"[ERROR] File not found: {xml_file}")
        sys.exit(1)

    rows, cols = parse_xml(xml_file, output_csv="laser_output.csv")

    print("\n--- PREVIEW: First 3 rows ---")
    for row in rows[:3]:
        for k, v in row.items():
            print(f"  {k:30s}: {v}")
        print()
