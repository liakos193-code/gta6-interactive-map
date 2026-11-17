import sqlite3
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)
DB_NAME = "gta6_tracker.db"
FREE_LIMIT = 3  # Όριο δωρεάν pins πριν ζητήσει αναβάθμιση σε Pro

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        # Πίνακας τοποθεσιών (Pins)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                x REAL NOT NULL,
                y REAL NOT NULL
            )
        ''')
        # Πίνακας προόδου χρήστη
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_progress (
                location_id INTEGER PRIMARY KEY
            )
        ''')
        # Αρχικά δεδομένα δοκιμής αν η βάση είναι άδεια
        cursor.execute("SELECT COUNT(*) FROM locations")
        if cursor.fetchone()[0] == 0:
            sample_pins = [
                ("Hidden Package #1", "collectible", "Πίσω από το Ocean View Hotel", 400, 300),
                ("Golden Desert Eagle", "weapon", "Στην ταράτσα του εμπορικού", 650, 520),
                ("Infernus Classic", "vehicle", "Παρκαρισμένο στο λιμάνι", 250, 700),
                ("Easter Egg: Vice City Relic", "easter_egg", "Μέσα στο εγκαταλελειμμένο κλαμπ", 800, 200),
                ("Secret Stash #2", "collectible", "Κάτω από τη γέφυρα", 500, 600)
            ]
            cursor.executemany(
                "INSERT INTO locations (title, category, description, x, y) VALUES (?, ?, ?, ?, ?)",
                sample_pins
            )
        conn.commit()

@app.route("/")
def index():
    return render_template("index.html", free_limit=FREE_LIMIT)

@app.route("/api/locations", methods=["GET"])
def get_locations():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM locations")
        locations = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("SELECT location_id FROM user_progress")
        found_ids = {row["location_id"] for row in cursor.fetchall()}
        
        for loc in locations:
            loc["found"] = loc["id"] in found_ids
            
    return jsonify(locations)

@app.route("/api/toggle/<int:loc_id>", methods=["POST"])
def toggle_found(loc_id):
    is_pro = request.json.get("is_pro", False)
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM user_progress WHERE location_id = ?", (loc_id,))
        exists = cursor.fetchone()
        
        if exists:
            cursor.execute("DELETE FROM user_progress WHERE location_id = ?", (loc_id,))
            status = False
        else:
            cursor.execute("SELECT COUNT(*) FROM user_progress")
            count = cursor.fetchone()[0]
            if not is_pro and count >= FREE_LIMIT:
                return jsonify({"error": "PAYWALL_REACHED", "message": "Αναβαθμίστε σε Pro για απεριόριστο tracking!"}), 403
            cursor.execute("INSERT INTO user_progress (location_id) VALUES (?)", (loc_id,))
            status = True
        conn.commit()
    return jsonify({"id": loc_id, "found": status})

# Crowdsourcing Endpoint: Επιτρέπει στους χρήστες να προσθέτουν νέα pins
@app.route("/api/locations", methods=["POST"])
def add_location():
    data = request.json
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO locations (title, category, description, x, y) VALUES (?, ?, ?, ?, ?)",
            (data["title"], data["category"], data["description"], data["x"], data["y"])
        )
        conn.commit()
    return jsonify({"status": "success"}), 201

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)