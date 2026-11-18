import os
import re
import json
import time
import hashlib
import sqlite3
import threading
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
import stripe
from flask import Flask, render_template, request, jsonify, send_from_directory

app = Flask(__name__)

# Persistent Disk στο Render (/var/data)
DATA_DIR = "/var/data" if os.path.isdir("/var/data") else "."
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

DB_NAME = os.path.join(DATA_DIR, "gta6_tracker.db")
FREE_LIMIT = 20

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change_this_secret_password")

# 1. ΑΥΣΤΗΡΕΣ λέξεις-κλειδιά: Πρέπει να αναφέρεται ρητά το GTA 6
STRICT_GTA6_KEYWORDS = [
    "gta 6",
    "gta vi",
    "grand theft auto vi",
    "grand theft auto 6"
]

# 2. ΑΠΟΚΛΕΙΣΜΟΣ: Κόβει παλιά GTA, RDR2 ή άσχετες ειδήσεις/εγκλήματα
BLACKLIST_KEYWORDS = [
    "gta 5", "gta v", "grand theft auto v", "gta online",
    "vice city stories", "definitive edition", "san andreas", "gta iv", "gta 4",
    "red dead", "rdr2", "max payne", "bully",
    "arrested", "police report", "florida man", "real life", "court", "lawsuit"
]

MAJOR_FREE_REGIONS = {
    "vice city", "leonida", "leonida keys", "grassrivers",
    "port gellhorn", "ambrosia", "mount kalaga"
}

ROCKSTAR_PAGES = [
    "https://www.rockstargames.com/VI",
    "https://www.rockstargames.com/newswire"
]

# Όλες οι πηγές σου οργανωμένες ανά κατηγορία & RSS/Feed URL
INTEL_RSS_SOURCES = [
    # Leaks & Embargo
    ("Insider Gaming", "Leaks & Embargo", "https://insider-gaming.com/feed/"),
    ("MP1st", "Leaks & Embargo", "https://mp1st.com/feed"),
    ("RockstarINTEL", "Leaks & Embargo", "https://rockstarintel.com/feed/"),
    # Previews & Reviewers
    ("GameSpot", "Reviewers", "https://www.gamespot.com/feeds/mashup/"),
    ("Eurogamer", "Reviewers", "https://www.eurogamer.net/feed"),
    ("The Guardian", "Reviewers", "https://www.theguardian.com/games/rss"),
    ("GamesRadar+", "Reviewers", "https://www.gamesradar.com/rss/"),
    ("Push Square", "Reviewers", "https://www.pushsquare.com/feeds/latest"),
    ("Pure Xbox", "Reviewers", "https://www.purexbox.com/feeds/latest"),
    ("VGC", "Reviewers", "https://www.videogameschronicle.com/feed/"),
    # Corporate
    ("Take-Two Investor Relations", "Corporate", "https://ir.take2games.com/rss/news-releases.xml"),
]

