import os
import re
from dotenv import load_dotenv
from arcgis.gis import GIS

# -----------------------------------
# 1. LOAD ENV
# -----------------------------------
load_dotenv()

AGOL_USERNAME = os.getenv("AGOL_USERNAME")
AGOL_PASSWORD = os.getenv("AGOL_PASSWORD")

if not AGOL_USERNAME or not AGOL_PASSWORD:
    raise Exception("❌ Missing AGOL credentials in .env file")

# -----------------------------------
# 2. CONNECT
# -----------------------------------
gis = GIS("https://www.arcgis.com", AGOL_USERNAME, AGOL_PASSWORD)

# -----------------------------------
# 3. UTILITIES
# -----------------------------------
def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def extract_item_id(value: str) -> str:
    value = value.strip()

    if "id=" in value:
        return value.split("id=")[-1].split("&")[0]

    match = re.search(r"([a-f0-9]{32})", value)
    if match:
        return match.group(1)

    return value


# -----------------------------------
# 4. MAIN LOOP
# -----------------------------------
while True:
    clear_screen()

    print("======================================")
    print("      ARCGIS ADMIN CONSOLE (CLEAN)")
    print("======================================")
    print("1. Feature Layer")
    print("2. Web Map")
    print("3. CSV File")
    print("4. Dashboard")
    print("0. EXIT")
    print("======================================")

    choice = input("Select option: ").strip()

    if choice == "0":
        print("\n🚪 Exiting... Goodbye!")
        break

    type_map = {
        "1": "Feature Layer",
        "2": "Web Map",
        "3": "CSV",
        "4": "Dashboard"
    }

    expected_type = type_map.get(choice)

    if not expected_type:
        input("\n❌ Invalid choice. Press Enter to continue...")
        continue

    clear_screen()

    print("======================================")
    print(f"        DELETE {expected_type.upper()}")
    print("======================================")

    item_input = input("Enter Item ID or URL (or type EXIT): ")

    if item_input.upper() == "EXIT":
        continue

    item_id = extract_item_id(item_input)

    print(f"\n🔎 Parsed Item ID: {item_id}")

    item = gis.content.get(item_id)

    if item is None:
        input("\n❌ Item not found. Press Enter...")
        continue

    print("\n--------------------------------------")
    print(f"✔ Title : {item.title}")
    print(f"📦 Type  : {item.type}")
    print(f"👤 Owner : {item.owner}")
    print("--------------------------------------")

    if item.type != expected_type:
        print(f"\n⚠️ Type mismatch (expected {expected_type})")

    print("\n🔍 Checking dependencies...")

    related = []
    rel_types = [
        "Service2Data",
        "Data2Service",
        "Map2Service",
        "Map2FeatureCollection",
        "Service2Map"
    ]

    for r in rel_types:
        try:
            related.extend(item.related_items(rel_type=r, direction="forward"))
            related.extend(item.related_items(rel_type=r, direction="reverse"))
        except:
            pass

    related = list({x.id: x for x in related}.values())

    if related:
        print("\n⚠️ Dependencies:")
        for r in related:
            print(f" - {r.title} ({r.type})")
    else:
        print("\n✔ No dependencies found")

    print("\n======================================")
    print("WARNING: This action is PERMANENT")
    print("======================================")

    confirm = input("Type DELETE to confirm or EXIT to cancel: ").strip().upper()

    if confirm == "EXIT":
        continue

    if confirm != "DELETE":
        input("\n❌ Cancelled. Press Enter...")
        continue

    try:
        item.delete()
        print("\n🗑️ Successfully deleted item.")
    except Exception as e:
        print(f"\n❌ Delete failed: {e}")

    input("\n🔄 Press Enter to return to menu...")