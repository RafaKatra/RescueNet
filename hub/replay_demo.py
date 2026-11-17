#!/usr/bin/env python3
"""
RescueNet - replay-attack demonstration (runs on the hub / Raspberry Pi)
=======================================================================
Emulates an attacker who records a genuine LoRa frame and transmits it again
later. The hub's own radio plays the attacker's transmitter.

  step 1  a genuine report is encrypted and sent once            -> station shows it
  step 2  the SAME frame, byte for byte, is sent again           -> station rejects it
  step 3  the SAME frame is sent a third time                     -> station rejects it
  step 4  a new genuine report (next counter) is sent            -> station shows it

Expected at the rescuer station: two reports appear (steps 1 and 4), and the
terminal prints "RescueNet frame rejected: replay (already accepted)" twice.
Every step is logged to replay_demo_<time>.csv on the hub.

STOP emergency_sos_lora.py FIRST: only one program can use the LoRa port.
The hub needs crypto_lora.py version 2 and a mission.key in this folder.

Usage (from the hub folder):
    python3 replay_demo.py
"""
import csv
import glob
import hashlib
import os
import sys
import time
from datetime import datetime

import serial

from compact_payload import pack
from crypto_lora import encrypt

BAUD_RATE = 115200
SETUP = ["AT", "AT+ADDRESS=0", "AT+NETWORKID=3", "AT+BAND=868000000",
         "AT+CRFOP=20", "AT+PARAMETER=9,7,1,12"]
GAP = 3.0       # seconds between steps (airtime is about 0.8 s at SF9)


def detect_port():
    for port in sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*")):
        try:
            t = serial.Serial(port=port, baudrate=BAUD_RATE, timeout=1)
            time.sleep(0.3)
            t.reset_input_buffer()
            t.write(b"AT\r\n")
            time.sleep(0.3)
            ok = "OK" in t.read(200).decode("utf-8", errors="ignore")
            t.close()
            if ok:
                return port
        except Exception:
            continue
    return None


def send(ser, frame):
    ser.reset_input_buffer()
    ser.write(f"AT+SEND=1,{len(frame)},{frame}\r\n".encode())
    t0, buf = time.time(), ""
    while time.time() - t0 < 4:
        buf += ser.read(100).decode("utf-8", errors="ignore")
        if "+OK" in buf or "+ERR" in buf:
            break
    return buf.strip()


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else detect_port()
    if not port:
        sys.exit("✗ No LoRa module found. Is emergency_sos_lora.py stopped?")
    ser = serial.Serial(port=port, baudrate=BAUD_RATE, timeout=0.1)
    time.sleep(0.5)
    for c in SETUP:
        ser.write((c + "\r\n").encode())
        time.sleep(0.25)
    ser.read(500)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = f"replay_demo_{stamp}.csv"
    f = open(out, "w", newline="")
    w = csv.writer(f)
    w.writerow(["step", "time", "what", "frame_sha256_16", "frame_chars", "module_reply"])

    genuine = encrypt(pack("Replay demo", "Original report REPLAY-DEMO", "demo", 0, 0))
    fresh = None
    steps = [(1, "genuine report, first transmission", lambda: genuine),
             (2, "replay: identical frame sent again", lambda: genuine),
             (3, "replay: identical frame sent a third time", lambda: genuine),
             (4, "new genuine report (next counter)", None)]
    print(f"✓ LoRa on {port}. Watch the rescuer station.\n")
    for n, what, get in steps:
        if get is None:
            fresh = encrypt(pack("Replay demo", "New report after the replay test", "demo", 0, 0))
            frame = fresh
        else:
            frame = get()
        reply = send(ser, frame)
        h = hashlib.sha256(frame.encode()).hexdigest()[:16]
        w.writerow([n, datetime.now().isoformat(timespec="seconds"), what, h, len(frame),
                    reply.replace("\r", " ").replace("\n", " ")])
        f.flush()
        print(f"  step {n}: {what}  [frame {h}]  module: {reply or 'no reply'}")
        if n < 4:
            time.sleep(GAP)
    f.close()
    ser.close()
    print(f"\n✓ Done. Log: {os.path.abspath(out)}")
    print("  Expected at the station: steps 1 and 4 shown, steps 2 and 3 rejected as replay.")
    print("  Take a screenshot of the station's terminal now, and copy the log to a USB stick.")


if __name__ == "__main__":
    main()
