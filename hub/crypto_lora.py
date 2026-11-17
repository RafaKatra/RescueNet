#!/usr/bin/env python3
"""
RescueNet - crypto_lora.py  (version 2: replay protection + per-mission keys)
=============================================================================
AES-128-GCM for the SOS reports carried over LoRa. The SAME file goes on the
hub (Raspberry Pi) and on the rescuer station (laptop). The rest of the system
is unchanged: the hub calls encrypt(), the rescuer calls decrypt().

What version 2 adds
-------------------
1. Replay protection. Every frame carries a counter that the hub never reuses.
   The rescuer station remembers, per mission and per hub, the highest counter
   it has accepted and which of the previous 64 it has seen, and rejects any
   frame it has already accepted or that is older than that window. The check
   runs only AFTER the frame has authenticated, so a forged frame cannot
   disturb the stored state. The state is saved to disk, so a restart of the
   station does not reopen the door to old frames.

2. Per-mission keys. The long-term master key (rescuenet.key) stays ONLY at the
   base station. Before a mission, the base derives a key for that mission and
   that hub (HKDF-SHA256) and the operator copies it to the hub as mission.key.
   A hub that is lost or captured exposes only its own key for that mission,
   and a mission can be closed so that its frames are refused from then on.

Wire format (base64 of):
    version[1] = 0x02
    nonce[12]  = mission_id[2] | hub_id[1] | counter[4] | random[5]
    ciphertext || tag[16]
The version byte is authenticated as associated data, and the nonce is bound by
GCM itself, so changing the version, mission, hub or counter breaks the tag.
Compared with version 1 the frame grows by one byte.
The counter makes each nonce unique under a key; the 5 random bytes keep it
unique even if a counter were ever repeated after a storage failure.

Commands
--------
  At the base station (laptop):
    python3 crypto_lora.py genkey                 master key, once (as before)
    python3 crypto_lora.py newmission --hub 0     key for one mission and hub 0
    python3 crypto_lora.py closemission <id>      refuse that mission from now on
  Anywhere:
    python3 crypto_lora.py status                 what is on this machine
    python3 crypto_lora.py test                   quick self-check

Install: sudo python3 -m pip install cryptography --break-system-packages
"""

import base64
import json
import os
import struct
import sys
import threading
from datetime import datetime

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION = 0x02
AAD = bytes([VERSION])
WINDOW = 64                     # how many counters back a late frame may still be
COUNTER_BLOCK = 32              # counters reserved on disk ahead of use
SALT = b"RescueNet/mission-key/v2"

_DIR = os.environ.get("RESCUENET_DIR") or os.path.dirname(os.path.abspath(__file__))
MASTER_FILE = os.path.join(_DIR, "rescuenet.key")        # base station only
MISSION_FILE = os.path.join(_DIR, "mission.key")         # hub only
COUNTER_FILE = os.path.join(_DIR, "mission_counter.json")  # hub only
ISSUED_FILE = os.path.join(_DIR, "missions_issued.json")   # base station only
STATE_FILE = os.path.join(_DIR, "replay_state.json")       # base station only

_lock = threading.Lock()
_counter = {"mission": None, "hub": None, "next": None, "reserved": None}
last_reject_reason = None


# ------------------------------------------------------------------ files
def _write_atomic(path, data, private=False):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    if private:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _read_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def _master():
    b64 = os.environ.get("RESCUENET_KEY")
    if not b64:
        if not os.path.exists(MASTER_FILE):
            raise FileNotFoundError(
                "No master key on this machine. At the base station run once: "
                "python3 crypto_lora.py genkey")
        with open(MASTER_FILE) as f:
            b64 = f.read().strip()
    k = base64.b64decode(b64)
    if len(k) not in (16, 24, 32):
        raise ValueError("The master key must be 16/24/32 bytes (base64)")
    return k


def derive_key(master, mission_id, hub_id):
    """AES-128 key for one mission and one hub (HKDF-SHA256)."""
    info = b"RescueNet mission key" + struct.pack(">HB", mission_id, hub_id)
    return HKDF(algorithm=hashes.SHA256(), length=16, salt=SALT, info=info).derive(master)


