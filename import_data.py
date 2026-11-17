import sqlite3

conn = sqlite3.connect("gta6_tracker.db")
cursor = conn.cursor()

cursor.execute("DELETE FROM locations")
cursor.execute("DELETE FROM user_progress")

clean_locations = [
    ("Vice City Beach (Ocean Drive)", "collectible", "Επιβεβαιωμένη παραλιακή ζώνη από το Trailer 1.", 780, 420),
    ("Port Vice City", "vehicle", "Κύριο λιμάνι εμπορευματοκιβωτίων & σκαφών.", 720, 310),
    ("Vice City International Airport", "vehicle", "Διεθνές αεροδρόμιο με ιδιωτικά τζετ και ελικόπτερα.", 640, 350),
    ("Grassrivers (Everglades)", "easter_egg", "Βαλτώδης περιοχή με αλιγάτορες και hovercrafts.", 480, 380),
    ("Leonida Keys", "collectible", "Σύμπλεγμα τροπικών νησιών στα νότια (από Trailer 1).", 550, 140),
    ("Port Gellhorn", "weapon", "Παρακμιακή παράκτια πόλη με μοτέλ και ενεχυροδανειστήρια.", 260, 580),
    ("Ambrosia", "vehicle", "Βιομηχανική ζώνη στο κέντρο της πολιτείας.", 490, 620),
    ("Mount Kalaga", "easter_egg", "Ορεινός όγκος στα βόρεια με μονοπάτια off-road.", 510, 880),
    ("Hamlet", "collectible", "Αγροτική κοινότητα στα περίχωρα της Leonida.", 380, 710),
    ("Thrillbilly Mud Club", "vehicle", "Πίστα mud-bogging με monster trucks.", 340, 650),
    ("Boardwalk Pawn & Gun", "weapon", "Επιβεβαιωμένο κατάστημα όπλων και ενεχυροδανειστήριο.", 750, 460),
    ("Nine1Nine Club", "easter_egg", "Γνωστό νυχτερινό κέντρο της Vice City.", 765, 490)
]

cursor.executemany(
    "INSERT INTO locations (title, category, description, x, y) VALUES (?, ?, ?, ?, ?)",
    clean_locations
)

conn.commit()
conn.close()
print("[✓] Η βάση καθάρισε! Έμειναν μόνο οι 12 επιβεβαιωμένες τοποθεσίες.")