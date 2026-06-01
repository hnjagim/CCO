import os
from dotenv import load_dotenv
from arcgis.gis import GIS

# Load credentials
load_dotenv()

AGOL_USERNAME = os.getenv("AGOL_USERNAME")
AGOL_PASSWORD = os.getenv("AGOL_PASSWORD")

# Connect to ArcGIS Online
gis = GIS("https://www.arcgis.com", AGOL_USERNAME, AGOL_PASSWORD)

print("✅ Connected to ArcGIS")
print("Logged in as:", gis.users.me.username)

# Table you want to delete
table_name = "Church_Mobilization"

print(f"\n🔎 Searching for item: {table_name}")

items = gis.content.search(
    query=f"title:{table_name}",
    max_items=5
)

if not items:
    print("❌ No item found with that title.")
else:
    for item in items:
        print(f"Found: {item.title} | Type: {item.type}")

        confirm = input("Delete this item? (yes/no): ")

        if confirm.lower() == "yes":
            item.delete()
            print(f"🗑 Deleted: {item.title}")
        else:
            print("Skipped.")

print("\n✔ Done")