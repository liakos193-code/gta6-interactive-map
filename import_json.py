import sqlite3
import json

with open("locations.json", "r", encoding="utf-8") as f:
    locs = json.load(f)

conn = sqlite3.connect("gta6_tracker.db")
cursor = conn.cursor()
cursor.execute("DELETE FROM locations")
cursor.execute("DELETE FROM user_progress")

for loc in locs:
    cursor.execute(
        "INSERT INTO locations (title, category, description, x, y) VALUES (?, ?, ?, ?, ?)",
        (loc["title"], loc["category"], loc["description"], loc["x"], loc["y"])
    )

conn.commit()
conn.close()
print(f"[+] Loaded {len(locs)} accurate locations successfully!")