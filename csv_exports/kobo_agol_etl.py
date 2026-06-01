import os
import requests
import pandas as pd
from dotenv import load_dotenv
from arcgis.gis import GIS
from io import StringIO

# Load environment variables
load_dotenv()

AGOL_USERNAME = os.getenv("AGOL_USERNAME")
AGOL_PASSWORD = os.getenv("AGOL_PASSWORD")

KOBO_USERNAME = os.getenv("KOBO_USERNAME")
KOBO_PASSWORD = os.getenv("KOBO_PASSWORD")

KOBO_API_TOKEN = os.getenv("KOBO_API_TOKEN")

print("🔐 Kobo Token Loaded:", bool(KOBO_API_TOKEN))


# Connect to ArcGIS Online
gis = GIS("https://www.arcgis.com", AGOL_USERNAME, AGOL_PASSWORD)

if gis.users.me:
    print("✅ Successfully connected to ArcGIS Online")
    print("Logged in as:", gis.users.me.username)
else:
    print("❌ Login Failed")

# ===============================
# KOBO FORMS
# ===============================

forms = {
    "Water_Access": "aE497GDmCKdDWKUrwTG6Sb",
    "Sanitation_Institution": "aAocE38i77TjFybswfeTJp",
    "Sanitation_Household": "aiRYEqZYTAm2zS9hx3PrcK",
    "Church_Mobilization": "a4LCRjghfiBJmxW7F2nuXD"
}

for table_name, form_id in forms.items():

    print(f"\n🔄 Processing {table_name}")

    url = f"https://eu.kobotoolbox.org/api/v2/assets/{form_id}/data.json"

    headers = {
        "Authorization": f"Token {KOBO_API_TOKEN}"
    }

    response = requests.get(url, headers=headers)

    if response.status_code != 200:
        print(f"❌ Failed to fetch {table_name}")
        print("Status Code:", response.status_code)
        print("Response:", response.text)
        continue

    data = response.json()

    if "results" not in data:
        print(f"❌ No data returned for {table_name}")
        continue

    df = pd.json_normalize(data["results"])

    print(f"✅ Retrieved {len(df)} records from {table_name}")

    # ===============================
    # SMART UPLOAD (INSIDE LOOP ✅)
    # ===============================

    print("⬆ Preparing upload for", table_name)

    csv_buffer = StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)

    print("⬆ Checking if table already exists in ArcGIS")

    existing_items = gis.content.search(
        query=f"title:{table_name} AND type:CSV",
        max_items=1
    )

    if existing_items:

        print("♻ Table exists — Updating...")

        existing_item = existing_items[0]

        existing_item.update(data=csv_buffer)

        published = existing_item.publish(overwrite=True)

        print(f"✅ Updated Hosted Table: {published.title}")

    else:

        print("🆕 Table not found — Creating new")

        csv_item = gis.content.add(
            item_properties={
                "title": table_name,
                "type": "CSV",
                "tags": ["kobo", "automation"]
            },
            data=csv_buffer
        )

        published = csv_item.publish()

        print(f"✅ Created Hosted Table: {published.title}")

    print("✔ Finished processing", table_name)

print("\n🎯 DATA PULL COMPLETE")