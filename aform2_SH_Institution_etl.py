import requests
import os
import pandas as pd
import re
from io import StringIO

# =========================
# CONFIGURATION
# =========================
API_TOKEN = os.getenv("KOBO_API_TOKEN")
BASE_URL = "https://eu.kobotoolbox.org/api/v2"
FORM_UID = "aAocE38i77TjFybswfeTJp"

headers = {"Authorization": f"Token {API_TOKEN}"}

# =========================
# STEP 1: FETCH LABEL MAPPING
# =========================
def get_human_labels():
    """Fetches the actual question text for every XML slug."""
    url = f"{BASE_URL}/assets/{FORM_UID}/"
    print("Fetching human-readable labels from form definition...")
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    
    asset_data = response.json()
    survey = asset_data.get('content', {}).get('survey', [])
    
    label_map = {}
    for item in survey:
        name = item.get('name')
        label = item.get('label')
        if name and label:
            label_text = label[0] if isinstance(label, list) else label
            label_map[name] = label_text
            
    return label_map

# =========================
# STEP 2: DOWNLOAD DATA
# =========================
def fetch_kobo_data():
    url = f"{BASE_URL}/assets/{FORM_UID}/data/?format=json"
    print(f"Downloading Kobo records from: {url}")
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    
    results = response.json().get('results', [])
    return pd.DataFrame(results)

