import pandas as pd
import requests
import os
from dotenv import load_dotenv
from pathlib import Path

# ---------------------------
# 1. SETUP
# ---------------------------
dotenv_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

KOBO_API_TOKEN = os.getenv("KOBO_API_TOKEN")
AGOL_USERNAME = os.getenv("AGOL_USERNAME")
AGOL_PASSWORD = os.getenv("AGOL_PASSWORD")
FEATURE_LAYER_URL = os.getenv("NEW_ARCGIS_FEATURE_LAYER_URL")

# Paths
base_path = r"D:\DATA and ANALYTICS CONSULTATION\2026\Nyahururu 2026\Updated Files"
input_csv = os.path.join(base_path, "Nyahururu_Projects_Master_final_v1.csv")
save_dir  = os.path.join(base_path, "images")
os.makedirs(save_dir, exist_ok=True)

image_cols = [f"pre_img{i}" for i in range(9)]

# ---------------------------
# 2. FUNCTIONS
# ---------------------------
def get_token():
    url = "https://arcgis.com"
    data = {"username": AGOL_USERNAME, "password": AGOL_PASSWORD, "referer": "https://arcgis.com", "f": "json"}
    return requests.post(url, data=data).json().get("token")

def get_arcgis_id_map(token):
    """Maps your 'Project_ID' to the actual ArcGIS 'OBJECTID'."""
    url = f"{FEATURE_LAYER_URL}/query"
    params = {"where": "1=1", "outFields": "OBJECTID, Project_ID", "f": "json", "token": token}
    features = requests.get(url, params=params).json().get('features', [])
    # Mapping: {Project_ID: OBJECTID}
    return {str(f['attributes']['Project_ID']): f['attributes']['OBJECTID'] for f in features}

# ---------------------------
# 3. EXECUTION
# ---------------------------
print("🔑 Authenticating and Mapping IDs...")
token = get_token()
id_map = get_arcgis_id_map(token)

df = pd.read_csv(input_csv, encoding="latin1")

print(f"🚀 Starting upload for {len(df)} projects...")

for _, row in df.iterrows():
    pid = str(row['Project_ID'])
    oid = id_map.get(pid)
    
    if not oid:
        print(f"⚠️ Project_ID {pid} not found in ArcGIS. Skipping.")
        continue

    for col in image_cols:
        url = str(row[col])
        if url.startswith("http"):
            local_path = os.path.join(save_dir, f"{col}_pid_{pid}.jpg")
            
            # Download from Kobo
            img_r = requests.get(url, headers={"Authorization": f"Token {KOBO_API_TOKEN}"})
            if img_r.status_code == 200:
                with open(local_path, "wb") as f: f.write(img_r.content)
                
                # Upload to ArcGIS using the REAL OID
                up_url = f"{FEATURE_LAYER_URL}/{oid}/addAttachment"
                with open(local_path, "rb") as f_up:
                    files = {"attachment": (os.path.basename(local_path), f_up, "image/jpeg")}
                    requests.post(up_url, data={"f": "json", "token": token}, files=files)
    
    print(f"✅ Finished Project_ID: {pid} (ArcGIS OID: {oid})")

print("🎉 ALL DONE!")