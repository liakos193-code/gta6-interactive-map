import os
import sqlite3
import threading
import time
from flask import Flask, render_template, request, jsonify
import stripe

# ==========================================
# 1. ΡΥΘΜΙΣΕΙΣ (ΦΑΚΕΛΟΣ ΓΙΑ ΤΟ RENDER & STRIPE)
# ==========================================
DATA_DIR = "/var/data" if os.path.isdir("/var/data") else "."
DB_NAME = os.path.join(DATA_DIR, "gta6_tracker.db")

# Βάλε εδώ τα κλειδιά σου από το Stripe
stripe.api_key = "sk_test_ΒΑΛΕ_ΤΟ_ΔΙΚΟ_ΣΟΥ_ΜΥΣΤΙΚΟ_ΚΛΕΙΔΙ"
YOUR_DOMAIN = 'https://gta6-interactive-map-1.onrender.com'

# ==========================================
# 2. Η ΣΥΝΑΡΤΗΣΗ ΤΟΥ WATCHER (ΨΑΧΤΗΡΙ)
# ==========================================
def watcher_worker():
    """
    Αυτή η συνάρτηση θα τρέχει στο παρασκήνιο.
    Βάλε εδώ μέσα τον ΔΙΚΟ ΣΟΥ κώδικα (scraping/RSS) που μαζεύει τα νέα!
    """
    while True:
        try:
            print("Ο Watcher ψάχνει για νέα του GTA 6...")

            # --- ΕΔΩ ΜΠΑΙΝΕΙ Ο ΔΙΚΟΣ ΣΟΥ ΚΩΔΙΚΑΣ ΑΝΑΖΗΤΗΣΗΣ ---


            # --------------------------------------------------

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
        # Πρόσθεσε εδώ και τα CREATE TABLE για intel_news κλπ αν δεν υπάρχουν
        conn.commit()

init_db()

@app.route('/')
def index():
    # Επιστρέφει το index.html που φτιάξαμε νωρίτερα με το 30% Offer
    return render_template('index.html', map_url="/static/map.jpg")

@app.route('/api/locations', methods=['GET'])
def get_locations():
    # Παράδειγμα API που διαβάζει τα σημεία από τον μόνιμο δίσκο
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM locations WHERE status = 'live'")
        rows = cur.fetchall()
        return jsonify([dict(row) for row in rows])

@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    try:
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
        return jsonify(error=str(e)), 403

# ==========================================
# 5. ΤΟ ΚΛΑΣΙΚΟ BLOCK ΕΚΚΙΝΗΣΗΣ ΓΙΑ LOCALHOST
# ==========================================
if __name__ == '__main__':
    # Αυτό εκτελείται ΜΟΝΟ όταν το τρέχεις εσύ στο PC σου (python app.py).
    # Στο Render (Gunicorn) αυτό το κομμάτι αγνοείται πλήρως!
    print("Ξεκινάει ο τοπικός server...")
    app.run(host='0.0.0.0', port=5000, debug=False)
