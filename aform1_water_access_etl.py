import os
import requests
import pandas as pd
import re
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

# 1. SETUP
load_dotenv()
API_TOKEN = os.getenv("KOBO_API_TOKEN")
BASE_URL = "https://eu.kobotoolbox.org/api/v2"

class RedirectionTokenAuth(requests.Session):
    def rebuild_auth(self, prepared_request, response):
        prepared_request.headers['Authorization'] = f'Token {API_TOKEN}'
        return

session = RedirectionTokenAuth()
session.headers.update({'Authorization': f'Token {API_TOKEN}'})

FORMS = {
    'Water': 'aE497GDmCKdDWKUrwTG6Sb'
}

def clean_label(label):
    if isinstance(label, list) and len(label) > 0:
        return str(label[0]).strip()
    return str(label).strip() if label else ""

def get_metadata(uid):
    url = f"{BASE_URL}/assets/{uid}/?format=json"
    try:
        res = session.get(url, timeout=15)
        if res.status_code == 200:
            content = res.json().get('content', {})
            survey = content.get('survey', [])
            choices = content.get('choices', [])
            label_map = {q['name']: clean_label(q.get('label', q['name'])) for q in survey if 'name' in q}
            image_cols = [q['name'] for q in survey if q.get('type') in ['image', 'file', 'photo']]
            choice_map = {str(c['name']): clean_label(c.get('label', c['name'])) for c in choices}
            return label_map, choice_map, image_cols
    except: pass
    return {}, {}, []

