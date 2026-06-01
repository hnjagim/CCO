import os
import pandas as pd
import requests
from dotenv import load_dotenv
from arcgis.gis import GIS
from arcgis.features import FeatureLayer
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

# =========================
# 1. LOAD ENV
# =========================
load_dotenv()

AGOL_USERNAME = os.getenv("AGOL_USERNAME")
AGOL_PASSWORD = os.getenv("AGOL_PASSWORD")
KOBO_TOKEN = os.getenv("KOBO_API_TOKEN")

LAYER_URL = os.getenv("NEW_ARCGIS_FEATURE_LAYER_URL")

# =========================
# 2. CONNECT ARCGIS
# =========================
gis = GIS("https://www.arcgis.com", AGOL_USERNAME, AGOL_PASSWORD)
fl = FeatureLayer(LAYER_URL)

# =========================
# 3. LOAD CSV
# =========================
csv_path = r"D:\DATA and ANALYTICS CONSULTATION\2026\Nyahururu 2026\Updated Files\Nyahururu_Projects_Master_final_v1.csv"
df = pd.read_csv(csv_path, encoding="latin1")

# =========================
# 4. IMAGE DIRECTORY
# =========================
image_dir = r"D:\DATA and ANALYTICS CONSULTATION\2026\Nyahururu 2026\Updated Files\images"
os.makedirs(image_dir, exist_ok=True)

# =========================
# 5. LOG FILE
# =========================
log_file = os.path.join(image_dir, "upload_log.xlsx")
log_data = []

# =========================
# 6. IMAGE COLUMNS
# =========================
image_cols = [
    "pre_img0", "pre_img1", "pre_img2", "pre_img3", "pre_img4",
    "pre_img5", "pre_img6", "pre_img7", "pre_img8"
]

# =========================
# 7. RETRY FUNCTION
# =========================
def download_image(url, retries=3):

    headers = {
        "Authorization": f"Token {KOBO_TOKEN}"
    }

    for i in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=40)

            print(f"DEBUG STATUS: {r.status_code} | {url}")

            if r.status_code == 200:
                return r.content

        except Exception as e:
            print(f"Retry {i+1} failed: {e}")

    return None

# =========================
# 8. PROCESS SINGLE IMAGE
# =========================
def process_image(project_id, col, url):
    if pd.isna(url) or str(url).strip() == "":
        return None

    img_data = download_image(url)

    if img_data is None:
        return (project_id, col, "FAILED", "Download failed")

    file_path = os.path.join(image_dir, f"{project_id}_{col}.jpg")

    try:
        with open(file_path, "wb") as f:
            f.write(img_data)

        fl.attachments.add(project_id, file_path)

        return (project_id, col, "SUCCESS", "")

    except Exception as e:
        return (project_id, col, "FAILED", str(e))

# =========================
# 9. MAIN PROCESS (PARALLEL)
# =========================
tasks = []

print("Starting processing...\n")

for _, row in df.iterrows():
    project_id = row["ProjectId"]

    for col in image_cols:
        url = row.get(col)
        tasks.append((project_id, col, url))

results = []

with ThreadPoolExecutor(max_workers=6) as executor:
    futures = [
        executor.submit(process_image, pid, col, url)
        for pid, col, url in tasks
    ]

    for f in tqdm(as_completed(futures), total=len(futures)):
        result = f.result()
        if result:
            results.append(result)

# =========================
# 10. SAVE EXCEL LOG
# =========================
log_df = pd.DataFrame(results, columns=["ProjectId", "ImageColumn", "Status", "Error"])
log_df.to_excel(log_file, index=False)

print("\nDONE ✔")
print(f"Log saved to: {log_file}")