import pandas as pd
import requests
import os
import time
from dotenv import load_dotenv
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------
# 0. LOAD ENV VARIABLES
# ---------------------------
dotenv_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=dotenv_path)

KOBO_API_TOKEN = os.getenv("KOBO_API_TOKEN")
AGOL_USERNAME = os.getenv("AGOL_USERNAME")
AGOL_PASSWORD = os.getenv("AGOL_PASSWORD")
AGOL_REFERER = os.getenv("AGOL_REFERER")
FEATURE_LAYER_URL = os.getenv("ARCGIS_FEATURE_LAYER_URL")

if not all([KOBO_API_TOKEN, AGOL_USERNAME, AGOL_PASSWORD, AGOL_REFERER, FEATURE_LAYER_URL]):
    raise ValueError("❌ Missing environment variables in .env")

headers_kobo = {"Authorization": f"Token {KOBO_API_TOKEN}"}


# ---------------------------
# 1. CONFIGURATION
# ---------------------------
input_csv = r"D:\DATA and ANALYTICS CONSULTATION\2026\Nyahururu 2026\Nyahururu_Projects_Master_final_v1.csv"
save_dir = r"D:\DATA and ANALYTICS CONSULTATION\2026\Nyahururu 2026\images_v1"
output_csv = r"D:\DATA and ANALYTICS CONSULTATION\2026\Nyahururu 2026\Nyahururu_Projects_ArcGIS_final_v1.csv"

os.makedirs(save_dir, exist_ok=True)

# ---------------------------
# 2. LOAD CSV
# ---------------------------
df = pd.read_csv(input_csv, encoding="latin1")

print(f"✅ CSV loaded: {len(df)} rows")
print("📌 Columns found:", list(df.columns))

# ---------------------------
# 3. DETECT OBJECT ID FIELD
# ---------------------------
possible_ids = ["OBJECTID", "ObjectId", "objectid", "FID"]

object_id_field = None
for col in possible_ids:
    if col in df.columns:
        object_id_field = col
        break

if object_id_field is None:
    raise ValueError("❌ No OBJECTID field found in CSV")

print(f"✅ Using OBJECT ID field: {object_id_field}")

# ---------------------------
# 4. IMAGE FIELDS
# ---------------------------
IMAGE_FIELDS = [col for col in df.columns if col.startswith("pre_img")]
print(f"🖼️ Image fields detected: {IMAGE_FIELDS}")

# ---------------------------
# 5. DOWNLOAD IMAGE FUNCTION
# ---------------------------
def download_image(url, prefix, idx, retries=3, delay=2):
    if pd.isna(url) or str(url).strip() == "":
        return None

    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers_kobo, timeout=15)

            if resp.status_code == 200:
                filename = os.path.join(save_dir, f"{prefix}_{idx}.jpg")
                with open(filename, "wb") as f:
                    f.write(resp.content)
                return filename
            else:
                print(f"❌ {url} -> HTTP {resp.status_code} (Attempt {attempt+1})")

        except Exception as e:
            print(f"❌ Download error: {e} (Attempt {attempt+1})")

        time.sleep(delay)

    return None

# ---------------------------
# 6. MULTITHREAD DOWNLOAD
# ---------------------------
def download_images_multithread(urls, prefix):
    results = [None] * len(urls)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(download_image, url, prefix, i): i
            for i, url in enumerate(urls)
        }

        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                print(f"❌ Download error at index {idx}: {e}")

    return results

# ---------------------------
# 7. DOWNLOAD ALL IMAGES
# ---------------------------
for field in IMAGE_FIELDS:
    print(f"\n⬇️ Downloading {field}...")
    df[f"{field}_path"] = download_images_multithread(df[field].tolist(), field)

# ---------------------------
# 8. GET AGOL TOKEN
# ---------------------------
def get_agol_token(username, password, referer):
    url = "https://www.arcgis.com/sharing/rest/generateToken"
    data = {
        "username": username,
        "password": password,
        "referer": referer,
        "f": "json",
        "expiration": 60
    }

    resp = requests.post(url, data=data)
    resp.raise_for_status()

    token = resp.json().get("token")
    if not token:
        raise ValueError("❌ Failed to get AGOL token")

    return token

print("\n🔐 Logging into ArcGIS Online...")
AGOL_TOKEN = get_agol_token(AGOL_USERNAME, AGOL_PASSWORD, AGOL_REFERER)
print("✅ AGOL Token obtained")

# ---------------------------
# 9. ATTACHMENT CACHE
# ---------------------------
attachment_cache = {}

def get_existing_attachments(objectid):
    if objectid in attachment_cache:
        return attachment_cache[objectid]

    url = f"{FEATURE_LAYER_URL}/{objectid}/attachments"
    params = {"f": "json", "token": AGOL_TOKEN}

    try:
        resp = requests.get(url, params=params)
        data = resp.json()

        files = [att["name"] for att in data.get("attachmentInfos", [])]
        attachment_cache[objectid] = files
        return files

    except Exception as e:
        print(f"❌ Failed to fetch attachments for {objectid}: {e}")
        return []

# ---------------------------
# 10. UPLOAD FUNCTION
# ---------------------------
def upload_attachment(objectid, img_path):
    if not img_path:
        return None

    filename = os.path.basename(img_path)

    # 🔍 Check duplicates
    existing_files = get_existing_attachments(objectid)

    if filename in existing_files:
        print(f"⏭️ Skipping duplicate: {filename} (OBJECTID {objectid})")
        return f"Skipped: {filename}"

    url = f"{FEATURE_LAYER_URL}/{objectid}/addAttachment"

    try:
        with open(img_path, "rb") as f:
            files = {"file": (filename, f, "image/jpeg")}
            data = {"f": "json", "token": AGOL_TOKEN}

            resp = requests.post(url, data=data, files=files, timeout=30)

        result = resp.json()

        if result.get("addAttachmentResult", {}).get("success"):
            attach_id = result["addAttachmentResult"]["objectId"]

            # update cache
            attachment_cache.setdefault(objectid, []).append(filename)

            print(f"✅ Uploaded: {filename} → OBJECTID {objectid}")
            return f"{FEATURE_LAYER_URL}/{objectid}/attachments/{attach_id}"
        else:
            print(f"❌ Upload failed: {filename} → {result}")
            return None

    except Exception as e:
        print(f"❌ Upload error: {e}")
        return None

# ---------------------------
# 11. MULTITHREAD UPLOAD
# ---------------------------
def upload_multithread(objectids, paths, field):
    results = [None] * len(paths)

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(upload_attachment, objid, path): i
            for i, (objid, path) in enumerate(zip(objectids, paths))
        }

        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                print(f"❌ Upload error ({field}) at {idx}: {e}")

    return results

# ---------------------------
# 12. UPLOAD ALL IMAGES
# ---------------------------
for field in IMAGE_FIELDS:
    print(f"\n⬆️ Uploading {field}...")
    df[f"{field}_arcgis"] = upload_multithread(
        df[object_id_field].tolist(),
        df[f"{field}_path"].tolist(),
        field
    )

# ---------------------------
# 13. SAVE OUTPUT
# ---------------------------
df.to_csv(output_csv, index=False)

print("\n🎉 DONE!")
print(f"📄 Output saved to:\n{output_csv}")