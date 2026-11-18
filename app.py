import os
import sqlite3
import threading
import time
from flask import Flask, render_template, request, jsonify
import stripe
import official_watcher  # Κάνει import το δικό σου αρχείο για το αυτόματο ψάξιμο

# ==========================================
# 1. ΡΥΘΜΙΣΕΙΣ (ΦΑΚΕΛΟΣ ΓΙΑ ΤΟ RENDER & STRIPE)
# ==========================================
DATA_DIR = "/var/data" if os.path.isdir("/var/data") else "."
DB_NAME = os.path.join(DATA_DIR, "gta6_tracker.db")

# Παίρνει το κλειδί δυναμικά από τα Environment Variables του Render
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
YOUR_DOMAIN = 'https://gta6-interactive-map-1.onrender.com'

# ==========================================
# 2. Η ΣΥΝΑΡΤΗΣΗ ΤΟΥ WATCHER (ΨΑΧΤΗΡΙ)
# ==========================================
def watcher_worker():
    """
    Αυτή η συνάρτηση τρέχει στο παρασκήνιο.
    Καλεί τον official watcher κάθε 5 λεπτά για να γεμίζει το site.
    """
    while True:
        try:
            print("Ο Watcher ψάχνει για νέα του GTA 6...")
            
            # Τρέχει τον κώδικα από το official_watcher.py
            official_watcher.run_official_watcher()
            
            time.sleep(300)  # Περιμένει 5 λεπτά (300 δευτερόλεπτα) πριν ξαναψάξει
        except Exception as e:
            print(f"Σφάλμα στον watcher: {e}")
            time.sleep(60)

# ==========================================
# 3. ΤΟ "ΚΟΛΠΟ" ΓΙΑ ΤΟ RENDER / GUNICORN
# ==========================================
# Φτιάχνουμε μια συνάρτηση που ξεκινάει το Thread και την καλούμε ΑΜΕΣΩΣ,
# έξω από το if __name__ == '__main__':
def start_background_watcher():
    watcher_thread = threading.Thread(target=watcher_worker, daemon=True)
    watcher_thread.start()
    print("✅ Ο Watcher ξεκίνησε επιτυχώς στο παρασκήνιο (Gunicorn)!")

# Εκτελείται αμέσως μόλις το Gunicorn διαβάσει το αρχείο!
start_background_watcher()

# ==========================================
# 4. ΑΡΧΙΚΟΠΟΙΗΣΗ FLASK APP & ROUTES
# ==========================================
app = Flask(__name__)

# Εξασφαλίζουμε ότι υπάρχει η βάση δεδομένων και οι πίνακες
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                category TEXT,
                tier TEXT,
                description TEXT,
                image_url TEXT,
                x REAL,
                y REAL,
                found BOOLEAN DEFAULT 0,
                status TEXT DEFAULT 'live'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_progress (
                user_key TEXT,
                location_id INTEGER,
                PRIMARY KEY(user_key, location_id)
            )
        """)
        conn.commit()

init_db()

@app.route('/')
def index():
    # Επιστρέφει το index.html με τον διαδραστικό χάρτη
    return render_template('index.html', map_url="/static/map.jpg")

@app.route('/api/locations', methods=['GET'])
def get_locations():
    # Διαβάζει τα σημεία από τον μόνιμο δίσκο
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM locations WHERE status = 'live'")
        rows = cur.fetchall()
        return jsonify([dict(row) for row in rows])

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    try:
        # Επιπλέον έλεγχος για να δούμε στα logs αν το Render διάβασε όντως το κλειδί
        if not stripe.api_key:
            print("ΣΦΑΛΜΑ: Το STRIPE_SECRET_KEY δεν βρέθηκε στο Environment του Render!")
            return jsonify(error="Stripe API key is missing"), 500

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'GTA VI Interactive Map - PRO Pass',
                        'description': 'Unlock all custom pins, live intel feed, and 100% completion tracking.',
                    },
                    'unit_amount': 999,  # $9.99 (Η τιμή με την έκπτωση)
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=YOUR_DOMAIN + '?success=true',
            cancel_url=YOUR_DOMAIN + '?canceled=true',
        )
        return jsonify({'url': session.url})
    except Exception as e:
        print(f"Stripe Error: {e}")  # Τυπώνει το ακριβές λάθος στα logs του Render για βοήθεια
        return jsonify(error=str(e)), 403

# ==========================================
# 5. ΤΟ ΚΛΑΣΙΚΟ BLOCK ΕΚΚΙΝΗΣΗΣ ΓΙΑ LOCALHOST
# ==========================================
if __name__ == '__main__':
    # Αυτό εκτελείται ΜΟΝΟ όταν το τρέχεις εσύ στο PC σου (python app.py).
    # Στο Render (Gunicorn) αυτό το κομμάτι αγνοείται πλήρως!
    print("Ξεκινάει ο τοπικός server...")
    app.run(host='0.0.0.0', port=5000, debug=False)