def _mission():
    if not os.path.exists(MISSION_FILE):
        raise FileNotFoundError(
            "No mission.key on this hub. At the base station run "
            "'python3 crypto_lora.py newmission --hub 0' and copy the file it makes "
            "to this folder as mission.key.")
    m = _read_json(MISSION_FILE, None)
    return int(m["mission_id"]), int(m["hub_id"]), base64.b64decode(m["key"])


# ------------------------------------------------------------------ hub side
def _next_counter(mission_id, hub_id):
    """Counter that is never reused for this mission and hub, even after a crash:
    a block of counters is written to disk BEFORE any of them is used."""
    c = _counter
    if c["mission"] != mission_id or c["hub"] != hub_id or c["next"] is None:
        saved = _read_json(COUNTER_FILE, {})
        start = saved.get("next", 0) if (saved.get("mission") == mission_id
                                          and saved.get("hub") == hub_id) else 0
        c.update(mission=mission_id, hub=hub_id, next=start, reserved=start)
    if c["next"] >= c["reserved"]:
        c["reserved"] = c["next"] + COUNTER_BLOCK
        _write_atomic(COUNTER_FILE, json.dumps(
            {"mission": mission_id, "hub": hub_id, "next": c["reserved"]}))
    if c["next"] > 0xFFFFFFFF:
        raise RuntimeError("Counter exhausted for this mission: start a new mission.")
    n = c["next"]
    c["next"] += 1
    return n


def encrypt(plaintext: str) -> str:
    """Hub: encrypt + authenticate one report under the mission key."""
    mission_id, hub_id, key = _mission()
    with _lock:
        ctr = _next_counter(mission_id, hub_id)
    nonce = struct.pack(">HBI", mission_id, hub_id, ctr) + os.urandom(5)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), AAD)
    return base64.b64encode(AAD + nonce + ct).decode("ascii")


# ------------------------------------------------------------------ rescuer side
def _reject(reason, mission_id=None, hub_id=None, ctr=None):
    global last_reject_reason
    last_reject_reason = reason
    where = "" if mission_id is None else f" (mission {mission_id}, hub {hub_id}, counter {ctr})"
    print(f"✗ RescueNet frame rejected: {reason}{where}", file=sys.stderr, flush=True)
    return None


def decrypt(token: str):
    """Rescuer: authenticate, check for replay, decrypt.
    Returns the plaintext, or None if the frame is forged, damaged, replayed,
    too old, from a closed mission, or in the old format without protection."""
    global last_reject_reason
    try:
        raw = base64.b64decode(token, validate=True)
    except Exception:
        return _reject("not valid base64")
    if len(raw) < 1 + 12 + 16:
        return _reject("too short")
    if raw[0] != VERSION:
        return _reject("old frame format without replay protection")
    nonce, ct = raw[1:13], raw[13:]
    mission_id, hub_id, ctr = struct.unpack(">HBI", nonce[:7])
    try:
        key = derive_key(_master(), mission_id, hub_id)
        plain = AESGCM(key).decrypt(nonce, ct, AAD).decode()
    except FileNotFoundError:
        raise
    except Exception:
        return _reject("authentication failed (forged or damaged)", mission_id, hub_id, ctr)

    with _lock:
        issued = _read_json(ISSUED_FILE, {})
        if issued.get(str(mission_id), {}).get("closed"):
            return _reject("mission is closed", mission_id, hub_id, ctr)
        state = _read_json(STATE_FILE, {})
        k = f"{mission_id}:{hub_id}"
        s = state.get(k)
        if s is None:
            s = {"top": ctr, "seen": 1}
        else:
            top, seen = s["top"], s["seen"]
            if ctr > top:
                shift = ctr - top
                seen = ((seen << shift) | 1) & ((1 << WINDOW) - 1) if shift < WINDOW else 1
                s = {"top": ctr, "seen": seen}
            elif top - ctr >= WINDOW:
                return _reject("older than the replay window", mission_id, hub_id, ctr)
            else:
                bit = 1 << (top - ctr)
                if seen & bit:
                    return _reject("replay (already accepted)", mission_id, hub_id, ctr)
                s = {"top": top, "seen": seen | bit}
        state[k] = s
        _write_atomic(STATE_FILE, json.dumps(state))
    last_reject_reason = None
    return plain


