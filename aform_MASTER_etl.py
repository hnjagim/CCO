import subprocess
import sys
import pandas as pd
import os

# --- STEP 1: DEFINE YOUR FILES ---
etl_scripts = [
    "aform1_water_access_etl.py",
    "aform2_SH_Institution_etl.py",
    "aform3_SH_Household_etl.py",
    "aform4_ccm_etl.py"
]

# Map the script names to the Excel files they produce
excel_outputs = [
    "aform1_water_access_etl.xlsx",
    "aform2_SH_Institution_etl.xlsx",
    "aform3_SH_Household_etl.xlsx",
    "aform4_ccm_etl.xlsx"
]

def run_pipeline():
    # --- STEP 2: RUN INDIVIDUAL ETL SCRIPTS ---
    print(">>> Phase 1: Generating Individual Excel Files...")
    for script in etl_scripts:
        try:
            print(f"Running {script}...")
            subprocess.run([sys.executable, script], check=True)
        except subprocess.CalledProcessError:
            print(f"Critical Error in {script}. Stopping pipeline.")
            return

    # --- STEP 3: COMBINE INTO MASTER ---
    print("\n>>> Phase 2: Combining into Master Report...")
    all_dfs = []
    
    for file in excel_outputs:
        if os.path.exists(file):
            df = pd.read_excel(file)
            # Standardize column names to fix the "Image_URL" vs "image_URL" issue
            df.columns = df.columns.str.strip().str.lower()
            all_dfs.append(df)
        else:
            print(f"Warning: {file} was not generated.")

    if all_dfs:
        master_df = pd.concat(all_dfs, axis=0, ignore_index=True, sort=False)
        master_df.to_excel("Kobo_Consolidated_ETL_Production.xlsx", index=False)
        print(f"\nSUCCESS! Master report generated with {len(master_df)} total rows.")
    else:
        print("No data found to combine.")

if __name__ == "__main__":
    run_pipeline()
