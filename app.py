import os
import sqlite3
import stripe
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
DB_NAME = "gta6_tracker.db"
FREE_LIMIT = 20

# Environment Variables (Ασφαλές για GitHub)
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "change_this_secret_password")

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                image_url TEXT,
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
        conn.commit()

def check_admin(req):
    return req.headers.get("X-Admin-Password") == ADMIN_PASSWORD

@app.route("/")
def index():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'map_url'")
        row = cursor.fetchone()
        map_url = row[0] if row else "/static/map.jpg"
    return render_template("index.html", free_limit=FREE_LIMIT, map_url=map_url)

@app.route("/api/locations", methods=["GET"])
def get_locations():
    user_key = request.args.get("user_key", "guest")
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM locations")
        locations = [dict(row) for row in cursor.fetchall()]

        cursor.execute("SELECT location_id FROM user_progress WHERE user_key = ?", (user_key,))
        found_ids = {row["location_id"] for row in cursor.fetchall()}

    for loc in locations:
        loc["found"] = loc["id"] in found_ids

    return jsonify(locations)

@app.route("/api/locations", methods=["POST"])
def add_location():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO locations (title, category, description, image_url, x, y) VALUES (?, ?, ?, ?, ?, ?)",
            (data["title"], data["category"], data.get("description", ""), data.get("image_url", ""), data["x"], data["y"])
        )
        conn.commit()
    return jsonify({"status": "added"}), 201

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

@app.route("/api/toggle/<int:loc_id>", methods=["POST"])
def toggle_progress(loc_id):
    data = request.json
    user_key = data.get("user_key", "guest")
    is_pro = data.get("is_pro", False)

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT location_id FROM user_progress WHERE user_key = ? AND location_id = ?", (user_key, loc_id))
        exists = cursor.fetchone()

        if exists:
            cursor.execute("DELETE FROM user_progress WHERE user_key = ? AND location_id = ?", (user_key, loc_id))
            conn.commit()
            return jsonify({"status": "removed"})
        else:
            cursor.execute("SELECT COUNT(*) FROM user_progress WHERE user_key = ?", (user_key,))
            count = cursor.fetchone()[0]
            if not is_pro and count >= FREE_LIMIT:
                return jsonify({
                    "status": "limit_reached",
                    "message": f"Free limit reached ({FREE_LIMIT} items). Upgrade to PRO for unlimited 100% tracking!"
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
                        "name": "GTA 6 Map Tracker - PRO Pass",
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
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT email FROM pro_users WHERE email = ?", (email,))
        row = cursor.fetchone()
    return jsonify({"is_pro": bool(row)})

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