# Αρχικές επιβεβαιωμένες εγγραφές (ώστε το PRO News Feed να δείχνει γεμάτο από το 1ο δευτερόλεπτο)
INITIAL_INTEL_FEED = [
    ("NateTheHate & Insider Gaming", "Leaks & Embargo", "2026-11-18", "Review codes distributed to press; review embargo lifts Nov 18 (3:00 AM PT / 12:00 PM CET) ahead of Nov 19 launch.", "https://insider-gaming.com"),
    ("BlackBate (ResetEra)", "Leaks & Embargo", "2026-11-18", "Metacritic & OpenCritic critic scores go live ~12:01–1:01 PM CET; select YouTubers & outlets lift at midnight ET Nov 19.", "https://www.resetera.com"),
    ("Jason Schreier (Bloomberg)", "Leaks & Embargo", "2026-11-18", "Live GTA VI Q&A hosted Nov 18 (11:00 AM ET) covering Rockstar North development insights & launch readiness.", "https://www.bloomberg.com"),
    ("New York Times / Kinda Funny / Dazed / Famitsu / TROISCOULEURS", "Confirmed Previews", "2026-11-18", "Confirmed hands-on preview outlets covering Leonida world scale, Lucia & Jason dual-protagonist mechanics, and console performance.", "https://www.rockstargames.com/VI"),
    ("GameSpot / Eurogamer / VGC / Push Square / Pure Xbox", "Reviewers", "2026-11-18", "Full PS5 & Xbox Series X|S launch reviews incoming upon embargo lift; digital preload (~212 GB) live worldwide.", "https://www.metacritic.com"),
    ("Metacritic & OpenCritic", "Score Aggregators", "2026-11-18", "Live critic score aggregation active for Grand Theft Auto VI (PS5 & Xbox Series X|S).", "https://opencritic.com"),
    ("TGG / Shirrako / El Rubius / Davy Jones / MikeShowSha / Spare Time Gamer", "YouTubers", "2026-11-18", "Full walkthroughs, Easter Egg hunts, secret weapons & 100% collectible video guides rolling out at midnight local unlock.", "https://www.youtube.com"),
    ("Take-Two Investor Relations & Rockstar Store", "Corporate", "2026-11-18", "PS5 & Xbox Series X|S launch confirmed Nov 19, 2026. Physical Collector/Map editions via Rockstar Store; PC & Online roadmap pending.", "https://ir.take2games.com"),
]

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                tier TEXT NOT NULL DEFAULT 'pro',
                description TEXT,
                image_url TEXT,
                source_url TEXT,
                x REAL NOT NULL,
                y REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'live'
            )
        """)
        for alter_sql in [
            "ALTER TABLE locations ADD COLUMN tier TEXT NOT NULL DEFAULT 'pro'",
            "ALTER TABLE locations ADD COLUMN source_url TEXT",
            "ALTER TABLE locations ADD COLUMN status TEXT NOT NULL DEFAULT 'live'"
        ]:
            try:
                cursor.execute(alter_sql)
            except sqlite3.OperationalError:
                pass

        # Νέος πίνακας για το PRO Live Intel & News Feed
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS intel_news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                group_tag TEXT NOT NULL,
                published_date TEXT NOT NULL,
                summary TEXT NOT NULL,
                url TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_custom_pins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_key TEXT NOT NULL,
                title TEXT NOT NULL,
                notes TEXT,
                x REAL NOT NULL,
                y REAL NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_progress (
                user_key TEXT NOT NULL,
                location_id INTEGER NOT NULL,
                PRIMARY KEY (user_key, location_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pro_users (
                email TEXT PRIMARY KEY,
                order_id TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('map_url', '/static/map.jpg')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('map_status', 'community')")

        # Γέμισμα αρχικών PRO ειδήσεων αν ο πίνακας είναι άδειος
        cursor.execute("SELECT COUNT(*) FROM intel_news")
        if cursor.fetchone()[0] == 0:
            for src, grp, dt, summ, link in INITIAL_INTEL_FEED:
                cursor.execute(
                    "INSERT INTO intel_news (source_name, group_tag, published_date, summary, url) VALUES (?, ?, ?, ?, ?)",
                    (src, grp, dt, summ, link)
                )
        conn.commit()

init_db()

def is_strictly_gta6(title, body=""):
    combined = f"{title} {body}".lower()
    has_gta6 = any(k in combined for k in STRICT_GTA6_KEYWORDS)
    has_blacklisted = any(b in combined for b in BLACKLIST_KEYWORDS)
    return has_gta6 and not has_blacklisted

def classify_intel(title, text="", source=""):
    combined = f"{title} {text}".lower()
    clean_lower = title.strip().lower()

    if clean_lower in MAJOR_FREE_REGIONS:
        return "free", "Landmark"
    if any(k in combined for k in ["easter egg", "myth", "secret", "ufo", "ghost", "mystery", "reference"]):
        return "pro", "Easter Egg"
    if any(k in combined for k in ["weapon", "gun", "rifle", "pistol", "melee", "knife", "launcher", "ammo"]):
        return "pro", "Secret Weapon"
    if any(k in combined for k in ["collectible", "letter", "scrap", "figurine", "card", "package", "hidden", "stash"]):
        return "pro", "Hidden Collectible"
    return "pro", "100% Completion"

def fetch_url(url, timeout=14):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; GTA6MapBot/5.0)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")

def cache_image_locally(img_url, prefix="asset"):
    if not img_url or not img_url.startswith("http"):
        return img_url
    try:
        ext = ".jpg"
        for e in [".png", ".webp", ".jpeg"]:
            if e in img_url.lower():
                ext = e
                break
        filename = f"{prefix}_{hashlib.md5(img_url.encode()).hexdigest()[:12]}{ext}"
        filepath = os.path.join(UPLOADS_DIR, filename)
        if not os.path.exists(filepath):
            req = urllib.request.Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
                if len(data) < 5000:
                    return ""
                with open(filepath, "wb") as f:
                    f.write(data)
        return f"/uploads/{filename}"
    except Exception:
        return img_url

def add_intel_news_item(source_name, group_tag, published_date, summary, url=""):
    clean_summary = re.sub(r"<[^>]+>", "", summary).strip()[:320]
    if not clean_summary:
        return False
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM intel_news WHERE LOWER(summary) = LOWER(?)", (clean_summary,))
        if cur.fetchone():
            return False
        cur.execute(
            "INSERT INTO intel_news (source_name, group_tag, published_date, summary, url) VALUES (?, ?, ?, ?, ?)",
            (source_name, group_tag, published_date, clean_summary, url)
        )
        conn.commit()
        return True

def stage_or_publish_pin(title, category, description, image_url="", source_url="", x=50.0, y=50.0, status="pending", tier="pro"):
    clean_title = title.strip()[:140]
    if not clean_title:
        return False
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM locations WHERE LOWER(title) = LOWER(?)", (clean_title,))
        if cursor.fetchone():
            return False
        local_img = cache_image_locally(image_url, prefix="pin") if image_url else ""
        cursor.execute(
            """INSERT INTO locations (title, category, tier, description, image_url, source_url, x, y, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (clean_title, category, tier, description[:500], local_img, source_url, x, y, status)
        )
        conn.commit()
        return True

