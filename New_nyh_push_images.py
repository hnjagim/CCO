import os
import time
import requests
from dotenv import load_dotenv
from arcgis.gis import GIS

# 1. Setup
load_dotenv()
username = os.getenv("AGOL_USERNAME")
password = os.getenv("AGOL_PASSWORD")
gis = GIS("https://www.arcgis.com", username, password)

# Exact URL for the attachment endpoint
base_url = "https://arcgis.com"
image_folder = r"D:\DATA and ANALYTICS CONSULTATION\2026\Nyahururu 2026\Updated Files\images"

# Get token for raw request
token = gis._con.token

print("🚀 Starting Heavy-Duty Upload...")

files = [f for f in os.listdir(image_folder) if f.lower().endswith((".jpg", ".jpeg", ".png"))]

for filename in files:
    try:
        oid = int(filename.split('_')[0])
        img_path = os.path.join(image_folder, filename)
        upload_url = f"{base_url}/{oid}/addAttachment"
        
        print(f"Uploading {filename} to OID {oid}...")
        
        with open(img_path, 'rb') as f:
            files_payload = {'attachment': f}
            data_payload = {'f': 'json', 'token': token}
            
            # Send raw POST request (more stable for bulk)
            response = requests.post(upload_url, files=files_payload, data=data_payload)
            
            if response.status_code == 200:
                res_json = response.json()
                if res_json.get('addAttachmentResult', {}).get('success'):
                    print(f"   ✅ SUCCESS")
                else:
                    print(f"   ❌ FAILED: {res_json}")
            else:
                print(f"   ❌ HTTP Error {response.status_code}")

        # Wait 2 seconds to avoid server rate-limiting
        time.sleep(2)

    except Exception as e:
        print(f"   ❌ ERROR on {filename}: {e}")

print("\n✨ Done. Refresh your ArcGIS table to see the results.")