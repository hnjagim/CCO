from arcgis.gis import GIS
import os
from dotenv import load_dotenv

# ---------------------------
# 1. LOAD ENV
# ---------------------------
load_dotenv()

AGOL_USERNAME = os.getenv("AGOL_USERNAME")
AGOL_PASSWORD = os.getenv("AGOL_PASSWORD")

if not AGOL_USERNAME or not AGOL_PASSWORD:
    raise Exception("❌ Missing AGOL credentials in .env")

# ---------------------------
# 2. CONNECT TO ARCGIS ONLINE
# ---------------------------
gis = GIS("https://www.arcgis.com", AGOL_USERNAME, AGOL_PASSWORD)
print("✅ Logged into ArcGIS Online")

# ---------------------------
# 3. CSV PATH
# ---------------------------
csv_path = r"D:\DATA and ANALYTICS CONSULTATION\2026\Nyahururu 2026\New Files\Nyahururu_Projects_Master_final_v1.csv"

if not os.path.exists(csv_path):
    raise FileNotFoundError(f"❌ CSV not found:\n{csv_path}")

print(f"📄 Using CSV:\n{csv_path}")

# ---------------------------
# 4. UPLOAD CSV TO AGOL
# ---------------------------
csv_item = gis.content.add(
    item_properties={
        "title": "Nyahururu Projects Master v1",
        "type": "CSV",
        "tags": "kobo, nyahururu, projects",
        "description": "Uploaded via Python automation"
    },
    data=csv_path
)

print(f"📤 CSV uploaded")
print(f"Item ID: {csv_item.id}")

# ---------------------------
# 5. PUBLISH AS HOSTED FEATURE LAYER
# ---------------------------
print("\n🚀 Publishing to Hosted Feature Layer...")

feature_layer_item = csv_item.publish()

print("\n🎯 SUCCESS!")
print(f"Feature Layer Title: {feature_layer_item.title}")
print(f"Feature Layer URL: {feature_layer_item.url}")
print(f"Item ID: {feature_layer_item.id}")