def check_rockstar_official_pages():
    for page_url in ROCKSTAR_PAGES:
        try:
            html = fetch_url(page_url, timeout=15)
            og_match = re.findall(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, flags=re.IGNORECASE)
            img_matches = re.findall(r'https?://[^"\'\s<>]+\.(?:jpg|jpeg|png|webp)', html, flags=re.IGNORECASE)
            candidates = og_match + [u for u in img_matches if any(k in u.lower() for k in ["map", "leonida", "vice", "vi", "hero", "keyart"])]

            if not candidates:
                continue

            latest_img = candidates[0]
            with sqlite3.connect(DB_NAME) as conn:
                cur = conn.cursor()
                cur.execute("SELECT value FROM settings WHERE key = 'seen_rockstar_imgs'")
                row = cur.fetchone()
                seen = json.loads(row[0]) if row else []

                if latest_img not in seen:
                    seen.append(latest_img)
                    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('seen_rockstar_imgs', ?)", (json.dumps(seen[-40:]),))
                    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('pending_map_url', ?)", (latest_img,))
                    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('pending_map_source', ?)", (page_url,))
                    conn.commit()
                    add_intel_news_item(
                        "Rockstar Games Official",
                        "Corporate",
                        datetime.utcnow().strftime("%Y-%m-%d"),
                        f"New official visual asset detected on {page_url}",
                        page_url
                    )
        except Exception as e:
            print(f"[WATCHER] Rockstar check ({page_url}): {e}")

