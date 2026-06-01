import os
import requests
import pandas as pd
from dotenv import load_dotenv

# =====================================================
# 1. LOAD ENVIRONMENT & SETTINGS
# =====================================================
load_dotenv()
API_TOKEN = os.getenv("KOBO_API_TOKEN")
BASE_URL = "https://eu.kobotoolbox.org/api/v2"
FORM_UID = "a4LCRjghfiBJmxW7F2nuXD"

headers = {"Authorization": f"Token {API_TOKEN}", "User-Agent": "Mozilla/5.0"}

# =====================================================
# 2. FETCH FORM SCHEMA (For Labels & Choices)
# =====================================================
print("Fetching human-readable labels and choices...")
schema_url = f"{BASE_URL}/assets/{FORM_UID}/"
schema_response = requests.get(schema_url, headers=headers).json()
content = schema_response.get("content", {})
survey_content = content.get("survey", [])
choices_content = content.get("choices", [])

label_map = {}
for item in survey_content:
    name = item.get("name")
    label = item.get("label")
    if isinstance(label, (dict, list)):
        label = next(iter(label.values())) if isinstance(label, dict) else next((x for x in label if x), name)
    if name:
        label_map[name] = str(label if label else name)

choice_map = {}
for c in choices_content:
    c_name = str(c.get("name"))
    c_label = c.get("label")
    if isinstance(c_label, (dict, list)):
        c_label = next(iter(c_label.values())) if isinstance(c_label, dict) else next((x for x in c_label if x), c_name)
    choice_map[c_name] = str(c_label)

# =====================================================
# 3. DOWNLOAD DATA SUBMISSIONS
# =====================================================
print("Downloading data submissions...")
all_data = []
next_url = f"{BASE_URL}/assets/{FORM_UID}/data/"

while next_url:
    response = requests.get(next_url, headers=headers).json()
    all_data.extend(response.get("results", []))
    next_url = response.get("next")

df = pd.json_normalize(all_data, sep="/")

# =====================================================
# 4. GPS, IMAGE, & DATE CONSOLIDATION
# =====================================================
if '_geolocation' in df.columns:
    df['Latitude'] = df['_geolocation'].apply(lambda x: x[0] if isinstance(x, list) and len(x) >= 2 else None)
    df['Longitude'] = df['_geolocation'].apply(lambda x: x[1] if isinstance(x, list) and len(x) >= 2 else None)

if '_attachments' in df.columns:
    def get_urls(attachments):
        return [a.get('download_url') for a in attachments if a.get('download_url')]
    url_series = df['_attachments'].apply(get_urls)
    max_imgs = url_series.map(len).max() or 0
    for i in range(max_imgs):
        df[f'image_URL_{i+1}'] = url_series.apply(lambda x: x[i] if len(x) > i else None)

# =====================================================
# 4. GPS, IMAGE, & DATE CONSOLIDATION
# =====================================================

# ... (keep your existing Latitude/Longitude and image_URL code here) ...

# 1. First consolidation from original technical names
date_cols = [
    'c8b2_Indicate_the_date_of_the_training',
    'mac4_Date_the_activity_was_conducted',
    'wojo3_Indicate_the_date_of_he_activity_was_held'
]
df['activity_project_started'] = df[df.columns.intersection(date_cols)].bfill(axis=1).iloc[:, 0]

# 2. Convert potential empty strings/whitespace to NaN so fillna works
df.replace(r'^\s*$', pd.NA, regex=True, inplace=True)

# 3. FILL EMPTY ENTRIES from the mobilization date column
mob_col = "Date the mobilization activity was held"
if mob_col in df.columns:
    # We fill 'activity_project_started' with values from 'mob_col'
    df['activity_project_started'] = df['activity_project_started'].fillna(df[mob_col])

# 4. Sync completed date to the now-filled started date
df['activity_project_completed'] = df['activity_project_started']

# =====================================================
# 5. RENAME & MAP CHOICES
# =====================================================
df = df.map(lambda x: choice_map.get(str(x), x) if not isinstance(x, (list, dict)) else x)

final_columns = []
for col in df.columns:
    last_part = col.split("/")[-1]
    # Keep _id for rearrangement
    if col in ['Latitude', 'Longitude', 'activity_project_started', 'activity_project_completed', '_id'] or col.startswith('image_URL_'):
        final_columns.append(col)
    else:
        final_columns.append(label_map.get(last_part, col))
df.columns = final_columns

df = df.copy()

rename_dict = {
    "Indicate your name": "Enumerator",
    "Indicate ward": "Ward",
    "Indicate location": "Location",
    "Indicate sub-location": "Sub-Location",
    "Indicate village": "Village",
    "Select the activity": "project_name",
    "Please provide a detailed description of this church mobilization activity.": "Description"
}
df.rename(columns=rename_dict, inplace=True)

