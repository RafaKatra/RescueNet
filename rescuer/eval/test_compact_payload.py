"""Component validation of the compaction stage (paper Table 4).

Checks, on randomly generated reports and on edge cases, that
pack() -> [AES-128-GCM v1 encrypt -> decrypt] -> unpack() returns the
intended fields, and records the on-air size and airtime (SF9, 125 kHz, CR 4/5, 12-symbol preamble: the active radio setting).
Usage: python3 test_compact_payload.py [path to hub folder, default ../../hub]
The version-1 frame format (crypto_lora_v1.py) is used, as in the field measurements.
"""
import os, sys, random, string, math, base64, json
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "hub"))
os.environ["RESCUENET_KEY"] = base64.b64encode(os.urandom(16)).decode()
from compact_payload import pack, unpack, SEP
from crypto_lora_v1 import encrypt, decrypt

NAME_MAX, MSG_MAX, LOC_MAX = 20, 80, 25


def airtime(pl, sf=9, bw=125e3, cr=1, npre=12, crc=1, ih=0, de=None):
    ts = 2 ** sf / bw
    if de is None:
        de = 1 if ts > 0.016 else 0      # low-data-rate optimisation (off at SF9, 125 kHz)
    npay = 8 + max(math.ceil((8 * pl - 4 * sf + 28 + 16 * crc - 20 * ih) / (4 * (sf - 2 * de))) * (cr + 4), 0)
    return (npre + 4.25) * ts + npay * ts


def clean(s, n):
    return s.replace(SEP, " ").replace("\n", " ").replace("\r", " ").strip()[:n]


rng = random.Random(42)
alpha = string.ascii_letters + string.digits + " .,!?'-"
results = {}
fails = []

# 1. Random Latin-script reports, full chain
N = 1000
max_coord_err = 0.0
for i in range(N):
    name = "".join(rng.choice(alpha) for _ in range(rng.randint(0, 30)))
    msg = "".join(rng.choice(alpha) for _ in range(rng.randint(0, 120)))
    loc = "".join(rng.choice(alpha) for _ in range(rng.randint(0, 40)))
    lat, lng = rng.uniform(-90, 90), rng.uniform(-180, 180)
    rec = unpack(decrypt(encrypt(pack(name, msg, loc, lat, lng))))
    exp_name = clean(name, NAME_MAX) or "Unknown"
    ok = (rec["name"] == exp_name and rec["message"] == clean(msg, MSG_MAX)
          and rec["location"] == clean(loc, LOC_MAX))
    err = max(abs(rec["lat"] - lat), abs(rec["lng"] - lng))
    max_coord_err = max(max_coord_err, err)
    if not ok or err > 0.5e-6 + 1e-12:
        fails.append(("random", i))
results["R1 random Latin reports round-trip (n=1000)"] = f"{N - len([f for f in fails if f[0]=='random'])}/{N}"
results["R1 max coordinate error (deg)"] = f"{max_coord_err:.2e}"

# 2. Separator / newline injection
inj = pack("a|b", "x|y|z\nnew", "l|m", 40.5, 23.0)
r = unpack(inj)
results["R2 separator and newline injection neutralised"] = (
    "pass" if inj.count(SEP) == 5 and r["message"] == "x y z new" and r["lat"] == 40.5 else "FAIL")

# 3. Missing / invalid GPS
r = unpack(pack("n", "m", "", None, "abc"))
results["R3 missing or invalid GPS encoded as 0"] = "pass" if (r["lat"], r["lng"]) == (0.0, 0.0) else "FAIL"

# 4. Truncated record still parses (robustness)
r = unpack("name|msg")
results["R4 truncated record parsed without exception"] = "pass" if r["lat"] == 0.0 and r["message"] == "msg" else "FAIL"

# 5. Greek text round-trip
g = unpack(decrypt(encrypt(pack("Ορέστης", "Φωτιά καιγόμαστε βοήθεια", "Λάρισα", 39.64, 22.42))))
results["R5 Greek text round-trip"] = "pass" if g["message"] == "Φωτιά καιγόμαστε βοήθεια" else "FAIL"

# 6. Tampering
tok = encrypt(pack("n", "m", "l", 1, 2))
raw = bytearray(base64.b64decode(tok)); raw[20] ^= 1
results["R6 bit-flipped frame rejected"] = "pass" if decrypt(base64.b64encode(bytes(raw)).decode()) is None else "FAIL"

# Sizes and airtime
def onair(name, msg, loc, lat, lng):
    p = pack(name, msg, loc, lat, lng)
    return len(p.encode()), len(encrypt(p))

legacy = "NAME:Orestis|MESSAGE:There is fire in front of my house, we are ok.|LOCATION:Larissa|LAT:39.639022|LNG:22.419125"
sizes = []
p_rep, e_rep = onair("Orestis", "There is fire in front of my house, we are ok.", "Larissa", 39.639022, 22.419125)
sizes.append(("Representative report (Table 3)", p_rep, e_rep))
p_max, e_max = onair("N" * 40, "M" * 200, "L" * 60, -89.999999, -179.999999)
sizes.append(("Latin script, every field at maximum", p_max, e_max))
p_gr, e_gr = onair("Ν" * 40, "Μ" * 200, "Λ" * 60, -89.999999, -179.999999)
sizes.append(("Greek script, every field at maximum", p_gr, e_gr))
p_min, e_min = onair("", "", "", None, None)
sizes.append(("Empty form, no GPS", p_min, e_min))
results["sizes"] = [dict(case=c, packed_bytes=pb, onair_chars=oa, airtime_s=round(airtime(oa), 2),
                         within_240=oa <= 240) for c, pb, oa in sizes]
results["legacy_example_bytes"] = len(legacy.encode())
results["failures"] = fails
print(json.dumps(results, indent=1, ensure_ascii=False))