def scan_gta_wiki_api():
    wiki_endpoints = [
        "https://gta.fandom.com/api.php",
        "https://gta.wiki/api.php"
    ]
    for endpoint in wiki_endpoints:
        try:
            api_url = f"{endpoint}?action=query&list=search&srsearch=%22Grand%20Theft%20Auto%20VI%22&srlimit=25&format=json"
            data = json.loads(fetch_url(api_url))
            for item in data.get("query", {}).get("search", []):
                title = item.get("title", "").strip()
                snippet = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
                if not is_strictly_gta6(title, snippet):
                    continue
                tier, cat = classify_intel(title, snippet, source="GTA Wiki")
                base_wiki = endpoint.replace("/api.php", "/wiki/")
                page_link = base_wiki + urllib.parse.quote(title.replace(" ", "_"))
                stage_or_publish_pin(title, cat, snippet, "", page_link, 50.0, 50.0, status="pending", tier=tier)
        except Exception as e:
            print(f"[WATCHER] Wiki API error ({endpoint}): {e}")

def scan_sources():
    check_rockstar_official_pages()
    scan_gta_wiki_api()

    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    for source_name, group_tag, feed_url in INTEL_RSS_SOURCES:
        try:
            xml_data = fetch_url(feed_url)
            root = ET.fromstring(xml_data)
            entries = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")

            for entry in entries[:15]:
                title_el = entry.find("title") or entry.find("{http://www.w3.org/2005/Atom}title")
                title = (title_el.text or "").strip() if title_el is not None else ""

                link_el = entry.find("link")
                link = (link_el.text or link_el.get("href", "")).strip() if link_el is not None else ""

                date_el = entry.find("pubDate") or entry.find("{http://www.w3.org/2005/Atom}updated")
                pub_date = (date_el.text or today_str).strip()[:16] if date_el is not None else today_str

                content_el = entry.find("description") or entry.find("{http://www.w3.org/2005/Atom}content")
                body = (content_el.text or "") if content_el is not None else ""

                if not is_strictly_gta6(title, body):
                    continue

                # Αποθήκευση κατευθείαν στο PRO Intel & News Feed (Source Name | Date | Info)
                add_intel_news_item(source_name, group_tag, pub_date, title, link)
        except Exception as e:
            print(f"[WATCHER] Intel feed error ({source_name}): {e}")

def watcher_worker():
    time.sleep(8)
    while True:
        print("[WATCHER] Scanning GTA 6 official, leaks, reviewers & score feeds...")
        scan_sources()
        time.sleep(300)

if not os.environ.get("WATCHER_STARTED"):
    os.environ["WATCHER_STARTED"] = "1"
    threading.Thread(target=watcher_worker, daemon=True).start()

def check_admin(req):
    return req.headers.get("X-Admin-Password") == ADMIN_PASSWORD

