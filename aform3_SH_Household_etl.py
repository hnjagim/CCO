import os
import requests
import pandas as pd
from dotenv import load_dotenv

# =====================================================
# 1. LOAD ENVIRONMENT VARIABLES
# =====================================================
load_dotenv()
API_TOKEN = os.getenv("KOBO_API_TOKEN")

# =====================================================
# 2. KOBO SETTINGS
# =====================================================
BASE_URL = "https://eu.kobotoolbox.org/api/v2"
FORM_UID = "aiRYEqZYTAm2zS9hx3PrcK"

headers = {
    "Authorization": f"Token {API_TOKEN}",
    "User-Agent": "Mozilla/5.0"
}

# =====================================================
# 3. FETCH FORM SCHEMA (For Labels)
# =====================================================
print("Fetching form schema...")
schema_url = f"{BASE_URL}/assets/{FORM_UID}/"
schema_response = requests.get(schema_url, headers=headers)

if schema_response.status_code != 200:
    print("❌ Failed to fetch form schema")
    exit()

asset_data = schema_response.json()
survey = asset_data.get("content", {}).get("survey", [])

label_map = {}
for item in survey:
    field_name = item.get("name")
    label = item.get("label")
    
    if isinstance(label, list):
        label = next((x for x in label if x), field_name)
    elif isinstance(label, dict):
        label = next(iter(label.values()), field_name)
    elif not label:
        label = field_name
        
    label_map[field_name] = str(label)

# =====================================================
# 4. DOWNLOAD DATA SUBMISSIONS
# =====================================================
print("Downloading Kobo submissions...")
data_url = f"{BASE_URL}/assets/{FORM_UID}/data/"
all_data = []
next_url = data_url

while next_url:
    response = requests.get(next_url, headers=headers)
    if response.status_code != 200:
        print("❌ Failed to fetch submissions")
        exit()
    
    data = response.json()
    all_data.extend(data.get("results", []))
    next_url = data.get("next")

# =====================================================
# 5. DATA CLEANING FUNCTIONS
# =====================================================
def fix_hierarchy_repeats(val):
    if not isinstance(val, str) or not val.strip():
        return val
    
    if "." in val and any(char.isdigit() for char in val):
        return val
        
    parts = val.split("_")
    last_item = parts[-1] 
    return last_item.replace("_", " ").title()

# =====================================================
# 6. PROCESS DATAFRAME
# =====================================================
print("Processing data, GPS, and Phase logic...")
df = pd.json_normalize(all_data, sep="/")

# --- EXTRACT LAT/LONG FROM _geolocation LIST ---
if '_geolocation' in df.columns:
    df['Latitude'] = df['_geolocation'].apply(lambda x: x[0] if isinstance(x, list) and len(x) >= 2 else None)
    df['Longitude'] = df['_geolocation'].apply(lambda x: x[1] if isinstance(x, list) and len(x) >= 2 else None)
    print("✅ Latitude and Longitude extracted.")

# --- EXTRACT ALL FILE URLs SEQUENTIALLY (image_URL_n) ---
if '_attachments' in df.columns:
    def get_all_file_urls(attachments):
        if not isinstance(attachments, list): return []
        return [a.get('download_url') for a in attachments if a.get('download_url')]

    url_series = df['_attachments'].apply(get_all_file_urls)
    max_files = url_series.map(len).max() if not url_series.empty else 0
    
    for i in range(max_files):
        df[f'image_URL_{i+1}'] = url_series.apply(lambda x: x[i] if len(x) > i else None)
    print(f"✅ Created {max_files} sequential image_URL columns.")

# Map column headers to human-readable labels
new_columns = []
for col in df.columns:
    last_part = col.split("/")[-1]
    if col in ['Latitude', 'Longitude'] or col.startswith('image_URL_'):
        new_columns.append(col)
    else:
        new_columns.append(label_map.get(last_part, col))
df.columns = new_columns

# Fix Fragmentation warning
df = df.copy()

# --- SHORTEN SPECIFIC COLUMN NAMES ---
rename_dict = {
    "Indicate your name": "Enumerator",
    "Indicate the Ward": "Ward",
    "Indicate the location": "Location",
    "Indicate the Sub-location": "Sub-Location",
    "Indicate the Village": "Village",
    "Select CLTS stage you are reporting": "phase_description",
    "Select the activity you are reporting":"project_name",
    "Date the training was held.": "activity_project_started",
    "Provide a detailed description of this sanitation and hygine activity.": "Description"
}
df.rename(columns=rename_dict, inplace=True)

# Create completed date as a duplicate of started date
if "activity_project_started" in df.columns:
    col_idx = df.columns.get_loc("activity_project_started")
    df.insert(col_idx + 1, "activity_project_completed", df["activity_project_started"])
    print("✅ Created 'activity_project_started' and 'activity_project_completed' columns.")

# --- NEW: CALCULATE PHASE AND ORDER: Village -> Phase -> Phase Description ---
if "phase_description" in df.columns:
    # First apply standard hierarchy fix to the values
    df['phase_description'] = df['phase_description'].apply(fix_hierarchy_repeats)
    
    # Logic: Change "Up" to "Follow Up"
    df['phase_description'] = df['phase_description'].replace("Up", "Follow Up")

    # Map Descriptions to Phase Numbers
    phase_mapping = {
        "Triggering": "Phase 1",
        "Follow Up": "Phase 2",
        "Claiming": "Phase 3",
        "Verification": "Phase 4",
        "Certification": "Phase 5"
    }
    
    # Create the 'Phase' column
    df['Phase'] = df['phase_description'].map(lambda x: phase_mapping.get(x, ""))
    
    # Reorder columns: Village -> Phase -> Phase Description
    if "Village" in df.columns:
        # Move Phase after Village
        col_phase = df.pop("Phase")
        village_idx = df.columns.get_loc("Village")
        df.insert(village_idx + 1, "Phase", col_phase)
        
        # Move Phase Description after Phase
        col_desc = df.pop("phase_description")
        phase_idx = df.columns.get_loc("Phase")
        df.insert(phase_idx + 1, "phase_description", col_desc)
        print("✅ Reordered: Village -> Phase -> Pphase_description.")

