import sys
import subprocess
import time
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import requests
except ImportError:
    print("[!] Η βιβλιοθήκη 'requests' λείπει. Εγκατάσταση...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "--break-system-packages"])
    import requests

# =======================================================
# [ΒΑΛΕ ΤΟ ΚΛΕΙΔΙ ΣΟΥ ΕΔΩ]
GITHUB_TOKEN = ""
# =======================================================

if GITHUB_TOKEN == "ΒΑΛΕ_ΕΔΩ_ΤΟ_ΚΛΕΙΔΙ_ΣΟΥ" or GITHUB_TOKEN == "":
    sys.exit("\n[!] Ξέχασες να βάλεις το κλειδί στη γραμμή 17!")

HEADERS = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github.v3+json"}

# 1 ΑΠΟΛΥΤΗ ΛΕΞΗ-ΦΡΑΣΗ ΑΝΑ ΚΑΤΗΓΟΡΙΑ ΓΙΑ GTA 6 LOCATIONS & COORDINATES
CATEGORIES = {
    "1. GTA 6 General Locations & Pins": ['"gta6" "locations"', '"gta-6" "markers"'],
    "2. Leonida & Vice City Coordinates": ['"Leonida" "coordinates"', '"Vice City" "gta6" "lat"'],
    "3. Interactive Map Data (Leaflet/GeoJSON)": ['"gta6" "leaflet"', '"gta6" "geojson"'],
    "4. Collectibles & Easter Eggs": ['"gta6" "collectibles"', '"gta6" "easter_eggs"'],
    "5. Datamined Coordinates (X, Y, Z)": ['"gta6" "coords"', '"Project Americas" "coordinates"'],
    "6. Vehicles, Weapons & Safehouses": ['"gta6" "safehouses"', '"gta6" "weapons"']
}

def search_github_for_gta6_locations():
    print("=====================================================")
    print("[*] ΕΝΑΡΞΗ: GTA 6 LOCATIONS GITHUB CRAWLER (SNIPER MODE)")
    print("=====================================================\n")
    
    # Επεκτάσεις αρχείων όπου αποθηκεύονται συντεταγμένες χαρτών στο GitHub
    extensions = ["json", "geojson", "js"]
    
    for category_name, queries in CATEGORIES.items():
        print(f"\n[+] Σαρώνει κατηγορία: {category_name}")
        print("-" * 60)
        
        for query in queries:
            for ext in extensions:
                print(f"    [*] Ερώτημα: {query} (extension:{ext})")
                
                encoded_query = requests.utils.quote(query)
                search_url = f"https://api.github.com/search/code?q={encoded_query}+extension:{ext}"
                
                try:
                    response = requests.get(search_url, headers=HEADERS, timeout=15, verify=False)
                    
                    if response.status_code == 200:
                        results = response.json().get("items", [])
                        if not results:
                            print("        [-] Δεν βρέθηκαν αρχεία.")
                        
                        for item in results[:5]:
                            file_name = item['name']
                            repo_name = item['repository']['full_name']
                            file_url = item['html_url']
                            # Μετατροπή του link σε raw URL για άμεσο κατέβασμα δεδομένων
                            raw_url = file_url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
                            
                            print(f"        [!] ΒΡΕΘΗΚΕ: {file_name} (Repo: {repo_name})")
                            print(f"            Link: {file_url}")
                            print(f"            Raw Data: {raw_url}")
                            
                    elif response.status_code == 403:
                        print("        [x] Όριο (Rate Limit). Αναμονή 15 δευτερόλεπτα...")
                        time.sleep(15)
                    else:
                        print(f"        [x] Σφάλμα {response.status_code}: {response.json().get('message', 'Άγνωστο')}")
                        
                except Exception as e:
                    print(f"        [x] Απρόσμενο Σφάλμα: {e}")
                    
                # Το GitHub Code Search API επιτρέπει αυστηρά μέχρι 10 requests/λεπτό
                time.sleep(6)

if __name__ == "__main__":
    search_github_for_gta6_locations()