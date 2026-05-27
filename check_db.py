import sqlite3

conn = sqlite3.connect("laser_data.db")

cursor = conn.cursor()

cursor.execute("""
SELECT job_name, duration_seconds
FROM laser_records
LIMIT 5
""")

rows = cursor.fetchall()

for row in rows:
    print(row)

conn.close()