# =========================
# MAIN PIPELINE
# =========================
def main():
    # A. Get the raw data
    df = fetch_kobo_data()
    if df.empty:
        print("No data found.")
        return

    # B. Get the dictionary of labels
    label_dict = get_human_labels()

    # C. Initial Clean: Remove group prefixes
    df.columns = [c.split('/')[-1] for c in df.columns]

    # D0. ADD SOURCE FORM COLUMN (AS FIRST COLUMN)
    df.insert(0, 'Source_Form', 'SH-Institution')

    # D1. CALCULATE TOTALS
    #m_adults = "Indicate_the_number_nstitution_household"
    #f_adults = "Indicate_the_number_nstitution_household_001"
    #if m_adults in df.columns and f_adults in df.columns:
     #   df['Total Adults'] = pd.to_numeric(df[m_adults], errors='coerce').fillna(0) + \
      #                       pd.to_numeric(df[f_adults], errors='coerce').fillna(0)

    # f_child = "Indicate_the_number_nstitution_household_002"
    # m_child = "Indicate_the_number_nstitution_household_003"
    # if f_child in df.columns and m_child in df.columns:
    #     df['Total Children'] = pd.to_numeric(df[f_child], errors='coerce').fillna(0) + \
      #                          pd.to_numeric(df[m_child], errors='coerce').fillna(0)

    # D2. CONSOLIDATE PROJECT COLUMNS
    target_col = "Provide_a_potential_ion_facility_project"
    source_cols = ["Indicate_the_name_of_ion_facility_project", "Indicate_the_name_of_ion_facility_project_001"]
    anchor_col = "form_type"
    
    for source in source_cols:
        if source in df.columns and target_col in df.columns:
            df[target_col] = df[target_col].fillna(df[source])
            df.drop(columns=[source], inplace=True)

    # D3. EXTRACT COORDINATES & ATTACHMENT URLs
    if '_geolocation' in df.columns:
        df['Latitude'] = df['_geolocation'].apply(lambda x: x[0] if isinstance(x, list) and len(x) > 0 else None)
        df['Longitude'] = df['_geolocation'].apply(lambda x: x[1] if isinstance(x, list) and len(x) > 1 else None)

    if '_attachments' in df.columns:
        def extract_urls(attachments):
            if isinstance(attachments, list):
                return [a.get('download_url') for a in attachments if 'download_url' in a]
            return []
        urls_series = df['_attachments'].apply(extract_urls)
        max_attachments = urls_series.apply(len).max()
        for i in range(max_attachments):
            df[f'image_URL_{i+1}'] = urls_series.apply(lambda x: x[i] if len(x) > i else None)

    # D4. REORDER COLUMNS
    date_start = "Indicate_the_date_th_project_was_started"
    date_end = "Indicate_the_date_th_roject_was_completed"
    
    if anchor_col in df.columns:
        base_idx = df.columns.get_loc(anchor_col) + 1
        cols_to_move = [target_col, 'Latitude', 'Longitude', date_start, date_end]
        for col in cols_to_move:
            if col in df.columns:
                col_data = df.pop(col)
                if isinstance(col_data, pd.DataFrame):
                    col_data = col_data.iloc[:, 0]
                df.insert(base_idx, col, col_data)
                base_idx += 1

    # E. Clean Row Data (Enhanced fix for both __ and _ prefixes)
    def strip_cascading_prefixes(value):
        if isinstance(value, str) and "_" in value:
            return value.split("_")[-1]
        return value
    
    df = df.map(strip_cascading_prefixes)

    # F. Rename Slugs to Human Labels
    new_cols = []
    for col in df.columns:
        if col in label_dict:
            new_cols.append(label_dict[col])
        else:
            base_col = re.sub(r'_\d{3}$', '', str(col))
            new_cols.append(label_dict.get(base_col, col))
    df.columns = new_cols

    # G. CUSTOM RENAMES
    df = df.rename(columns={
        "Please indicate your name": "Enumerator",
        "Select the Ward": "Ward",
        "Select the Location": "Location",
        "Select the Sub-Location": "Sub-Location",
        "Select the Village/Community": "Village",
        "Which form is this?": "Phase",
        "Indicate the date the sanitation project was started.": "activity_project_started",
        "Indicate the date the sanitation project was completed": "activity_project_completed",
        "Breify describe the key challenges faced regarding the institutions sanitation facility": "Description",
        "Provide_a_potential_ion_facility_project":"project_name"
    })

     # ========================================================
    # NEW STEP: CREATE PHASE & PHASE DESCRIPTION
    # ========================================================
    # Dictionary to map technical name -> [Phase #, Description]
    phase_map = {
        'assessment':  ['Phase 1', 'Preliminary Assessment'],
        'construction': ['Phase 2', 'Civil Works Construction'],
        'verification': ['Phase 3', 'Project Verification']
    }

    if "Phase" in df.columns:
        # Create the new 'Phase Description' column first
        df['phase_description'] = df['Phase'].map(lambda x: phase_map.get(x, [x, ''])[1])
        # Update the original 'Phase' column to show the Phase #
        df['Phase'] = df['Phase'].map(lambda x: phase_map.get(x, [x, ''])[0])
        
        # Move Phase Description to be right after Phase
        idx = df.columns.get_loc("Phase") + 1
        desc_data = df.pop("phase_description")
        df.insert(idx, "phase_description", desc_data)

    # ========================================================
    # H. UPDATED EXCLUSION LIST
    # ========================================================
    cols_to_exclude = [
        "uuid", "start", "end",
        "What specific issues were observed with the Institution's sanitation facility that make this institution eligible for program support?",
        "Type of sanitation facility currently in use.",
        "Does the institution have a reliable source of water for sanitation purposes?",
        "Indicate the number of male adults in the institution",
        "Indicate the number of female adults in the institution",
        "Indicate the number of female children in the institution",
        "Indicate the number of male children in the institution",
        "Indicate the toilet to pupil ratio for boys.",
        "Indicate the toilet to pupil ratio for girls.",
        "Indicate the number of people with disability.",
        "Is there a regular cleaning and maintenance schedule for the sanitation facility?",
        "Does the institution have any partnerships or partnership plans for sanitation facility improvement?",
        "Photo of sanitation facility currently in use",
        "A different angle of the sanitation facility currently in use.",
        "What reccomendations do you have for improving the sanitation facility in the institution.",
        "Record your current location", "__version__", "instanceID", "_xform_id_string", "_uuid",
        "rootUuid", "_attachments", "_status", "_geolocation", "_submission_time", "_tags", "_notes",
        "_validation_status", "_submitted_by", "Indicate the type of institution where the sanaitation project was constructed.",
        "Select the name of the school", "What type of sanitation facility has been constructed?",
        "Based on JMP criteria, what is the sanitation service level of the completed sanitation facility?",
        "Describe the construction details of the sanitation facility.",
        "In what areas did the community/insititution contribute",
        "Please quantify the contribution in dollars (in USD, $)",
        "Is there a functional hand washing station with soap and water near the sanitation facility?",
        "Does the sanitation facility include disability freindly features?",
        "How many stances does the sanitation facility have?",
        "How many stances are available for females only?",
        "How many stances are available for males only",
        "Was_a_urinal_constructed_for_the_boys",
        "How many stances are available for people with physical disabilities?",
        "How many stances are for staff only.",
        "Provide a picture of construction in progress (Photo 1)",
        "Provide a picture of construction in progress (Photo 2)",
        "Please provide the GPS coordinates of the sanitation facility.",
        "After the construction of this sanitation facility, has the school complied to the toilet pupil ratio for boys as reccomenred by the National standards?",
        "What is the toilet to pupil ratio for boys",
        "Upload_the_design_of_sanitation_facility",
        "Did the beneficiaries fulfill all the MOU commitments for sanitation facility construction in the required time period?",
        "Upload_the_signed_MO_angelization_program",
        "Please provide a picture of the hand washing station showing the soap and water flowing.",
        "Please provide a picture of the exterioir of the completed sanitation facility",
        "Please provide a picture of the interior of the completed sanitation facility.",
        "Provide a photo of the program logos identification at this sanitation facility.",
        "Record_the_GPS", "deprecatedID", "How many stances have menstraul hygiene facilities?",
        "Indicate_the_number_sanitation_facility", "Others (specify)",
        "After the construction of this sanitation facility, has the school complied to the toilet pupil ratio for girls as reccomenred by the National standards?",
        "What is the toilet to pupil ratio for girls?", "Please_Indicate_your_name",
        "Is_the_sanitation_located_in_a", "Indicate the type of institution being assesed.",
        "Indicate_the_name_of_n_project_is_located_001", "Did_the_beneficiarie_required_time_period",
        "What_committments_we_the_MOU_commitments", "List_other_materials_used_in_c","Indicate the date this assesment was conducted."
    ]
    
    df.drop(columns=[c for c in cols_to_exclude if c in df.columns], inplace=True)

    # I. Final Formatting for Excel
    for col in df.columns:
        column_data = df.iloc[:, df.columns.get_loc(col)] if df.columns.tolist().count(col) > 1 else df[col]
        if column_data.apply(lambda x: isinstance(x, (list, dict))).any():
            df[col] = df[col].astype(str)

    # J. Save Output
    output_file = "aform2_SH_Institution_etl.xlsx"
    df.to_excel(output_file, index=False)
    print(f"Success! Filtered data with Source_Form saved to {output_file}")

if __name__ == "__main__":
    main()