# --- CALCULATE PHASE (Case-Insensitive Fix) ---
phase_mapping = {
    "gospel proclamation outreaches and literature distribution": "Phase 1",
    "community engagement": "Phase 2",
    "church mobilization activities": "Phase 3",
    "community animator training": "Phase 4",
    "establishment of water user committee and mou signing": "Phase 5",
    "action plan follow up (impact stories)": "Phase 6",
    "global wash and environmental days": "Phase 7"
}

if "project_name" in df.columns:
    # Convert project_name to lowercase and strip spaces for the mapping search
    df['Phase'] = df['project_name'].apply(
        lambda x: phase_mapping.get(str(x).strip().lower(), "")
    )
    
    p_idx = df.columns.get_loc("project_name")
    col_phase = df.pop("Phase")
    df.insert(p_idx + 1, "Phase", col_phase)
    df.insert(p_idx + 2, "phase_description", df["project_name"])



# --- REORDER: MOVE PROJECT NAME, GPS & DATES AFTER Phase Description ---
if "phase_description" in df.columns:
    idx = df.columns.get_loc("phase_description")
    
    # Just add "project_name" at the start of this list
    cols_to_move = [
        "project_name", 
        "Latitude", 
        "Longitude", 
        "activity_project_started", 
        "activity_project_completed"
    ]
    
    # Insert them one by one, shifting the index each time
    current_idx = idx + 1
    for col in cols_to_move:
        if col in df.columns:
            val = df.pop(col)
            df.insert(current_idx, col, val)
            current_idx += 1


# Clean values helper
def clean_val(val):
    if not isinstance(val, str) or not val.strip(): return val
    if "." in val and any(c.isdigit() for c in val): return val
    return val.split("_")[-1].replace("_", " ").title()

df = df.map(clean_val)

# Final formatting & Exclusions
df.insert(0, "Source_Form", "CCM-Survey")

# --- MOVE _id IMMEDIATELY AFTER Source_Form ---
if "_id" in df.columns:
    col_id = df.pop("_id")
    df.insert(1, "_id", col_id)

# =====================================================
# FORCE FILL PROJECT DATES
# =====================================================
source_col = "Date the mobilization activity was held"
target_cols = ["activity_project_started", "activity_project_completed"]

if source_col in df.columns:
    for col in target_cols:
        # 1. Convert to numeric/datetime where possible and force empty strings to NaN
        df[col] = pd.to_datetime(df[col], errors='coerce')
        temp_source = pd.to_datetime(df[source_col], errors='coerce')
        
        # 2. Fill missing targets with the source values
        df[col] = df[col].fillna(temp_source)
        
        # 3. Final format back to string (YYYY-MM-DD) for the report
        df[col] = df[col].dt.strftime('%Y-%m-%d').fillna("")

print("Dates consolidated from mobilization column.")

