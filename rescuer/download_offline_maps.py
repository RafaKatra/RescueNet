#!/usr/bin/env python3
"""
RescueNet - Offline Map Pre-Loader
-----------------------------------
Τρέχει ΜΙΑ φορά, με σύνδεση στο internet, ΠΡΙΝ την αποστολή.
Κατεβάζει τα tiles της περιοχής επιχείρησης σε τοπική βάση SQLite
ώστε ο receiver του διασώστη να λειτουργεί εντελώς offline στο πεδίο.

Μετά την προφόρτωση, το internet ΔΕΝ χρειάζεται πουθενά.
"""

from tkintermapview import OfflineLoader

# --- Βάση δεδομένων tiles (θα την διαβάζει ο receiver) ---
DATABASE = "rescuenet_tiles.db"

# --- Tile server: ΠΡΕΠΕΙ να είναι ίδιος με του receiver ---
TILE_SERVER = "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"

# --- Ορθογώνιο περιοχής (πάνω-αριστερά, κάτω-δεξιά) σε (lat, lng) ---
# Παράδειγμα: Νέα Ραιδεστός, Θεσσαλονίκη. Άλλαξέ το στην περιοχή σου.
TOP_LEFT     = (40.610, 22.960)   # ΒΔ γωνία
BOTTOM_RIGHT = (40.540, 23.030)   # ΝΑ γωνία

# --- Επίπεδα zoom. Μεγαλύτερο zoom = περισσότερη λεπτομέρεια & όγκος ---
ZOOM_MIN = 10   # ευρεία εικόνα περιοχής
ZOOM_MAX = 17   # λεπτομέρεια δρόμου/κτιρίου

if __name__ == "__main__":
    print("=" * 55)
    print("RescueNet - Προφόρτωση offline χάρτη")
    print("=" * 55)
    print(f"Περιοχή : {TOP_LEFT} -> {BOTTOM_RIGHT}")
    print(f"Zoom    : {ZOOM_MIN} έως {ZOOM_MAX}")
    print(f"Βάση    : {DATABASE}")
    print("Λήψη σε εξέλιξη (μπορεί να πάρει λίγα λεπτά)...\n")

    loader = OfflineLoader(path=DATABASE, tile_server=TILE_SERVER)
    loader.save_offline_tiles(TOP_LEFT, BOTTOM_RIGHT, ZOOM_MIN, ZOOM_MAX)
    loader.print_loaded_sections()

    print("\n✓ Ολοκληρώθηκε. Αντίγραψε το αρχείο", DATABASE,
          "δίπλα στο rescuer_receiver_en.py.")
