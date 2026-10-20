#!/usr/bin/env python3
"""
RescueNet - compact_payload.py
==============================
Συμπυκνώνει το SOS ΠΡΙΝ την κρυπτογράφηση, ώστε να πέφτει το μέγεθος
(και άρα το airtime + η πιθανότητα CRC loss στο SF12).

ΙΔΙΟ αρχείο σε drone + rescuer. Οι δύο πλευρές ΠΡΕΠΕΙ να συμφωνούν
απόλυτα στη δομή — γι' αυτό είναι ένα κοινό module.

Δομή (μετά το pack, πριν το encrypt):
    "<name>|<message>|<location>|<lat_int>|<lng_int>|<wifi_m>"
όπου lat_int = round(lat * 1_000_000)  (ακέραιος, 6 δεκαδικά ≈ 11 cm ακρίβεια)
και wifi_m = προαιρετικό 6ο πεδίο (απόσταση θύματος->hub σε μέτρα· 0 = δεν μετρήθηκε,
πάντα 0 στο released build — βλ. άρθρο §2.2).

Σε σχέση με το παλιό format με labels (NAME:/MESSAGE:/...), γλιτώνει
~40 bytes labels + ~10 bytes από τις συντεταγμένες (int αντί για string).

Η ροή γίνεται:
    Drone   : πεδία -> pack() -> encrypt() -> base64 -> AT+SEND
    Rescuer : +RCV -> base64 -> decrypt() -> unpack() -> πεδία
"""

SEP = "|"
COORD_SCALE = 1_000_000   # 6 δεκαδικά ψηφία


def _clean(s, maxlen):
    """Καθαρίζει την είσοδο του χρήστη: αφαιρεί τον separator/newlines, κόβει μήκος."""
    s = str(s if s is not None else "").replace(SEP, " ").replace("\n", " ").replace("\r", " ").strip()
    return s[:maxlen]


def pack(name, message, location, lat, lng, wifi_m=0,
         name_max=20, msg_max=80, loc_max=25):
    """
    Παίρνει τα πεδία του SOS και επιστρέφει ένα ΣΥΜΠΥΚΝΩΜΕΝ�ο string
    (χωρίς labels, με packed coords) έτοιμο για κρυπτογράφηση.
    """
    name = _clean(name, name_max)
    message = _clean(message, msg_max)
    location = _clean(location, loc_max)

    # Συντεταγμένες -> ακέραιοι. 0 αν λείπουν/άκυρες.
    try:
        lat_i = int(round(float(lat) * COORD_SCALE))
    except (TypeError, ValueError):
        lat_i = 0
    try:
        lng_i = int(round(float(lng) * COORD_SCALE))
    except (TypeError, ValueError):
        lng_i = 0

    # Απόσταση drone->θύματος από WiFi RSSI, σε ακέραια μέτρα. 0 = άγνωστη.
    try:
        wifi_i = max(0, int(round(float(wifi_m))))
    except (TypeError, ValueError):
        wifi_i = 0

    return SEP.join([name, message, location, str(lat_i), str(lng_i), str(wifi_i)])


def unpack(packed):
    """
    Αντίστροφο του pack(). Παίρνει το ΑΠΟΚΡΥΠΤΟΓΡΑΦΗΜΕΝΟ συμπυκνωμένο string
    και επιστρέφει dict με τα πεδία (lat/lng ως float, ή 0.0 αν λείπουν).
    Ανθεκτικό: αν λείπουν πεδία, γεμίζει με κενά/0.
    """
    parts = packed.split(SEP)
    # Συμπλήρωσε αν λείπουν πεδία (π.χ. κομμένο μήνυμα)
    while len(parts) < 6:
        parts.append("")

    name, message, location, lat_s, lng_s, wifi_s = parts[:6]

    def to_coord(x):
        try:
            return int(x) / COORD_SCALE
        except (TypeError, ValueError):
            return 0.0

    return {
        "name": name or "Unknown",
        "message": message,
        "location": location,
        "lat": to_coord(lat_s),
        "lng": to_coord(lng_s),
        "wifi_m": int(wifi_s) if str(wifi_s).isdigit() else 0,
    }


# ============================================================
# CLI: γρήγορος έλεγχος round-trip
# ============================================================
if __name__ == "__main__":
    p = pack("Orestis", "There is fire in front of my house, we are ok.",
             "Souroti", 40.535342, 23.057351)
    print("packed  :", p)
    print("μήκος   :", len(p), "bytes (vs ~112 με labels)")
    print("unpacked:", unpack(p))

    # έλεγχος: χωρίς GPS
    p2 = pack("Takis", "Ok", "", 0, 0)
    print("\nχωρίς GPS packed:", p2)
    print("unpacked        :", unpack(p2))
