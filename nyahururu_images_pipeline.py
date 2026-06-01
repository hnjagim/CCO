# nyahururu_images_pipeline_multithread.py
import pandas as pd
import requests
import os
import time
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys

# ---------------------------
# 0. LOAD ENV VARIABLES
# ---------------------------
load_dotenv()  # loads KOBO_API_TOKEN from .env
API_TOKEN = os.getenv("KOBO_API_TOKEN")
if not API_TOKEN:
    sys.exit("Error: KOBO_API_TOKEN not found in .env file!")

headers = {"Authorization": f"Token {API_TOKEN}"}

# ---------------------------
# 1. CONFIGURATION
# ---------------------------
input_csv = r"D:\DATA and ANALYTICS CONSULTATION\2026\Nyahururu 2026\Nyahururu_Projects_Master_final.csv"
save_dir = r"D:\DATA and ANALYTICS CONSULTATION\2026\Nyahururu 2026\images"
output_csv = r"D:\DATA and ANALYTICS CONSULTATION\2026\Nyahururu 2026\Nyahururu_Projects_ArcGIS.csv"
os.makedirs(save_dir, exist_ok=True)

# ---------------------------
# 2. LOAD CSV
# ---------------------------
df = pd.read_csv(input_csv, encoding="latin1")
print(f"CSV loaded: {len(df)} rows")
print("Columns:", df.columns)

# ---------------------------
# 3. HELPER FUNCTION TO DOWNLOAD IMAGE
# ---------------------------
def download_image(url, prefix, idx, retries=3, delay=2):
    """
    Download image from URL with retries and returns local path
    """
    if pd.isna(url) or url.strip() == "":
        return None
    attempt = 0
    while attempt < retries:
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                filename = os.path.join(save_dir, f"{prefix}_{idx}.jpg")
                with open(filename, "wb") as f:
                    f.write(response.content)
                return filename
            else:
                print(f"Failed {url}: Status {response.status_code} (Attempt {attempt + 1})")
                attempt += 1
                time.sleep(delay)
        except Exception as e:
            print(f"Error {url}: {e} (Attempt {attempt + 1})")
            attempt += 1
            time.sleep(delay)
    print(f"Skipping {url} after {retries} attempts")
    return None

# ---------------------------
# 4. MULTITHREAD DOWNLOAD FUNCTION
# ---------------------------
def download_images_multithread(urls, prefix, max_workers=5):
    results = [None] * len(urls)
    tasks = [(i, url) for i, url in enumerate(urls)]
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {executor.submit(download_image, url, prefix, idx): idx for idx, url in tasks}
        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                print(f"Error downloading {urls[idx]}: {e}")
                results[idx] = None
    return results

# ---------------------------
# 5. DOWNLOAD BOTH IMAGE COLUMNS
# ---------------------------
print("Downloading pre_img1...")
df["pre_img1_path"] = download_images_multithread(df["pre_img1"].tolist(), "pre_img1", max_workers=5)

print("Downloading pre_img2...")
df["pre_img2_path"] = download_images_multithread(df["pre_img2"].tolist(), "pre_img2", max_workers=5)

# ---------------------------
# 6. SAVE ARC-GIS READY CSV
# ---------------------------
df.to_csv(output_csv, index=False)
print(f"ArcGIS-ready CSV saved: {output_csv}")
print("Done ✅")