def process_form(item):
    name, uid = item
    print(f"--> Syncing: {name}")
    
    label_map, choice_map, image_questions = get_metadata(uid)
    data_url = f"{BASE_URL}/assets/{uid}/data.json"
    
    try:
        res = session.get(data_url, timeout=30)
        res.raise_for_status()
        data = res.json().get('results', [])
        if not data: return None

        df = pd.DataFrame(data)

        # --- 1. ATTACHMENT URL EXTRACTION ---
        url_cols_temp = []
        if '_attachments' in df.columns:
            def get_full_url(row, filename):
                if not filename or pd.isna(filename): return ""
                for a in row.get('_attachments', []):
                    if str(filename) in a.get('filename', ''):
                        return a.get('download_url')
                return ""
            
            for col in df.columns:
                key = col.split('/')[-1] if '/' in col else col
                if key in image_questions:
                    col_name = f"{key}_URL"
                    df[col_name] = df.apply(lambda r: get_full_url(r, r.get(col)), axis=1)
                    url_cols_temp.append(col_name)

        if url_cols_temp:
            def shift_urls(row):
                links = [row[c] for c in url_cols_temp if pd.notna(row[c]) and str(row[c]).strip() != ""]
                return pd.Series(links + [""] * (len(url_cols_temp) - len(links)), index=url_cols_temp)
            df[url_cols_temp] = df.apply(shift_urls, axis=1)

        # --- 2. GPS EXTRACTION ---
        if '_geolocation' in df.columns:
            df['Latitude'] = df['_geolocation'].apply(lambda x: x[0] if isinstance(x, list) and len(x) > 0 else None)
            df['Longitude'] = df['_geolocation'].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else None)

        # --- 3. MERGE PROJECT NAME ---
        target_name = "Indicate the name of the project"
        project_cols = [c for c in df.columns if target_name in str(label_map.get(c.split('/')[-1], c))]
        if not project_cols: project_cols = [c for c in df.columns if target_name in str(c)]

        if project_cols:
            df[target_name] = df[project_cols].replace(['nan', 'None', '', 'nan_1'], pd.NA).bfill(axis=1).iloc[:, 0]
            df.drop(columns=[c for c in project_cols if c != target_name], inplace=True)

        # --- 4. SMART GPS BACKFILL ---
        df['Latitude'] = pd.to_numeric(df['Latitude'], errors='coerce')
        df['Longitude'] = pd.to_numeric(df['Longitude'], errors='coerce')
        if target_name in df.columns:
            df['Latitude'] = df.groupby(target_name)['Latitude'].transform(lambda x: x.ffill().bfill())
            df['Longitude'] = df.groupby(target_name)['Longitude'].transform(lambda x: x.ffill().bfill())

        # 5. CHOICE REPLACEMENT
        data_cols = [c for c in df.columns if not str(c).startswith('_')]
        df[data_cols] = df[data_cols].astype(str).replace(choice_map)

        # 6. MAP HEADERS
        final_headers = []
        for col in df.columns:
            if col in ['Latitude', 'Longitude']:
                final_headers.append(col)
            elif col in url_cols_temp:
                idx = url_cols_temp.index(col) + 1
                final_headers.append(f"image_URL_{idx}")
            else:
                clean_key = col.split('/')[-1] if '/' in col else col
                final_headers.append(label_map.get(clean_key, clean_key))
        df.columns = final_headers

        # --- NEW: CUSTOM RENAMES ---
        df = df.rename(columns={
            "Please Indicate your name": "Enumerator",
            "Select the Ward": "Ward",
            "Select the Location": "Location",
            "Select the Sub-location": "Sub-Location",
            "Select the Village": "Village",
            "Select the section you want to complete":"Phase",
            "Indicate the name of the project":"project_name",
            "Date Water project started.":"activity_project_started",
            "Date water project was completed":"activity_project_completed",
            "Please provide a detailed description of this water point.":"Description"
        })

        # --- NEW: SPLIT PHASE ---
        if "Phase" in df.columns:
            # Split Phase column into Phase and Phase_Description
            df[['Phase', 'phase_description']] = df['Phase'].str.split(':', n=1, expand=True)
            df['Phase'] = df['Phase'].str.strip()
            df['phase_description'] = df['phase_description'].str.strip()

        # --- NEW: SEQUENTIAL REORDERING ---
        anchor_col = "Phase"
        cols_to_move = ["phase_description", "project_name", "Latitude", "Longitude"]
        
        if anchor_col in df.columns:
            base_idx = df.columns.get_loc(anchor_col) + 1
            for col in cols_to_move:
                if col in df.columns:
                    col_data = df.pop(col)
                    df.insert(base_idx, col, col_data)
                    base_idx += 1

        # --- CLEAN ROW DATA ---
        # Splitting cascading location IDs and cleaning Phase if it didn't split perfectly
        def strip_cascading(val):
            if isinstance(val, str) and "_" in val:
                return val.split("_")[-1]
            return val
        
        df = df.map(strip_cascading)

        # 7. EXCLUSION LOGIC
        cols_to_exclude = [
            "start", "end", "Project location (Institution/community)", "Select the type of institution",
            "Indicate the name of the institutuion.", "Please describe how the community accesses drinking water before this water intervention",
            "What health issues and/or dangers related to collection of water exist before this water intervention (select all that apply)?",
            "Indicate the number of households in this village.", "Please indicate the work you plan to do",
            "Please provide a picture of the current water source", "Indicate_the_name_of_the_water_project_001",
            "Please_capture_the_G_for_this_water_point", "Please indicate the work you plan to do on this water project (select all that apply):",
            "Was the water system designed according to engineering standards?", "Please capture a photo of the system design",
            "What is the date of pump installation?", "What kind of pump was installed?", "Indicate the brand and the name of the pump installed.",
            "What is the pumping water level (in meters below ground)?", "What is the intake depth (in meters)?",
            "Please indicate the liters per minute for the pump installed.", "Please capture a photo of the pump/motor assembly.",
            "Please capture a photo of the electrical control panel.", "Please capture a photo of the well pad that shows the construction materials, thickness, and shape.",
            "Please capture a photo of the project in progress", "Please capture a photo of the completed project",
            "Please capture another photo showing a different component of the completed project.",
            "uuid", "instanceid", "formhub", "deprecatedid", "rootuuid", "validation_status", "xform_id",
            "__version__", "_xform_id_string", "_uuid", "_attachments", "_status", "_geolocation", 
            "_submission_time", "_tags", "_notes", "_validation_status", "_submitted_by", "deprecatedID", "rootUuid",
            "image_URL_10", "image_URL_11", "image_URL_12", "image_URL_13", "image_URL_14", 
            "image_URL_15", "image_URL_16", "image_URL_17", "image_URL_18", "image_URL_19", "image_URL_20",
            "Please provide a picture showing the program identification for the threes organizations.",
            "Has the water point reduced the distance users travel to fetch water to a standard 500m or 30 minute round trip?",
"Please provide a picture showing the program identification for the threes organizations.",
"Has the water point reduced the distance users travel to fetch water to a standard 500m or 30 minute round trip?",
"Indicate_the_name_of_the_water_project_004",
"Indicate_the_GPS_location",
"How much new piping was installed through the water system (in meters)",
"How many tapstands were replaced, rehabilitated, or installed?",
"How many valves were added or replaced?",
"Is the storage tank elevated?",
"What is the total water storage volume (in cubic meters)?",
"What water treatment methods are being used as part of this water treatment system (select all that apply)?",
"How much daily potable water can this water treatment system supply (liters per day)?",
"Please capture a photo of the entire water treatment system in operation.",
"Drilling start date",
"Drilling end date",
"Drilling method",
"Aquifer",
"What is the total depth of the borehole? (in meters below ground)",
"What is the static water level? (in meters below ground)",
"What is the depth of the bottom of the sanitary seal of this borehole (in meters below ground)?",
"Was gravel pack installed?",
"What is the depth of the top of the gravel pack (in meters below ground)?",
"Was a formation stabilizer seal placed directly above the gravel pack?",
"What material is used for casing?",
"Depth Final Casing (m)",
"Full Casing",
"Outer Casing Diameter at Widest (mm)",
"Borehole Diameter (mm)",
"Annular Space (mm)",
"Gravel Pack Collapsed",
"Upload the drillers log",
"Picture of drilling in progress",
"Is this a dry borehole?",
"drilling_gps",
"What is the date the yield test was completed?",
"How long was the recovery test duration (in minutes)?",
"What was the static water level before the test was performed (in meters below ground level)?",
"What was the water level when the recovery test was ceased (in meters below ground level)?",
"What is the yield of the borehole? (in meters cubic per hour?)",
"At what rate was the well pumped (in liters per minute)?",
"Can the borehole yield meet the user demand?",
"Provide a scanned document of the water yield test form",
"Indicate_the_name_of_the_water_project_002",
"Where was the sampe analysed?",
"Indicate the name of the lab?",
"Where was the sample collected (i.e., hand pump, tap in school yard, etc.)?",
"What is the date of the water sample collection?",
"When did the test begin?",
"When was the test completed?",
"What is the result of the total coliforms test?",
"What is the result of the total E. coli test?",
"Please provide any other comments about the water quality (taste, odor, color, slime, or other problems).",
"Provide a scanned document of the Water quality test",
"Were any values out of range?",
"Explain the values out of range",
"What is the decision on the water use based on the water quality test results?",
"Indicate_the_name_of_the_water_project_003",
"Provide a picture of a community member holding safe water.",
"How many people use this water point to draw clean water?",
"How many of these people are served within a 30 minute round trip?",
"What security measures have been put in place to protect the investment?",
"Is there a water user management committee managing this water point?",
"If yes, how many committee members?",
"How will the sustainability and long term use of the water point be ensured",
"Indicate_the_name_of_the_water_project_005",
"Record_your_current_location",
"Other (specify)",
"If a hydrogeological survey was performed, please upload the PDF of the hydrogeological survey.",
"Please provide a photo of the potential drilling site including context (nearby buildings, fields, community, etc.).",
"Why Not Full Casing",
"Collect GPS location for this site",
"gps_project_name",
"Thank you",
"Other"
            
        ]

        cols_to_drop = [c for c in df.columns if any(str(c).strip().lower() == str(e).strip().lower() for e in cols_to_exclude)]
        df.drop(columns=cols_to_drop, errors='ignore', inplace=True)

        df = df.copy() 
        df.insert(0, 'Source_Form', name)
        return df
    except Exception as e:
        print(f"Failed {name}: {e}")
        return None

if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = [d for d in list(executor.map(process_form, FORMS.items())) if d is not None]

    if results:
        master_df = pd.concat(results, ignore_index=True, sort=False)
        output_file = "aform1_water_access_etl.xlsx"
        master_df.to_excel(output_file, index=False)
        print(f"\nSUCCESS! Master file created: {output_file}")