# ------------------------------------------------------------------ CLI
def _cmd_genkey():
    if os.path.exists(MASTER_FILE):
        print(f"⚠  A master key already exists: {MASTER_FILE}  (not replaced)")
        return
    _write_atomic(MASTER_FILE, base64.b64encode(os.urandom(16)).decode() + "\n", private=True)
    print(f"✓ Master key written: {MASTER_FILE}")
    print("  It stays on the base station. Do NOT copy it to the hub.")


def _cmd_newmission(args):
    hubs = [0]
    if "--hub" in args:
        hubs = [int(x) for x in args[args.index("--hub") + 1].split(",")]
    master = _master()
    issued = _read_json(ISSUED_FILE, {})
    while True:
        mission_id = int.from_bytes(os.urandom(2), "big")
        if str(mission_id) not in issued:
            break
    issued[str(mission_id)] = {"created": datetime.now().isoformat(timespec="seconds"),
                               "hubs": hubs, "closed": False}
    _write_atomic(ISSUED_FILE, json.dumps(issued, indent=1))
    for h in hubs:
        out = os.path.join(_DIR, f"mission_{mission_id}_hub{h}.key")
        _write_atomic(out, json.dumps({
            "version": 2, "mission_id": mission_id, "hub_id": h,
            "key": base64.b64encode(derive_key(master, mission_id, h)).decode(),
            "created": issued[str(mission_id)]["created"]}), private=True)
        print(f"✓ Mission {mission_id}, hub {h}: {out}")
    print("  Copy it to the hub folder and rename it to mission.key.")
    print("  Then delete the copy from this laptop and from the USB stick.")


def _cmd_closemission(args):
    issued = _read_json(ISSUED_FILE, {})
    mid = args[0]
    if mid not in issued:
        sys.exit(f"Mission {mid} was not issued here.")
    issued[mid]["closed"] = True
    issued[mid]["closed_at"] = datetime.now().isoformat(timespec="seconds")
    _write_atomic(ISSUED_FILE, json.dumps(issued, indent=1))
    print(f"✓ Mission {mid} closed: its frames are refused from now on.")


def _cmd_status():
    has_master = os.path.exists(MASTER_FILE) or bool(os.environ.get("RESCUENET_KEY"))
    has_mission = os.path.exists(MISSION_FILE)
    print(f"Folder: {_DIR}")
    print(f"Master key (base station): {'yes' if has_master else 'no'}")
    if has_mission:
        m, h, _ = _mission()
        c = _read_json(COUNTER_FILE, {})
        print(f"Mission key (hub): mission {m}, hub {h}; next counter on disk: {c.get('next', 0)}")
    else:
        print("Mission key (hub): no")
    if has_master and has_mission:
        print("⚠  This machine holds BOTH keys. On the hub, delete rescuenet.key.")
    issued = _read_json(ISSUED_FILE, {})
    if issued:
        print("Missions issued here:")
        for k, v in issued.items():
            print(f"  {k}: hubs {v['hubs']}, {'CLOSED' if v.get('closed') else 'open'}, {v['created']}")
    st = _read_json(STATE_FILE, {})
    if st:
        print("Replay state (mission:hub -> highest counter accepted):")
        for k, v in st.items():
            print(f"  {k} -> {v['top']}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["genkey"]:
        _cmd_genkey()
    elif a[:1] == ["newmission"]:
        _cmd_newmission(a[1:])
    elif a[:1] == ["closemission"] and len(a) > 1:
        _cmd_closemission(a[1:])
    elif a[:1] == ["status"]:
        _cmd_status()
    elif a[:1] == ["test"]:
        tok = encrypt("Test|can't breathe|field|40575000|22995000|0")
        print("frame    :", tok, f"({len(tok)} characters on air)")
        print("decrypted:", decrypt(tok))
        print("replayed :", decrypt(tok), " (None = correctly rejected)")
    else:
        print(__doc__)