@app.route("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(UPLOADS_DIR, filename)

@app.route("/")
def index():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'map_url'")
        row = cursor.fetchone()
        map_url = row[0] if row else "/static/map.jpg"
    return render_template("index.html", free_limit=FREE_LIMIT, map_url=map_url)

# --- PRO ONLY: LIVE INTEL & NEWS FEED ENDPOINT ---
@app.route("/api/intel-news", methods=["GET", "POST"])
def intel_news_api():
    if request.method == "POST":
        if not check_admin(request):
            return jsonify({"error": "Unauthorized"}), 401
        data = request.json
        add_intel_news_item(
            data.get("source_name", "Official"),
            data.get("group_tag", "Leaks & Embargo"),
            data.get("published_date", datetime.utcnow().strftime("%Y-%m-%d")),
            data.get("summary", ""),
            data.get("url", "")
        )
        return jsonify({"status": "added"}), 201

    is_pro = request.args.get("is_pro", "false").lower() == "true"
    if not is_pro and not check_admin(request):
        return jsonify([])

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM intel_news ORDER BY id DESC LIMIT 40")
        return jsonify([dict(r) for r in cur.fetchall()])

@app.route("/api/locations", methods=["GET"])
def get_locations():
    user_key = request.args.get("user_key", "guest")
    is_pro = request.args.get("is_pro", "false").lower() == "true"
    include_pending = check_admin(request)

    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        if include_pending:
            cursor.execute("SELECT * FROM locations")
        elif is_pro:
            cursor.execute("SELECT * FROM locations WHERE status = 'live'")
        else:
            cursor.execute("SELECT * FROM locations WHERE status = 'live' AND tier = 'free'")
        rows = [dict(r) for r in cursor.fetchall()]

        cursor.execute("SELECT location_id FROM user_progress WHERE user_key = ?", (user_key,))
        found_ids = {r["location_id"] for r in cursor.fetchall()}

    for loc in rows:
        loc["found"] = loc["id"] in found_ids

    return jsonify(rows)

@app.route("/api/locations", methods=["POST"])
def add_location():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    local_img = cache_image_locally(data.get("image_url", ""), prefix="pin")
    tier = data.get("tier", "pro")
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO locations (title, category, tier, description, image_url, source_url, x, y, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'live')""",
            (data["title"], data["category"], tier, data.get("description", ""), local_img, "", data["x"], data["y"])
        )
        conn.commit()
    return jsonify({"status": "added"}), 201

@app.route("/api/approve/<int:loc_id>", methods=["POST"])
def approve_and_place_location(loc_id):
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    tier = data.get("tier", "pro")
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE locations SET x = ?, y = ?, tier = ?, status = 'live' WHERE id = ?",
            (data["x"], data["y"], tier, loc_id)
        )
        conn.commit()
    return jsonify({"status": "approved_live"})

@app.route("/api/move/<int:loc_id>", methods=["POST"])
def move_location(loc_id):
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE locations SET x = ?, y = ? WHERE id = ?", (data["x"], data["y"], loc_id))
        conn.commit()
    return jsonify({"status": "moved"})

@app.route("/api/delete/<int:loc_id>", methods=["DELETE"])
def delete_location(loc_id):
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM locations WHERE id = ?", (loc_id,))
        cursor.execute("DELETE FROM user_progress WHERE location_id = ?", (loc_id,))
        conn.commit()
    return jsonify({"status": "deleted"})

@app.route("/api/update-map-url", methods=["POST"])
def manual_update_map():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    raw_url = data.get("map_url", "").strip()
    if not raw_url:
        return jsonify({"error": "Missing map_url"}), 400
    local_map = cache_image_locally(raw_url, prefix="official_map")
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('map_url', ?)", (local_map,))
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('map_status', 'official_locked')")
        conn.commit()
    return jsonify({"status": "map_updated", "map_url": local_map})

@app.route("/api/pending-map", methods=["GET", "POST"])
def handle_pending_map():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    with sqlite3.connect(DB_NAME) as conn:
        cur = conn.cursor()
        if request.method == "GET":
            cur.execute("SELECT value FROM settings WHERE key = 'pending_map_url'")
            url_row = cur.fetchone()
            cur.execute("SELECT value FROM settings WHERE key = 'pending_map_source'")
            src_row = cur.fetchone()
            return jsonify({
                "pending_map_url": url_row[0] if url_row else "",
                "source": src_row[0] if src_row else ""
            })

        action = request.json.get("action")
        if action == "approve":
            cur.execute("SELECT value FROM settings WHERE key = 'pending_map_url'")
            row = cur.fetchone()
            if row and row[0]:
                local_map = cache_image_locally(row[0], prefix="official_map")
                cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('map_url', ?)", (local_map,))
                cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('map_status', 'official_locked')")
        cur.execute("DELETE FROM settings WHERE key IN ('pending_map_url', 'pending_map_source')")
        conn.commit()
        return jsonify({"status": action})

@app.route("/api/bulk-import", methods=["POST"])
def bulk_import_pins():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    items = request.json.get("pins", [])
    imported = 0
    for item in items:
        if stage_or_publish_pin(
            title=item.get("title", ""),
            category=item.get("category", "Easter Egg"),
            description=item.get("description", ""),
            image_url=item.get("image_url", ""),
            source_url=item.get("source_url", ""),
            x=float(item.get("x", 50.0)),
            y=float(item.get("y", 50.0)),
            status="live",
            tier=item.get("tier", "pro")
        ):
            imported += 1
    return jsonify({"status": "imported", "count": imported})

@app.route("/api/custom-pins", methods=["GET", "POST", "DELETE"])
def custom_pins():
    if request.method == "GET":
        user_key = request.args.get("user_key", "")
        with sqlite3.connect(DB_NAME) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_custom_pins WHERE user_key = ?", (user_key,))
            return jsonify([dict(r) for r in cursor.fetchall()])

    if request.method == "DELETE":
        pin_id = request.args.get("id")
        user_key = request.args.get("user_key", "")
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM user_custom_pins WHERE id = ? AND user_key = ?", (pin_id, user_key))
            conn.commit()
        return jsonify({"status": "deleted"})

    data = request.json
    if not data.get("is_pro"):
        return jsonify({"error": "PRO feature only"}), 403
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO user_custom_pins (user_key, title, notes, x, y) VALUES (?, ?, ?, ?, ?)",
            (data["user_key"], data["title"], data.get("notes", ""), data["x"], data["y"])
        )
        conn.commit()
    return jsonify({"status": "custom_pin_saved"}), 201

@app.route("/api/toggle/<int:loc_id>", methods=["POST"])
def toggle_progress(loc_id):
    data = request.json
    user_key = data.get("user_key", "guest")
    is_pro = data.get("is_pro", False)

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT location_id FROM user_progress WHERE user_key = ? AND location_id = ?", (user_key, loc_id))
        if cursor.fetchone():
            cursor.execute("DELETE FROM user_progress WHERE user_key = ? AND location_id = ?", (user_key, loc_id))
            conn.commit()
            return jsonify({"status": "removed"})
        else:
            cursor.execute("SELECT COUNT(*) FROM user_progress WHERE user_key = ?", (user_key,))
            if not is_pro and cursor.fetchone()[0] >= FREE_LIMIT:
                return jsonify({
                    "status": "limit_reached",
                    "message": f"Free limit reached ({FREE_LIMIT} items). Upgrade to PRO for unlimited tracking!"
                }), 403
            cursor.execute("INSERT INTO user_progress (user_key, location_id) VALUES (?, ?)", (user_key, loc_id))
            conn.commit()
            return jsonify({"status": "added"})

@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    try:
        session = stripe.checkout.Session.create(
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": "GTA 6 Map Tracker - PRO Pass (All Easter Eggs, Live Intel & Custom Pins)",
                        "tax_code": "txcd_10000000",
                    },
                    "unit_amount": 999,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=request.host_url + "?success=true",
            cancel_url=request.host_url + "?canceled=true",
        )
        return jsonify({"url": session.url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return jsonify({"error": "Invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_email = session.get("customer_details", {}).get("email", "").lower().strip()
        order_id = session.get("id", "")
        if user_email:
            with sqlite3.connect(DB_NAME) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO pro_users (email, order_id) VALUES (?, ?)", (user_email, order_id))
                conn.commit()

    return jsonify({"status": "ok"}), 200

@app.route("/api/verify-pro", methods=["POST"])
def verify_pro():
    email = request.json.get("email", "").lower().strip()
    if not email:
        return jsonify({"is_pro": False})

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT email FROM pro_users WHERE email = ?", (email,))
        if cursor.fetchone():
            return jsonify({"is_pro": True})

    try:
        customers = stripe.Customer.list(email=email, limit=5)
        for cust in customers.auto_paging_iter():
            charges = stripe.Charge.list(customer=cust.id, limit=5)
            if any(c.paid and not c.refunded for c in charges.data):
                with sqlite3.connect(DB_NAME) as conn:
                    conn.execute("INSERT OR REPLACE INTO pro_users (email, order_id) VALUES (?, ?)", (email, "stripe_verified"))
                    conn.commit()
                return jsonify({"is_pro": True})
    except Exception:
        pass

    return jsonify({"is_pro": False})

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
