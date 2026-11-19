import os
import hmac
import json
import sqlite3
import threading
import time

import stripe
from flask import Flask, render_template, request, jsonify

import official_watcher  # αυτόματο ψάξιμο για τον επίσημο χάρτη (στη ρίζα του repo)

# ==========================================
# 1. ΡΥΘΜΙΣΕΙΣ
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = "/var/data" if os.path.isdir("/var/data") else BASE_DIR
DB_NAME = os.path.join(DATA_DIR, "gta6_tracker.db")   # ίδια διαδρομή με τον watcher
FREE_LIMIT = 20

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")   # κενό = το admin είναι απενεργοποιημένο

app = Flask(__name__)


# ==========================================
# 2. ΒΑΣΗ ΔΕΔΟΜΕΝΩΝ (με αυτόματη αναβάθμιση παλιάς βάσης)
# ==========================================
def _columns(conn, table):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                tier TEXT,
                description TEXT,
                image_url TEXT,
                x REAL NOT NULL,
                y REAL NOT NULL,
                found BOOLEAN DEFAULT 0,
                status TEXT DEFAULT 'live'
            )
        """)
        # Η παλιά βάση του repo δεν έχει αυτές τις στήλες -> τις προσθέτουμε
        cols = _columns(conn, "locations")
        if "image_url" not in cols:
            conn.execute("ALTER TABLE locations ADD COLUMN image_url TEXT")
        if "tier" not in cols:
            conn.execute("ALTER TABLE locations ADD COLUMN tier TEXT")
        if "found" not in cols:
            conn.execute("ALTER TABLE locations ADD COLUMN found BOOLEAN DEFAULT 0")
        if "status" not in cols:
            conn.execute("ALTER TABLE locations ADD COLUMN status TEXT DEFAULT 'live'")
        conn.execute("UPDATE locations SET status = 'live' WHERE status IS NULL")

        # Η παλιά user_progress δεν έχει user_key -> ξαναφτιάχνεται
        if "user_key" not in _columns(conn, "user_progress") and _columns(conn, "user_progress"):
            conn.execute("DROP TABLE user_progress")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_progress (
                user_key TEXT NOT NULL,
                location_id INTEGER NOT NULL,
                PRIMARY KEY (user_key, location_id)
            )
        """)
        conn.execute("CREATE TABLE IF NOT EXISTS pro_users (email TEXT PRIMARY KEY, order_id TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('map_url', '/static/map.jpg')")

        # Αν δεν υπάρχει κανένα pin, φορτώνουμε τα αρχικά από το locations.json
        if conn.execute("SELECT COUNT(*) FROM locations").fetchone()[0] == 0:
            path = os.path.join(BASE_DIR, "locations.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    for loc in json.load(f):
                        conn.execute(
                            "INSERT INTO locations (title, category, description, x, y) VALUES (?, ?, ?, ?, ?)",
                            (loc["title"], loc["category"], loc.get("description", ""), loc["x"], loc["y"]),
                        )
        conn.commit()


init_db()


# ==========================================
# 3. ΤΟ ΨΑΧΤΗΡΙ (WATCHER) ΣΤΟ ΠΑΡΑΣΚΗΝΙΟ
# ==========================================
def watcher_worker():
    while True:
        try:
            print("Ο Watcher ψάχνει για νέα του GTA 6...")
            official_watcher.run_official_watcher()
            time.sleep(300)
        except Exception as e:
            print(f"Σφάλμα στον watcher: {e}")
            time.sleep(60)


threading.Thread(target=watcher_worker, daemon=True).start()


# ==========================================
# 4. ΒΟΗΘΗΤΙΚΑ
# ==========================================
def check_admin(req):
    sent = req.headers.get("X-Admin-Password", "")
    return bool(ADMIN_PASSWORD) and hmac.compare_digest(sent, ADMIN_PASSWORD)


def is_pro_user(conn, user_key):
    """Το PRO ελέγχεται πάντα στον server, ποτέ από ό,τι στέλνει ο browser."""
    row = conn.execute("SELECT 1 FROM pro_users WHERE email = ?", (str(user_key).lower().strip(),)).fetchone()
    return bool(row)


# ==========================================
# 5. ROUTES
# ==========================================
@app.route("/")
def index():
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'map_url'").fetchone()
    return render_template("index.html", free_limit=FREE_LIMIT, map_url=row[0] if row else "/static/map.jpg")


@app.route("/api/locations", methods=["GET"])
def get_locations():
    user_key = request.args.get("user_key", "guest")
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT id, title, category, tier, description, image_url, x, y
            FROM locations WHERE status = 'live' OR status IS NULL
        """).fetchall()
        found_ids = {r["location_id"] for r in conn.execute(
            "SELECT location_id FROM user_progress WHERE user_key = ?", (user_key,))}
    out = []
    for r in rows:
        d = dict(r)
        d["found"] = d["id"] in found_ids
        out.append(d)
    return jsonify(out)


@app.route("/api/locations", methods=["POST"])
def add_location():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    try:
        title, category, x, y = data["title"], data["category"], float(data["x"]), float(data["y"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Bad request"}), 400
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute(
            "INSERT INTO locations (title, category, description, image_url, x, y, status) VALUES (?, ?, ?, ?, ?, ?, 'live')",
            (title, category, data.get("description", ""), data.get("image_url", ""), x, y),
        )
        conn.commit()
    return jsonify({"status": "added"}), 201


@app.route("/api/move/<int:loc_id>", methods=["POST"])
def move_location(loc_id):
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    try:
        x, y = float(data["x"]), float(data["y"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Bad request"}), 400
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE locations SET x = ?, y = ? WHERE id = ?", (x, y, loc_id))
        conn.commit()
    return jsonify({"status": "moved"})


@app.route("/api/delete/<int:loc_id>", methods=["DELETE"])
def delete_location(loc_id):
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("DELETE FROM locations WHERE id = ?", (loc_id,))
        conn.execute("DELETE FROM user_progress WHERE location_id = ?", (loc_id,))
        conn.commit()
    return jsonify({"status": "deleted"})


@app.route("/api/toggle/<int:loc_id>", methods=["POST"])
def toggle_progress(loc_id):
    data = request.get_json(silent=True) or {}
    user_key = data.get("user_key", "guest")
    with sqlite3.connect(DB_NAME) as conn:
        exists = conn.execute(
            "SELECT 1 FROM user_progress WHERE user_key = ? AND location_id = ?", (user_key, loc_id)).fetchone()
        if exists:
            conn.execute("DELETE FROM user_progress WHERE user_key = ? AND location_id = ?", (user_key, loc_id))
            conn.commit()
            return jsonify({"status": "removed"})

        count = conn.execute("SELECT COUNT(*) FROM user_progress WHERE user_key = ?", (user_key,)).fetchone()[0]
        if count >= FREE_LIMIT and not is_pro_user(conn, user_key):
            return jsonify({
                "status": "limit_reached",
                "message": f"Free limit reached ({FREE_LIMIT} items). Upgrade to PRO for unlimited 100% tracking!",
            }), 403
        conn.execute("INSERT INTO user_progress (user_key, location_id) VALUES (?, ?)", (user_key, loc_id))
        conn.commit()
        return jsonify({"status": "added"})


@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    if not stripe.api_key:
        print("ΣΦΑΛΜΑ: Το STRIPE_SECRET_KEY δεν βρέθηκε στα Environment Variables!")
        return jsonify({"error": "Stripe API key is missing"}), 500
    try:
        session = stripe.checkout.Session.create(
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": "GTA 6 Map Tracker - PRO Pass"},
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
        print(f"Stripe Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return jsonify({"error": "Invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        email = ((session.get("customer_details") or {}).get("email") or "").lower().strip()
        if email:
            with sqlite3.connect(DB_NAME) as conn:
                conn.execute("INSERT OR REPLACE INTO pro_users (email, order_id) VALUES (?, ?)",
                             (email, session.get("id", "")))
                conn.commit()
    return jsonify({"status": "ok"}), 200


@app.route("/api/verify-pro", methods=["POST"])
def verify_pro():
    email = ((request.get_json(silent=True) or {}).get("email") or "").lower().strip()
    with sqlite3.connect(DB_NAME) as conn:
        return jsonify({"is_pro": bool(email) and is_pro_user(conn, email)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
