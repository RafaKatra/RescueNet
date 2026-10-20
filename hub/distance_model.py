#!/usr/bin/env python3
"""
RescueNet - Βελτιωμένος αλγόριθμος εκτίμησης απόστασης από RSSI
================================================================
Τρεις βελτιώσεις σε σχέση με το μοντέλο 2 σημείων:

  1) ΠΟΛΛΑΠΛΑ σημεία βαθμονόμησης με ελάχιστα τετράγωνα (least-squares).
     Το μοντέλο 2 σημείων κληρονομεί όλο τον θόρυβο αυτών των 2 μετρήσεων.
     Με 5–10 μετρήσεις και προσαρμογή ευθείας, ο εκθέτης n και το A(1m)
     βγαίνουν πολύ πιο σταθεροί.

  2) ΦΙΛΤΡΟ ΔΙΑΜΕΣΟΥ (median) στο RSSI. Το στιγμιαίο RSSI «χοροπηδά» ±πολλά dB
     λόγω multipath/fading. Η διάμεσος των τελευταίων δειγμάτων κόβει τα ξεσπάσματα
     χωρίς να καθυστερεί όσο ο μέσος όρος.

  3) ΕΞΟΜΑΛΥΝΣΗ (EMA) στην έξοδο + ΕΥΡΟΣ ΕΜΠΙΣΤΟΣΥΝΗΣ αντί για μία «ψεύτικα ακριβή»
     τιμή. Επιστρέφει κοντινό/μακρινό όριο, που είναι ειλικρινέστερο για RSSI.

Μοντέλο: RSSI(d) = A - 10 * n * log10(d)   =>   d = 10 ^ ((A - RSSI) / (10 n))

Χρήση στον receiver (rescuer_receiver_en.py):
    from distance_model import DistanceEstimator
    est = DistanceEstimator(CALIBRATION)          # μία φορά
    ...
    r = est.update(rssi)                            # για κάθε εισερχόμενο πακέτο
    print(r["distance_m"], r["min_m"], r["max_m"])  # εξομαλυμένη + εύρος
"""

import math
from collections import deque

# --- ΒΑΘΜΟΝΟΜΗΣΗ LoRa 868 MHz: ΠΡΟΣΩΡΙΝΕΣ ΤΙΜΕΣ, ΟΧΙ από μέτρηση ---
# Δίνουν n=3.14, A=-24.2 dBm. Το μοντέλο θεωρείται ΜΗ βαθμονομημένο (βλ. άρθρο §2.7, §4.7, Appendix B).
# Αντικατέστησε με πραγματικά ζεύγη (απόσταση_μέτρα, RSSI_dBm) ανά ανάπτυξη.
# Όσο περισσότερα και όσο πιο απλωμένα, τόσο καλύτερη η καμπύλη. Ελάχιστο 2, ιδανικά 6-10.
CALIBRATION = [
    (10.0,   -55.0),
    (50.0,   -78.0),
    (100.0,  -88.0),
    (300.0,  -101.0),
    (600.0,  -110.0),
    (900.0,  -118.0),
]


# --- ΒΑΘΜΟΝΟΜΗΣΗ WiFi (2.4 GHz) — ΞΕΧΩΡΙΣΤΗ ΑΠΟ ΤΟΥ LoRa ---
# ΠΡΟΣΟΧΗ: ξεχωριστή από τη LoRa. Οι τιμές είναι PLACEHOLDER — δεν έχουν μετρηθεί.
WIFI_CALIBRATION = [
    (2.0,    -38.0),
    (5.0,    -48.0),
    (10.0,   -56.0),
    (20.0,   -64.0),
    (40.0,   -72.0),
    (80.0,   -80.0),
]

