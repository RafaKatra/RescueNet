#!/usr/bin/env python3
"""
RescueNet - tests for crypto_lora.py version 2 (replay protection, per-mission keys)
====================================================================================
Runs a hub and a base station side by side in two temporary folders, using the
real crypto_lora.py, and checks each security property. It also measures the
size of a frame (old vs new format) and how long encryption and decryption take
on this machine. Nothing on the machine is changed: all files are temporary.

Usage (in the folder that holds crypto_lora.py):
    python3 test_crypto_v2.py
It prints a table and writes test_results_crypto_v2.txt next to it.
Run it on the laptop AND on the Raspberry Pi: the timings differ.
"""
import base64
import importlib.util
import io
import json
import math
import os
import platform
import shutil
import statistics as st
import sys
import tempfile
import time
from contextlib import redirect_stderr
from datetime import datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "crypto_lora.py")
results = []


def instance(folder, name):
    """A fresh copy of crypto_lora working in its own folder (= one machine)."""
    os.environ["RESCUENET_DIR"] = folder
    os.environ.pop("RESCUENET_KEY", None)
    spec = importlib.util.spec_from_file_location(name, SRC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def quiet(fn, *a):
    with redirect_stderr(io.StringIO()):
        return fn(*a)


def check(code, name, ok, detail=""):
    results.append((code, name, "PASS" if ok else "FAIL", detail))


def airtime(n_bytes, sf=9, bw=125e3, cr=1, pre=12):
    ts = 2 ** sf / bw
    de = 1 if ts > 0.016 else 0          # low-data-rate optimisation (off at SF9, 125 kHz)
    n = 8 + max(math.ceil((8 * n_bytes - 4 * sf + 28 + 16) / (4 * (sf - 2 * de))) * (cr + 4), 0)
    return (pre + 4.25) * ts + n * ts


def new_setup(hubs="0"):
    base_dir, hub_dir = tempfile.mkdtemp(), tempfile.mkdtemp()
    base = instance(base_dir, "base")
    _silent(base._cmd_genkey)
    _silent(base._cmd_newmission, ["--hub", hubs])
    issued = json.load(open(os.path.join(base_dir, "missions_issued.json")))
    mid = next(iter(issued))
    return base_dir, hub_dir, base, int(mid)


def _silent(fn, *a):
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a)


def install_mission(base_dir, hub_dir, mid, hub):
    shutil.copy(os.path.join(base_dir, f"mission_{mid}_hub{hub}.key"),
                os.path.join(hub_dir, "mission.key"))


MSG = "Test S1|trapped 2nd floor need help|S1|40640100|22944400|0"

# ---------------------------------------------------------------- setup
base_dir, hub_dir, base, mid = new_setup("0")
install_mission(base_dir, hub_dir, mid, 0)
hub = instance(hub_dir, "hub")
base = instance(base_dir, "base")

# T1 normal report
f1 = hub.encrypt(MSG)
check("T1", "A normal report is accepted and decrypted", quiet(base.decrypt, f1) == MSG)

# T2 replay of an accepted frame
check("T2", "An identical frame sent again is rejected (replay)",
      quiet(base.decrypt, f1) is None and "replay" in (base.last_reject_reason or ""),
      base.last_reject_reason or "")

# T3 out of order within the window
fr = [hub.encrypt(MSG) for _ in range(5)]
order = [0, 2, 1, 4, 3]
got = [quiet(base.decrypt, fr[i]) == MSG for i in order]
again = [quiet(base.decrypt, fr[i]) is None for i in order]
check("T3", "Frames arriving out of order are accepted once each", all(got) and all(again),
      "delivered 1,3,2,5,4; each accepted once, each repeat rejected")

# T4 older than the window
many = [hub.encrypt(MSG) for _ in range(70)]
quiet(base.decrypt, many[69])
old = quiet(base.decrypt, many[0])
old_reason = base.last_reject_reason or ""
mid10 = quiet(base.decrypt, many[10])
check("T4", "A frame older than the 64-frame window is rejected; a late one inside it is accepted",
      old is None and "older" in old_reason and mid10 == MSG,
      "counter 69 seen; 69 back rejected, 59 back accepted")

# T5-T7 tampering
raw = bytearray(base64.b64decode(hub.encrypt(MSG)))
t = raw.copy(); t[-20] ^= 0x01
check("T5", "A changed ciphertext byte is rejected", quiet(base.decrypt, base64.b64encode(t).decode()) is None)
t = raw.copy(); t[1 + 6] ^= 0x01          # last byte of the counter inside the nonce
check("T6", "A changed counter (to slip past the replay check) is rejected",
      quiet(base.decrypt, base64.b64encode(t).decode()) is None)
