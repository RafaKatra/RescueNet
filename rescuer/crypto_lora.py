#!/usr/bin/env python3
"""
RescueNet - crypto_lora.py
==========================
AES-128-GCM (AEAD) για την κρυπτογράφηση των SOS πάνω από LoRa.
ΙΔΙΟ αρχείο σε drone (Pi) και rescuer (laptop).

Το κλειδί ΔΕΝ γεννιέται κάθε φορά. Φτιάχνεται ΜΙΑ φορά και αποθηκεύεται
μόνιμα στο αρχείο 'rescuenet.key' (δίπλα σε αυτό το script). Από εκεί και
πέρα διαβάζεται αυτόματα — δεν χρειάζεται export, δεν χρειάζεται τίποτα.

  Φτιάξε κλειδί (μία φορά):   python3 crypto_lora.py genkey
  Γρήγορο τεστ:               python3 crypto_lora.py test

Wire format: base64( nonce[12] || ciphertext || tag[16] )  -> ASCII-safe για AT+SEND.
Install: sudo python3 -m pip install cryptography --break-system-packages
"""

import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Το αρχείο κλειδιού βρίσκεται ΠΑΝΤΑ δίπλα σε αυτό το script.
_KEY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rescuenet.key")


def _key():
    """Διαβάζει το μόνιμο κλειδί από το rescuenet.key (ή από env var αν οριστεί)."""
    # (Προαιρετικό override μέσω env var — αν δεν υπάρχει, πάμε στο αρχείο.)
    b64 = os.environ.get("RESCUENET_KEY")
    if not b64:
        if not os.path.exists(_KEY_FILE):
            raise FileNotFoundError(
                "Δεν βρέθηκε κλειδί. Τρέξε μία φορά:  python3 crypto_lora.py genkey"
            )
        with open(_KEY_FILE) as f:
            b64 = f.read().strip()
    k = base64.b64decode(b64)
    if len(k) not in (16, 24, 32):
        raise ValueError("Το κλειδί πρέπει να είναι 16/24/32 bytes (base64)")
    return k


def encrypt(plaintext: str) -> str:
    """Κρυπτογράφηση + αυθεντικοποίηση. Επιστρέφει ASCII-safe base64 string."""
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, plaintext.encode(), None)  # ct = ciphertext+tag
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt(token: str):
    """Αποκρυπτογράφηση + έλεγχος γνησιότητας.
    Επιστρέφει το plaintext, ή None αν το πακέτο είναι πλαστό/κατεστραμμένο."""
    try:
        raw = base64.b64decode(token)
        return AESGCM(_key()).decrypt(raw[:12], raw[12:], None).decode()
    except Exception:
        return None


# ============================================================
# CLI:  genkey  (φτιάξε μόνιμο κλειδί) |  test  (γρήγορος έλεγχος)
# ============================================================
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "genkey":
        if os.path.exists(_KEY_FILE):
            print(f"⚠  Υπάρχει ΗΔΗ κλειδί: {_KEY_FILE}")
            print("   ΔΕΝ το αντικαθιστώ (για να μη χαλάσω τη σύζευξη με τον διασώστη).")
            print("   Αν σίγουρα θες νέο: σβήσε πρώτα το αρχείο χειροκίνητα.")
            sys.exit(0)
        key_b64 = base64.b64encode(os.urandom(16)).decode()  # 16 bytes = AES-128
        with open(_KEY_FILE, "w") as f:
            f.write(key_b64 + "\n")
        os.chmod(_KEY_FILE, 0o600)  # μόνο ο ιδιοκτήτης διαβάζει/γράφει
        print(f"✓ Μόνιμο κλειδί γράφτηκε: {_KEY_FILE}")
        print("  ➜ Αντίγραψε ΑΥΤΟ το αρχείο (rescuenet.key) και στο άλλο μηχάνημα.")
        print("  ➜ Ίδιο κλειδί σε drone + rescuer = μπορούν να μιλήσουν.")

    elif len(sys.argv) > 1 and sys.argv[1] == "test":
        msg = "NAME:Test|MESSAGE:can't breathe|LOCATION:field|LAT:40.575|LNG:22.995"
        tok = encrypt(msg)
        print("plaintext :", msg)
        print("encrypted :", tok, f"({len(tok)} chars στον αέρα)")
        print("decrypted :", decrypt(tok))
        print("forged    :", decrypt("XXXX" + tok[4:]), "  (None = σωστά απορρίφθηκε)")

    else:
        print("Χρήση: python3 crypto_lora.py genkey   # φτιάξε μόνιμο κλειδί (μία φορά)")
        print("       python3 crypto_lora.py test     # γρήγορος έλεγχος")