# --- NEW: REORDER GPS AFTER project_name ---
if "project_name" in df.columns:
    proj_idx = df.columns.get_loc("project_name")
    if "Longitude" in df.columns:
        col_lon = df.pop("Longitude")
        df.insert(proj_idx + 1, "Longitude", col_lon)
    if "Latitude" in df.columns:
        col_lat = df.pop("Latitude")
        df.insert(proj_idx + 1, "Latitude", col_lat)
    print("✅ Moved Latitude and Longitude after 'project_name'.")

# --- EXCLUDE SPECIFIC COLUMNS ---
cols_to_exclude = [
    #"_id",
    "formhub/uuid", "start", "end",
    "Indicate the type of institution.", "Indicate the name of the institution",
    "Who are the training participants (select all that apply)?", 
    "How many promotion sessions have been held with this group?",
    "How many participants were 18 years and below?", 
    "How many participants fell into the age group of between 19- 35 years?", 
    "How many participants fell into the age group of between 36-55 years?", 
    "How many participants were above the age of 55 years?", 
    "How many participants had a disability?",
    "Indicate the type of disability that the participat(s) had.",
    "Why was this session conducted in this community, and what specific need prompted this training?",
    "Summarize the three key messages taught during this training session.",
    "Was the gospel of Jesus Christ shared verbally with participants during this sanitation and hygiene promotion session?",
    "Please indicate the action points that has been agreed between the participants and program staff.",
    "Please provide a picture of the sanitation and hygiene promotion activity and participants."	
    "Upload a file","Record your current location",	"_version_","meta/instanceID","_xform_id_string","_uuid",	
    "meta/rootUuid","_attachments",	"_status",	"_geolocation",	"_submission_time",	"_tags", "_notes","_submitted_by",
    "Select the name of the school","Please describe the other sanitation and hygiene lesson that was taught.",	
    "Other","Provide a detailed description of the triggering event",
    "Please provide a picture of the sanitation and hygiene promotion activity and participants.",	"Upload a file",
    "Number of household heads present",	"Number of men present",	"Number of women present",	"Number of children or youth present",	"What methods are you using to trigger the community? (Select all that apply)",	"How would you describe the community's response to triggering?",
    "Was a community action plan developed during triggering?",
    "Number of natural leaders identified during triggering","Upload CLTS Form A",
    "Upload triggering attendance list","GPS location","Training Location (Venue of training)",
    "Indicate the type of institution","Indicate the date of the training.","What type of TOT training session was this?",
    "Provide a detailed description of this TOT training session.","Why was this session conducted to this group of people, and what specific need prompted this training?",
    "What materials or methods were used to deliver the training?",
"Who will the training participants train (select all that apply)?",
"How many male participants attended this training session?",
"How many female participants attended this training session?",
"How many participants were between the age group of between 19- 35 years?",
"Estimate how many other people will receive hygiene promotion as a result of training this group.",
"What lessons were taught at this training session (select all that apply)?",
"Please describe which other lesson was taught at this training session.",
"Was the gospel of Jesus Christ shared verbally with participants during this training session?",
"How long was this training session? (in hours)",
"Please list the action point that were agreed between the participants and program staff.",
"Is this the last training in this community?",
"Please upload the signed community plan",
"Please provide a picture of the training activity and participants.",
"Upload a the scanned attendance list of participants",
"Other (Specify)",
"meta/deprecatedID",
"How many follow-up visits have been conducted in this village?",
"Which follow-up visit number is this?",
"How many households have built new sanitation facilities since the triggering event?",
"Type of sanitation facilities constructed (Select all that apply)",
"How many households are currently in the process of building a sanitation facility?",
"How many people are benefiting from the newly constructed sanitation facilities?",
"How many new handwashing facilities have been installed since the triggering event?",
"For all existing sanitation facilities, how many have functional handwashing facilities? (water and soap or ash present)",
"During this follow-up visit, was any open defecation observed?",
"GPS location",
"Do all households in the village have access to a functional sanitation facility?",
"Have all known open defecation sites been cleared and closed?",
"Do all sanitation facilities have a drop-hole cover or fly-proof mechanism?",
"Do sanitation facilities provide basic privacy?",
"GPS location",
#"Was the village verified for ODF certification by an independent verification team?",
"Upload the duly signed ODF verification form",
"GPS location",
"Others (specify)",
"What type of S&H training is this?",
"__version__",
"Which lessons were taught during this session (select all that apply)?",
"Is this the last S&H training for this community?"
]
df.drop(columns=[c for c in cols_to_exclude if c in df.columns], inplace=True)

# Final hierarchy cleaning
df = df.map(fix_hierarchy_repeats)

# Add Source Column
df.insert(0, "Source_Form", "SH-Household")

# =====================================================
# 7. SAVE TO EXCEL
# =====================================================
output_file = "aform3_SH_Household_etl.xlsx"
df.to_excel(output_file, index=False)

print(f"\n✅ SUCCESS: GPS split, Sequential Image URLs created, Phase mapping applied.")
print(f"File saved: {output_file}")