t = raw.copy(); t[3] ^= 0x01              # hub id byte
check("T7", "A frame relabelled with another hub id is rejected",
      quiet(base.decrypt, base64.b64encode(t).decode()) is None)

# T8 old format (downgrade)
master = base64.b64decode(open(os.path.join(base_dir, "rescuenet.key")).read().strip())
n = os.urandom(12)
v1 = base64.b64encode(n + AESGCM(master).encrypt(n, MSG.encode(), None)).decode()
check("T8", "A frame in the old format (no replay protection) is rejected",
      quiet(base.decrypt, v1) is None, base.last_reject_reason or "")

# T9 hub restart: no counter reuse
c_before = __import__("struct").unpack(">I", base64.b64decode(hub.encrypt(MSG))[4:8])[0]
hub = instance(hub_dir, "hub_restarted")
f_after = hub.encrypt(MSG)
c_after = __import__("struct").unpack(">I", base64.b64decode(f_after)[4:8])[0]
check("T9", "After a hub restart the counter continues forward, never repeats",
      c_after > c_before and quiet(base.decrypt, f_after) == MSG,
      f"last counter before restart {c_before}, first after {c_after}")

# T10 base station restart: replay state survives
base = instance(base_dir, "base_restarted")
check("T10", "After a rescuer-station restart an old frame is still rejected",
      quiet(base.decrypt, f1) is None)

# T11 closed mission
_silent(base._cmd_closemission, [str(mid)])
check("T11", "After the mission is closed its frames are rejected",
      quiet(base.decrypt, hub.encrypt(MSG)) is None, base.last_reject_reason or "")

# T12 two hubs in one mission: separate keys and counters
b2, h2dir, base2, mid2 = new_setup("0,1")
h0dir, h1dir = h2dir, tempfile.mkdtemp()
install_mission(b2, h0dir, mid2, 0)
install_mission(b2, h1dir, mid2, 1)
hub0, hub1 = instance(h0dir, "hub0"), instance(h1dir, "hub1")
base2 = instance(b2, "base2")
a0, a1 = hub0.encrypt(MSG), hub1.encrypt(MSG)
check("T12", "Two hubs in one mission: both accepted, each with its own key and counter",
      quiet(base2.decrypt, a0) == MSG and quiet(base2.decrypt, a1) == MSG,
      "both start at counter 0 without clashing")

# T13 another base station's keys
b3, _, base3, _ = new_setup("0")
base3 = instance(b3, "base3")
check("T13", "A frame from a hub keyed by another base station is rejected",
      quiet(base3.decrypt, hub0.encrypt(MSG)) is None)

# T14 hub holds only its mission key
check("T14", "The hub folder holds no master key",
      not os.path.exists(os.path.join(hub_dir, "rescuenet.key")))

# ---------------------------------------------------------------- size and time
len_v1 = len(v1)
len_v2 = len(hub0.encrypt(MSG))
size_line = (f"frame of a typical report: old format {len_v1} characters "
             f"({airtime(len_v1):.2f} s at SF9), new format {len_v2} characters "
             f"({airtime(len_v2):.2f} s at SF9)")

N = 300
te, td = [], []
frames = []
for _ in range(N):
    s = time.perf_counter(); fr_ = hub0.encrypt(MSG); te.append((time.perf_counter() - s) * 1e3)
    frames.append(fr_)
for fr_ in frames:
    s = time.perf_counter(); quiet(base2.decrypt, fr_); td.append((time.perf_counter() - s) * 1e3)
time_line = (f"time per report on this machine ({platform.machine()}, Python "
             f"{platform.python_version()}), median of {N}: encrypt {st.median(te):.2f} ms, "
             f"verify + replay check + decrypt {st.median(td):.2f} ms")

# ---------------------------------------------------------------- report
lines = [f"RescueNet crypto_lora v2 tests - {datetime.now().isoformat(timespec='seconds')} - "
         f"{platform.node()} ({platform.system()} {platform.machine()})", ""]
for code, name, res, det in results:
    lines.append(f"{code:4s} {res}  {name}" + (f"  [{det}]" if det else ""))
passed = sum(r[2] == "PASS" for r in results)
lines += ["", f"{passed}/{len(results)} passed", "", size_line, time_line]
text = "\n".join(lines)
print(text)
out = os.path.join(HERE, "test_results_crypto_v2.txt")
with open(out, "w") as f:
    f.write(text + "\n")
print(f"\n✓ Written to {out}")
sys.exit(0 if passed == len(results) else 1)
