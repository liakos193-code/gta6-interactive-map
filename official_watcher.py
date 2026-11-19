import re
import json
import sqlite3
import urllib.request

DB_NAME = "gta6_tracker.db"

# Τα επίσημα endpoints των μεγάλων εταιρειών (παρακολουθούνται αυτόματα)
TARGET_TARGETS = [
    {
        "name": "MapGenie GTA 6",
        "url": "https://mapgenie.io/grand-theft-auto-6/maps/leonida",
        "type": "mapgenie"
    },
    {
        "name": "IGN GTA 6 Map",
        "url": "https://www.ign.com/maps/grand-theft-auto-6/leonida",
        "type": "ign"
    },
    {
        "name": "GTA Base Map",
        "url": "https://www.gtabase.com/grand-theft-auto-6/map",
        "type": "gtabase"
    }
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json"
}

def fetch_page(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="ignore")

def normalize_coords(items):
    """Υπολογίζει αυτόματα τα όρια (min/max) των επίσημων δεδομένων και τα φέρνει στο 0-1000"""
    xs = [float(i["x"]) for i in items if i.get("x") is not None]
    ys = [float(i["y"]) for i in items if i.get("y") is not None]
    if not xs or not ys:
        return []

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = (max_x - min_x) or 1.0
    span_y = (max_y - min_y) or 1.0

    # Αν τα δεδομένα είναι ήδη θετικά σε κλίμακα 0..Max (π.χ. 0..8192)
    if min_x >= 0 and min_y >= 0 and max_x > 100:
        scale_x = next((s for s in [1000.0, 2048.0, 4096.0, 8192.0, 16384.0] if max_x <= s), max_x)
        scale_y = next((s for s in [1000.0, 2048.0, 4096.0, 8192.0, 16384.0] if max_y <= s), max_y)
        for i in items:
            i["norm_x"] = round((float(i["x"]) / scale_x) * 1000, 2)
            i["norm_y"] = round((float(i["y"]) / scale_y) * 1000, 2)
    else:
        # Αν είναι γεωγραφικές συντεταγμένες (lat/lng) ή αρνητικές (-1000..+1000)
        for i in items:
            i["norm_x"] = round(((float(i["x"]) - min_x) / span_x) * 1000, 2)
            i["norm_y"] = round(((float(i["y"]) - min_y) / span_y) * 1000, 2)

    return items

def extract_mapgenie(html):
    """Εξάγει αυτόματα τον επίσημο χάρτη και τα pins από το ενσωματωμένο window.mapData του MapGenie"""
    map_url = None
    pins = []

    # 1. Εύρεση URL εικόνας χάρτη
    tile_match = re.search(r'"tile_sets"\s*:\s*\[\s*\{[^}]*"url"\s*:\s*"([^"]+)"', html)
    if tile_match:
        map_url = tile_match.group(1).replace("\\/", "/")

    # 2. Εύρεση ενσωματωμένου JSON locations
    loc_match = re.search(r'"locations"\s*:\s*(\[\s*\{.*?\}\s*\])\s*,\s*"', html, re.DOTALL)
    if loc_match:
        try:
            raw_locs = json.loads(loc_match.group(1))
            for loc in raw_locs:
                pins.append({
                    "title": loc.get("title", "").strip(),
                    "category": map_category(loc.get("category_id") or loc.get("category", "")),
                    "description": re.sub(r"<[^>]+>", "", loc.get("description") or "").strip(),
                    "image_url": (loc.get("media") or [{}])[0].get("url", "") if isinstance(loc.get("media"), list) and loc.get("media") else "",
                    "x": loc.get("longitude") or loc.get("lng") or loc.get("x"),
                    "y": loc.get("latitude") or loc.get("lat") or loc.get("y")
                })
        except Exception:
            pass

    return map_url, pins

def extract_nextjs_data(html):
    """Εξάγει αυτόματα δεδομένα από Next.js sites (IGN / GTA Base) μέσω __NEXT_DATA__"""
    pins = []
    next_match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if not next_match:
        return None, []

    try:
        data = json.loads(next_match.group(1))
        text_dump = json.dumps(data)
        # Αναζήτηση για objects που περιέχουν συντεταγμένες & τίτλο
        markers = re.findall(r'\{"id":[^}]+?"title":"([^"]+)"[^}]+?"(?:lat|latitude)":([-\d.]+)[^}]+?"(?:lng|longitude)":([-\d.]+)[^}]*?\}', text_dump)
        for title, lat, lng in markers:
            pins.append({
                "title": title,
                "category": "collectible",
                "description": "",
                "image_url": "",
                "x": float(lng),
                "y": float(lat)
            })
    except Exception:
        pass

    return None, pins

def map_category(raw_cat):
    c = str(raw_cat).lower()
    if any(k in c for k in ["weapon", "gun", "gear", "ammo"]):
        return "weapon"
    if any(k in c for k in ["car", "vehicle", "boat", "plane", "heli"]):
        return "vehicle"
    if any(k in c for k in ["easter", "secret", "ufo", "mystery"]):
        return "easter_egg"
    return "collectible"

def run_official_watcher():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()

        # Έλεγχος αν έχουμε ακόμα μόνο τα αρχικά 4 δοκιμαστικά pins
        cursor.execute("SELECT value FROM settings WHERE key = 'official_synced'")
        already_synced = cursor.fetchone()

        for target in TARGET_TARGETS:
            try:
                html = fetch_page(target["url"])
                if target["type"] == "mapgenie":
                    new_map_url, pins = extract_mapgenie(html)
                else:
                    new_map_url, pins = extract_nextjs_data(html)

                # Αν βρήκε πραγματικά pins (πάνω από 15 ώστε να μην είναι placeholder)
                if len(pins) >= 15:
                    pins = normalize_coords(pins)

                    # Την πρώτη φορά που σκάει επίσημο δεδομένο, καθαρίζει τα 4 δοκιμαστικά pins
                    if not already_synced:
                        cursor.execute("DELETE FROM locations")
                        cursor.execute("DELETE FROM user_progress")
                        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('official_synced', 'true')")
                        already_synced = True

                    if new_map_url:
                        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('map_url', ?)", (new_map_url,))

                    added = 0
                    for p in pins:
                        if not p["title"]:
                            continue
                        cursor.execute("SELECT 1 FROM locations WHERE LOWER(title) = LOWER(?)", (p["title"],))
                        if not cursor.fetchone():
                            cursor.execute(
                                "INSERT INTO locations (title, category, description, image_url, x, y) VALUES (?, ?, ?, ?, ?, ?)",
                                (p["title"], p["category"], p["description"], p["image_url"], p["norm_x"], p["norm_y"])
                            )
                            added += 1

                    conn.commit()
                    print(f"[{target['name']}] LIVE DETECTED! Auto-synced {added} official pins.")
                else:
                    print(f"[{target['name']}] Not live yet (waiting for launch)...")

            except Exception:
                # 404 πριν το launch - απολύτως φυσιολογικό
                print(f"[{target['name']}] Waiting for official release...")

if __name__ == "__main__":
    run_official_watcher()
