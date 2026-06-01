import os
import subprocess
import sys
import pandas as pd
import re
from dotenv import load_dotenv
from arcgis.gis import GIS
from arcgis.features import FeatureLayerCollection

# --- LOAD SECRETS ---
load_dotenv()
AGOL_USER = os.getenv('AGOL_USERNAME')
AGOL_PASS = os.getenv('AGOL_PASSWORD')

# --- CONFIGURATION ---
FINAL_FILE = "Kobo_Consolidated_ETL_Production.xlsx"
LAYER_TITLE = "Kobo_Master_Production_Layer"

TASKS = [
    {"script": "aform1_water_access_etl.py", "name": "Water Access Form"},
    {"script": "aform2_SH_Institution_etl.py", "name": "SH Institution Form"},
    {"script": "aform3_SH_Household_etl.py", "name": "SH Household Form"},
    {"script": "aform4_ccm_etl.py", "name": "CCM Form"}
]

SOURCE_EXCELS = ["aform1_water_access_etl.xlsx", "form2_SH_Institution_etl.xlsx", "aform3_SH_Household_etl.xlsx", "aform4_ccm_etl.xlsx"]

def extract_phase_number(val):
    """Extracts numeric digits from the phase string for numeric entries."""
    if pd.isna(val):
        return None
    numbers = re.findall(r'\d+', str(val))
    # Returns the first number found as an integer
    return int(numbers[0]) if numbers else None

def validate_schema(new_df, fl_item):
    """Checks for missing fields but only warns instead of stopping."""
    print("🔍 Validating Schema (Warning Only Mode)...")
    flayer = fl_item.layers[0]
    agol_fields = {f.name.lower() for f in flayer.properties.fields if f.type not in ['esriFieldTypeOID', 'esriFieldTypeGlobalID']}
    new_fields = {c.lower() for c in new_df.columns}

    missing_in_new = agol_fields - new_fields
    if missing_in_new:
        print(f"⚠️ WARNING: The following AGOL fields are missing in your new data: {missing_in_new}")
        print("Proceeding with update anyway...")
    else:
        print("✅ Schema matches perfectly.")
    return True 

def run_pipeline():
    print("🚀 STARTING ROBUST PRODUCTION PIPELINE\n" + "="*40)

    # 1. REFRESH DATA
    for task in TASKS:
        print(f"  → Running: {task['script']}...")
        try:
            subprocess.run([sys.executable, task['script']], check=True)
            print(f"  ✅ {task['name']} generated.")
        except subprocess.CalledProcessError:
            print(f"\n❌ CRITICAL ERROR: {task['name']} failed. Pipeline stopped.")
            return

    # 2. CONSOLIDATE
    all_dfs = []
    for file in SOURCE_EXCELS:
        if os.path.exists(file):
            df = pd.read_excel(file)
            if not df.empty:
                df.columns = df.columns.str.strip().str.lower()
                all_dfs.append(df)
    
    if not all_dfs:
        print("❌ No data found in source excels. Exiting.")
        return

    master_df = pd.concat(all_dfs, axis=0, ignore_index=True, sort=False)

    # --- ADD PHASE SORT NUMBER COLUMN ---
    if 'phase' in master_df.columns:
        print("🔢 Adding 'Phase Sort Number' numeric column...")
        master_df['phase sort number'] = master_df['phase'].apply(extract_phase_number)
        
        cols = list(master_df.columns)
        if 'phase' in cols and 'phase sort number' in cols:
            cols.insert(cols.index('phase') + 1, cols.pop(cols.index('phase sort number')))
            master_df = master_df[cols]
    
    master_df.to_excel(FINAL_FILE, index=False)
    print(f"✅ Consolidated file created: {FINAL_FILE} ({len(master_df)} rows)")

        # 3. SYNC TO AGOL
    try:
        gis = GIS("https://arcgis.com", AGOL_USER, AGOL_PASS)
        
        # FIX 1: Exact matching using double quotes to completely ignore backup layers
        excel_search = gis.content.search(query=f'title:"{LAYER_TITLE}" AND type:"Microsoft Excel"')
        fs_search = gis.content.search(query=f'title:"{LAYER_TITLE}" AND type:"Feature Service"')
        
        # Filter explicitly to ensure we don't accidentally pull a backup item
        excel_item = next((item for item in excel_search if item.title == LAYER_TITLE), None)
        fl_item = next((item for item in fs_search if item.title == LAYER_TITLE), None)
        
        if excel_item and fl_item:
            
            # --- BACKUP STEP ---
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
            backup_title = f"{LAYER_TITLE}_Backup_{timestamp}"
            print(f"📦 Creating safety backup: '{backup_title}'...")
            
            try:
                cloned_items = gis.content.clone_items(
                    items=[fl_item], 
                    copy_data=True, 
                    search_existing_items=False
                )
                if cloned_items:
                    backup_item = cloned_items[0]
                    backup_item.update(item_properties={'title': backup_title})
                    print(f"✅ Backup created successfully (ID: {backup_item.id})")
            except Exception as backup_error:
                print(f"⚠️ Backup failed: {backup_error}. Stopping pipeline for safety.")
                return
            # --------------------

            if validate_schema(master_df, fl_item):
                print(f"🔄 Step 1: Updating the hosted Excel source file...")
                excel_item.update(data=FINAL_FILE)
                
                print(f"🔄 Step 2: Refreshing Feature Layer: '{fl_item.title}'...")
                flc = FeatureLayerCollection.fromitem(fl_item)
                
                # FIX 2: Universal API syntax compatibility via dictionary unpack 
                # This works perfectly on both older and newer versions of arcgis
                overwrite_params = {"data_item_id": excel_item.id}
                try:
                    response = flc.manager.overwrite(**overwrite_params)
                except TypeError:
                    # Fallback fallback for legacy package environments
                    response = flc.manager.overwrite(excel_item.id)
                
                if response.get('success') or response.get('status') == 'success':
                    print("🎉 AGOL Update Successful!")
                else:
                    print(f"⚠️ Update reported issues: {response}")
        else:
            print(f"🆕 '{LAYER_TITLE}' components missing. Publishing a fresh copy...")
            excel_props = {'title': LAYER_TITLE, 'type': 'Microsoft Excel'}
            excel_item = gis.content.add(excel_props, data=FINAL_FILE)
            published_service = excel_item.publish()
            print(f"🎉 Published: {published_service.title}")
            
    except Exception as e:
        print(f"❌ Process Error: {e}")

if __name__ == "__main__":
    run_pipeline()
