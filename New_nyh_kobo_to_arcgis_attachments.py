import pandas as pd
import requests
import os
import urllib.parse
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
AGOL_REFERER = os.getenv("AGOL_REFERER") or "https://arcgis.com"
FEATURE_LAYER_URL = os.getenv("NEW_ARCGIS_FEATURE_LAYER_URL").rstrip('/')

base_path = r"D:\DATA and ANALYTICS CONSULTATION\2026\Nyahururu 2026\Updated Files"
input_csv = os.path.join(base_path, "Nyahururu_Projects_Master_final_v1.csv")
save_dir  = os.path.join(base_path, "images")
os.makedirs(save_dir, exist_ok=True)

# These match your CSV columns
image_cols = [f"pre_img{i}" for i in range(1, 9)] # Adjusted based on your field list

# ---------------------------
# 2. FUNCTIONS
# ---------------------------
def get_token():
    url = "https://arcgis.com/sharing/rest/generateToken"
    data = {"username": AGOL_USERNAME, "password": AGOL_PASSWORD, "referer": AGOL_REFERER, "f": "json", "expiration": 1440}
    try:
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        encoded_data = urllib.parse.urlencode(data)
        return requests.post(url, data=encoded_data, headers=headers).json().get("token")
    except: return None

# ---------------------------
# 3. EXECUTION
# ---------------------------
def main():
    print("🔑 Logging in...")
    token = get_token()
    if not token: print("❌ Login failed."); return

    print("📖 Loading CSV...")
    df = pd.read_csv(input_csv, encoding="latin1")

    print(f"🚀 Processing {len(df)} records based on Row Order...")

    for index, row in df.iterrows():
        # IMPORTANT: Since you have 'ObjectId' in ArcGIS, 
        # Row 1 (index 0) in CSV maps to ObjectId 1 in ArcGIS.
        oid = index + 1 
        
        # We'll use village name just for logging so you know it's matching right
        village = str(row.get('village', 'Unknown'))

        for col in image_cols:
            url = str(row.get(col, ""))
            if url.startswith("http"):
                local_file = f"{col}_oid_{oid}.jpg"
                local_path = os.path.join(save_dir, local_file)
                
                # Download from Kobo
                if not os.path.exists(local_path):
                    try:
                        headers = {"Authorization": f"Token {KOBO_API_TOKEN}"}
                        r = requests.get(url, headers=headers, timeout=20)
                        if r.status_code == 200:
                            with open(local_path, "wb") as f: f.write(r.content)
                    except: continue
                
                # Upload to ArcGIS
                if os.path.exists(local_path):
                    try:
                        up_url = f"{FEATURE_LAYER_URL}/{oid}/addAttachment"
                        with open(local_path, "rb") as f_up:
                            files = {"attachment": (os.path.basename(local_path), f_up, "image/jpeg")}
                            params = {"f": "json", "token": token}
                            requests.post(up_url, data=params, files=files)
                    except: continue
        
        print(f"✅ Row {oid} ({village}) synced.")

if __name__ == "__main__":
    main()
