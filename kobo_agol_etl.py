import os
import requests
import pandas as pd
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

# 1. SETUP
load_dotenv()
API_TOKEN = os.getenv("KOBO_API_TOKEN")
# Fixed to your required EU address
BASE_URL = "https://eu.kobotoolbox.org/api/v2"

# --- REDIRECT FIX: Ensures Token persists during server redirects ---
class RedirectionTokenAuth(requests.Session):
    def rebuild_auth(self, prepared_request, response):
        prepared_request.headers['Authorization'] = f'Token {API_TOKEN}'
        return

session = RedirectionTokenAuth()
session.headers.update({'Authorization': f'Token {API_TOKEN}'})

FORMS = {
    'Water': 'aE497GDmCKdDWKUrwTG6Sb'
    #'SH_Institutions': 'aAocE38i77TjFybswfeTJp'
    #'SH_Households': 'aiRYEqZYTAm2zS9hx3PrcK'
    #'CCM': 'a4LCRjghfiBJmxW7F2nuXD'
}

def clean_label(label):
    """Safely extracts label string and handles multi-language lists."""
    if isinstance(label, list) and len(label) > 0:
        return str(label[0]).strip()
    return str(label).strip() if label else ""

def force_unique_columns(df):
    """Numbers duplicate column labels to prevent Pandas Index crashes."""
    cols = []
    count = {}
    for col in df.columns:
        col_name = clean_label(col)
        if col_name in count:
            count[col_name] += 1
            cols.append(f"{col_name}_{count[col_name]}")
        else:
            count[col_name] = 0
            cols.append(col_name)
    df.columns = cols
    return df

def get_metadata(uid):
    """Fetches labels, image columns, and choice mappings from EU server."""
    # Suffix /? is mandatory for EU server API stability
    url = f"{BASE_URL}/assets/{uid}/?format=json"
    try:
        res = session.get(url, timeout=15)
        if res.status_code == 200:
            content = res.json().get('content', {})
            survey = content.get('survey', [])
            choices = content.get('choices', [])
            
            label_map = {q['name']: clean_label(q.get('label', q['name'])) for q in survey if 'name' in q}
            image_cols = [q['name'] for q in survey if q.get('type') in ['image', 'file']]
            choice_map = {str(c['name']): clean_label(c.get('label', c['name'])) for c in choices}
            
            return label_map, image_cols, choice_map
    except: pass
    return {}, [], {}

def process_form(item):
    name, uid = item
    print(f"--> Syncing: {name}")
    
    label_map, image_questions, choice_map = get_metadata(uid)
    data_url = f"{BASE_URL}/assets/{uid}/data.json"
    
    try:
        res = session.get(data_url, timeout=30)
        res.raise_for_status()
        data = res.json().get('results', [])
        if not data: return None

        df = pd.DataFrame(data)

        # 1. ATTACHMENT URLs (Run BEFORE Choice Replacement)
        if '_attachments' in df.columns:
            def get_url(row, filename):
                if not filename or pd.isna(filename) or str(filename).lower() in ['nan', 'none']: return ""
                attachments = row.get('_attachments', [])
                if isinstance(attachments, list):
                    for a in attachments:
                        if str(filename) in a.get('filename', ''):
                            return a.get('download_url')
                return ""
            
            for col in df.columns:
                key = col.split('/')[-1] if '/' in col else col
                if key in image_questions:
                    full_label = label_map.get(key, key)
                    df[f"{full_label}_URL"] = df.apply(lambda r: get_url(r, r.get(col)), axis=1)

        # 2. CHOICE REPLACEMENT (Map codes like J9K7 to actual text)
        # We target only data columns to avoid breaking system lists like _attachments
        data_cols = [c for c in df.columns if not str(c).startswith('_')]
        df[data_cols] = df[data_cols].astype(str).replace(choice_map)

        # 3. MAP HEADERS TO FULL LABELS
        new_headers = []
        for col in df.columns:
            if "_URL" in str(col): 
                new_headers.append(col)
                continue
            
            clean_key = col.split('/')[-1] if '/' in col else col
            
            if 'latitude' in clean_key.lower(): new_headers.append("Latitude")
            elif 'longitude' in clean_key.lower(): new_headers.append("Longitude")
            else:
                new_headers.append(label_map.get(clean_key, clean_key))
        
        df.columns = new_headers
        df = force_unique_columns(df)
        
        # 4. CLEANING: Drop technical metadata (uuid, meta, etc.)
        trash = ['uuid', 'instanceid', 'formhub', 'deprecatedid', 'rootuuid', 'validation_status', 'xform_id']
        cols_to_keep = [
            c for c in df.columns 
            if not any(k in str(c).lower() for k in trash) 
            and (not str(c).startswith('_') or any(x in str(c).lower() for x in ['latitude', 'longitude', 'id']))
        ]
        df = df[cols_to_keep]
        
        df.insert(0, 'Source_Form', name)
        print(f"Success: {name}")
        return df
    except Exception as e:
        print(f"Failed {name}: {e}")
        return None

if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = [d for d in list(executor.map(process_form, FORMS.items())) if d is not None]

    if results:
        master_df = pd.concat(results, ignore_index=True, sort=False)
        output = "Kobo_Master_Final_Full_Labels-Water.xlsx"
        master_df.to_excel(output, index=False)
        print(f"\nSUCCESS! Master file created: {output}")
    else:
        print("\nNo data retrieved. Verify your Token and EU Server access.")