cols_to_exclude = [
    "_uuid", "_attachments", "_status", "_geolocation", "formhub/uuid",
    "Indicate the training location", "Select institution type",
    "Type the name of the institution", 
    "What type of church mobilization activity are you reporting?",
    "Why was this session conducted in this community, and what specific need prompted this training?",
    "List the topics that were covered during this activity.",
    "What materials or methods were used to deliver the content of this activity?",
    "Who are the training participants?",
    "How many participants were 18 years and below?",
    "How many participants fell into the age group of between 19- 35 years?",
    "How many participants fell into the age group of between 36-55 years?",
    "How many participants were above the age of 55 years?",
    "How many participants had a disability?",
    "Do you have any additional comments regarding this church mobilization activity?",
    "Please include a photo of the church mobilization activity.", 
    "Upload a file", 
    "Record your current location", 
    "__version__", "meta/instanceID", 
    "_xform_id_string", "meta/rootUuid", "_submission_time", 
    "_tags", "_notes", "_submitted_by", 
    "Indicate the type of disability that the participat(s) had.", 
    "Others (specify)", "meta/deprecatedID", "Others (specify)", "Others (specify)", 
    "Indicate the date of the training", 
    "What type of community mobilization activity are you reporting?", 
    "Mention the other activty that was done.", 
    "How many females participated in this meeting?", 
    "Indicate the number of people between 19-35 years", 
    "Indicate the number of people between 36-55 years", 
    "Indicate the number of people between 55+ years", 
    "Please describe the stakeholder interaction that took place (select all that apply).", 
    "Other",
    "Provide a detailed description of this community mobilization activity.",
"Who was included in the interaction that took place in the community (select all that apply)?",
"What reference materials/manual were used to prepare and deliver the lesson?",
"Please provide any additional details about community mobilization/sustainability.",
"Please include a photo of the community mobilization activity.",
"Upload the attendance List for the participants in the training",
"How many people have been selected/elected to the water user committee for this WASH project?",
"Is there an active community management body for planning, operating, and maintaining WASH services?",
"Please describe the primary way fees will be collected to fund maintenance of the WASH system.",
"Please describe anything else about the fee system, including the amounts that will be collected (in Ksh).",
"Please describe the training plan in place for building management capacity (select all that apply).",
"Who is providing the supply chain?",
"Describe how the community will get spare parts to maintain their WASH system:",
"Was an O&M Plan signed between Living Water and the community management body for how the WASH system will be maintained and repaired?",
"Upload the signed Operations and maintanance plan",
"Select the name of the comprehensive school",
"Date the activity was conducted",
"Provide a detailed description of this activity.",
"Why was this activity conducted in this community, and what specific need prompted this training?",
"What type of activity are you reporting?",
"How many churches were represented?",
"How many male participants attended this training session?",
"How many female participants attended this training session?",
"List any other local or national non-church organizations that were involved with this activity.",
"Was the gospel of Jesus Christ presented verbally during this activity?",
"Who made the verbal presentation of the gospel of Jesus Christ?",
"Were papers, books, or other written materials with the distributed during the activity",
"How many pieces of literature (papers, books, or other materials) were distributed during this activity",
"Please include a photo of the Gospel Proclamation activity.",
"Is this the last gospel outreach and litrature distribution in this community?",
"Select the name of the secondary school",
"Training date",
"Describe the purpose of the activity",
"Which thematic areas were covered? (select all that apply)",
"How many days was the training held?",
"How many churches were represented?",
"How many males?",
"How many females?",
"How many participants are below 18 years?",
"How many participants are 19–35 years?",
"How many participants are 35–55 years?",
"How many participants are 55+ years?",
"Indicate the reference materials used to deliver the training content.",
"Describe the criteria used in selection of the animators for this training",
"Indicate the action points were agreed with this group of facilitators?",
"Is this the last training with this community?",
"Photo of participants",
"GPS point of the training venue",
"Other (Specify)",
"Indicate the date of the activity was held",
"How many male participants attended this training session?",
"How many female participants attended this training session?",
"What type of community engagement meeting are you reporting on?",
"Provide a detailed description of this activity.",
"Was a schedule for village meetings developed during this activty?",
"What are the key challenges or needs identified by the community? List the top four prioritized challenges.",
"How long was this activity?",
"Describe the past interventions, their progress, and outcomes.",
"What locally available resources were identified to address the challenges/needs?",
"Which topics were covered during the training?",
"Did the training include practical demonstrations?",
"Were there any challenges or gaps indetified during the training?",
"List the challenges identified",
"Provide a photo of the of the activity in progress.",
"Is this the last the last community engagement session with this community?",
"Provide GPS .",
"What community amenities that were identified during the meeting?",
"Who are the key community leaders identified and engaged during the meeting?",
"Select the documents presented to the community during the handing over ceremony",
"Which global WASH day are you reporting?",
"Which date was this event held?",
"What types of activities were conducted during the event? (Select all that apply)",
"Which stakeholders collaborated/partnered with the program to organize this event? (Select all that apply",
"Describe the specific role of the stakehoders in this event.",
"How long did the event take? (In hours)",
"How many male participants attended this event?",
"JW23_How_many_male_partic_attended_this_event_001",
"How many female participants attended this event?",
"Which groups were represented among participants? (Select all that apply)",
"What were the key messages or themes promoted during the event?",
"What materials or methods were used to deliver the training?",
"What challenges, if any, were faced during the event?",
"What improvements or recommendations would you suggest for future WASH day events?",
"Please include a photo of the event",
"May we use your name in reports and publications?",
"Respondent name",
"May we take and use your photo for reporting?",
"May we record your story (audio) for reporting?",
"Gender",
"Age",
"Impact Story",
"Upload photo",
"Upload audio recording of the story",
"GPS Coordinates",
"How often will the maintenance fee be collected?",
"How many churches were involved?",
"How many of the participants were female?",
"How many males participated in this meeting?",
"Is this the last church mobilization training in this community?",
"Date the mobilization activity was held"

]
df.drop(columns=[c for c in cols_to_exclude if c in df.columns], inplace=True)

# =====================================================
# 6. SAVE TO EXCEL
# =====================================================
output_file = "aform4_ccm_etl.xlsx"
df.to_excel(output_file, index=False)
print(f"✅ Export Complete: Source_Form -> _id sequence set.")
