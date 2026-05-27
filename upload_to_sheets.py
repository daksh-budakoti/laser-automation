import gspread
import pandas as pd
from gspread_dataframe import set_with_dataframe

# Connect using service account
gc = gspread.service_account(filename="service_account.json")

# Open your Google Sheet
sheet = gc.open("Laser_Data").sheet1

# Read CSV
df = pd.read_csv("laser_output.csv")

# Clear old data (optional)
sheet.clear()

# Upload dataframe
set_with_dataframe(sheet, df)

print(f"{len(df)} rows uploaded successfully!")