class DistanceEstimator:
    def __init__(self, calibration_points, rssi_window=5, ema_alpha=0.4,
                 rssi_sigma_db=6.0):
        """
        calibration_points : λίστα (απόσταση_m, RSSI_dBm) — τουλάχιστον 2.
        rssi_window        : πλήθος δειγμάτων για τη διάμεσο (median).
        ema_alpha          : βάρος νέας μέτρησης στην εξομάλυνση εξόδου (0..1).
        rssi_sigma_db      : τυπική απόκλιση RSSI για το εύρος εμπιστοσύνης (dB).
        """
        self.n, self.A = self._fit(calibration_points)
        self.rssi_hist = deque(maxlen=max(1, rssi_window))
        self.ema = None
        self.alpha = ema_alpha
        self.sigma = rssi_sigma_db

    @staticmethod
    def _fit(points):
        """Ελάχιστα τετράγωνα: y=RSSI, x=log10(d). slope=-10n, intercept=A."""
        pts = [(float(d), float(r)) for d, r in points if d and d > 0]
        if len(pts) < 2:
            raise ValueError("Χρειάζονται τουλάχιστον 2 σημεία βαθμονόμησης")
        xs = [math.log10(d) for d, _ in pts]
        ys = [r for _, r in pts]
        m = len(pts)
        sx, sy = sum(xs), sum(ys)
        sxx = sum(x * x for x in xs)
        sxy = sum(x * y for x, y in zip(xs, ys))
        denom = m * sxx - sx * sx
        if denom == 0:
            raise ValueError("Εκφυλισμένη βαθμονόμηση (ίδιες αποστάσεις)")
        slope = (m * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / m
        n = -slope / 10.0
        A = intercept
        return n, A

    def _dist(self, rssi):
        if self.n == 0:
            return None
        return 10.0 ** ((self.A - rssi) / (10.0 * self.n))

    def _median(self):
        s = sorted(self.rssi_hist)
        k = len(s)
        if k == 0:
            return None
        return s[k // 2] if k % 2 else (s[k // 2 - 1] + s[k // 2]) / 2.0

    def update(self, rssi):
        """Δέξου ένα RSSI, γύρνα εξομαλυμένη απόσταση + εύρος (ή None)."""
        try:
            rssi = float(rssi)
        except (TypeError, ValueError):
            return None
        self.rssi_hist.append(rssi)
        med = self._median()
        d = self._dist(med)
        if d is None:
            return None
        self.ema = d if self.ema is None else self.alpha * d + (1 - self.alpha) * self.ema
        # Ισχυρότερο RSSI (+σ) -> πιο κοντά· ασθενέστερο (-σ) -> πιο μακριά
        d_near = self._dist(med + self.sigma)
        d_far = self._dist(med - self.sigma)
        return {
            "distance_m": self.ema,          # εξομαλυμένη εκτίμηση (χρησιμοποίησε αυτή)
            "raw_m": d,                       # στιγμιαία (από τη διάμεσο)
            "min_m": min(d_near, d_far),      # κοντινό όριο
            "max_m": max(d_near, d_far),      # μακρινό όριο
            "rssi_med": med,
        }

    def reset(self):
        self.rssi_hist.clear()
        self.ema = None


def fmt(d):
    if d is None:
        return "—"
    return f"~{d:.0f} m" if d < 1000 else f"~{d/1000:.2f} km"


if __name__ == "__main__":
    est = DistanceEstimator(CALIBRATION)
    print(f"Προσαρμογή: n={est.n:.2f}, A(1m)={est.A:.1f} dBm  (από {len(CALIBRATION)} σημεία)")
    print("Δοκιμή με θορυβώδη ροή RSSI γύρω στα -88 dBm (≈100 m):")
    import random
    for raw in [-86, -92, -70, -88, -90, -87, -89, -88]:
        r = est.update(raw)
        print(f"  RSSI {raw:>4} dBm  ->  raw {fmt(r['raw_m']):>9} | "
              f"εξομαλ. {fmt(r['distance_m']):>9} | εύρος {fmt(r['min_m'])}–{fmt(r['max_m'])}")
