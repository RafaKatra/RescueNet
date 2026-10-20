#!/usr/bin/env python3
"""
RescueNet - Rescuer Station (replaces the APK)
-----------------------------------------------
Laptop Linux + LoRa (RYLR998). Receives SOS from the drone, places
coordinates on an OFFLINE map and shows signal strength (RSSI), SNR
and ESTIMATED distance from the drone. No internet required in the field.

Prerequisite: run download_offline_maps.py first (creates rescuenet_tiles.db).

Dependencies:
    pip install pyserial tkintermapview
    (Linux: sudo apt install python3-tk)
"""

import os
import math
import time
import glob
import queue
import threading
from datetime import datetime

import serial
import tkinter as tk
from tkinter import ttk
import tkintermapview

# Improved distance model (least-squares + median + EMA + confidence range)
from distance_model import DistanceEstimator, CALIBRATION

# SOS message urgency classifier (rule-based default, ML optional)
from priority_classifier import classify_priority, priority_color, priority_rank

# ============================================================
# LoRa SETTINGS - MUST MATCH THE DRONE
# ============================================================
LORA_PORT   = None              # None = auto-detect (ttyUSB0, ttyUSB1, ...)
BAUD_RATE   = 115200
ADDRESS     = 1                 # rescuer = address 1 (drone sends here)
NETWORK_ID  = 3
BAND        = 868000000         # 868 MHz - same as drone
PARAMETER   = "12,7,1,8"        # SF=12, BW=7, CR=1, preamble=8 - same as drone
POWER       = 20                # dBm

# ============================================================
# DISTANCE ESTIMATION - uses distance_model.py
# ============================================================
# One estimator per sender (keeps RSSI history -> median + EMA).
# For a single drone one is enough; multiple drones are handled automatically.
_estimators = {}

def get_estimator(addr):
    if addr not in _estimators:
        _estimators[addr] = DistanceEstimator(CALIBRATION)
    return _estimators[addr]


def estimate_distance(addr, rssi):
    """Feed RSSI to estimator, return dict or None."""
    est = get_estimator(addr)
    return est.update(rssi)


def fmt_distance(d):
    if d is None:
        return "-"
    return f"~{d:.0f} m" if d < 1000 else f"~{d/1000:.2f} km"


def fmt_range(r):
    """Format confidence range: '~100 m (65-156 m)'"""
    if r is None:
        return "-"
    d = r["distance_m"]
    lo, hi = r["min_m"], r["max_m"]
    if d < 1000:
        return f"~{d:.0f} m ({lo:.0f}–{hi:.0f} m)"
    return f"~{d/1000:.2f} km ({lo/1000:.2f}–{hi/1000:.2f} km)"


# ============================================================
# AUTO-DETECT LoRa PORT (same logic as drone)
# ============================================================

def detect_lora_port():
    """Tries ttyUSB0, ttyUSB1, ..., ttyACM* with AT probe."""
    candidates = sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*"))
    if not candidates:
        return None
    for port in candidates:
        try:
            t = serial.Serial(port=port, baudrate=BAUD_RATE, timeout=1)
            time.sleep(0.3)
            try:
                t.reset_input_buffer()
            except Exception:
                pass
            t.write(b"AT\r\n")
            time.sleep(0.3)
            resp = t.read(200).decode('utf-8', errors='ignore')
            t.close()
            if "+OK" in resp or "OK" in resp:
                print(f"✓ LoRa detected on port {port}")
                return port
        except Exception:
            continue
    print(f"⚠ No port responded — fallback to {candidates[0]}")
    return candidates[0]

# ============================================================
# OFFLINE MAP
# ============================================================
TILE_DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "rescuenet_tiles.db")
TILE_SERVER   = "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png"  # same as downloader
DEFAULT_VIEW  = (40.575, 22.995)   # default center when no SOS yet
DEFAULT_ZOOM  = 13

sos_queue = queue.Queue()   # serial thread -> GUI thread


# ============================================================
# LoRa - init & receive
# ============================================================
def init_lora():
    port = LORA_PORT or detect_lora_port()
    if not port:
        raise RuntimeError("No LoRa serial port found")
    ser = serial.Serial(port=port, baudrate=BAUD_RATE, timeout=1)
    time.sleep(0.5)
    for cmd in [
        "AT",
        f"AT+ADDRESS={ADDRESS}",
        f"AT+NETWORKID={NETWORK_ID}",
        f"AT+BAND={BAND}",
        f"AT+PARAMETER={PARAMETER}",
        f"AT+CRFOP={POWER}",
    ]:
        ser.write((cmd + "\r\n").encode())
        time.sleep(0.2)
    ser.read(500)  # flush +OK responses
    print(f"✓ LoRa receiver: {port} | ADDRESS={ADDRESS}, NET={NETWORK_ID}, "
          f"{BAND/1e6:.0f} MHz, PARAMETER={PARAMETER}, {POWER} dBm")
    _e = DistanceEstimator(CALIBRATION)
    print(f"✓ Distance model: n={_e.n:.2f}, A={_e.A:.1f} dBm "
          f"({len(CALIBRATION)} calibration points)")
    return ser

def parse_rcv(line):
    """+RCV=<addr>,<len>,<payload>,<rssi>,<snr>  ->  dict or None"""
    if not line.startswith("+RCV="):
        return None
    try:
        body = line[len("+RCV="):]
        left, rssi, snr = body.rsplit(",", 2)        # rssi/snr = always last 2
        addr, _length, payload = left.split(",", 2)  # addr/len = always first 2
    except ValueError:
        return None

    from crypto_lora import decrypt
    from compact_payload import unpack
    payload = decrypt(payload)
    if payload is None:
        return None

    fields = unpack(payload)

    def to_float(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    rssi = rssi.strip()
    dist_result = estimate_distance(addr, rssi)
    return {
        "from_addr": addr,
        "rssi": rssi,
        "snr": snr.strip(),
        "distance_m": dist_result["distance_m"] if dist_result else None,
        "dist_min": dist_result["min_m"] if dist_result else None,
        "dist_max": dist_result["max_m"] if dist_result else None,
        "dist_result": dist_result,
        "name": fields["name"],
        "message": fields["message"],
        "location": fields["location"],
        "wifi_m": fields.get("wifi_m", 0),   # απόσταση θύματος->hub (WiFi)
        "lat": fields["lat"] or None,
        "lng": fields["lng"] or None,
        "time": datetime.now().strftime("%H:%M:%S"),
    }


def lora_listen_thread(ser):
    """Runs continuously, pushes valid SOS to queue."""
    buf = b""
    while True:
        try:
            buf += ser.read(256)
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                sos = parse_rcv(line)
                if sos:
                    sos_queue.put(sos)
                    print(f"✓ SOS: {sos['name']} | RSSI {sos['rssi']} "
                          f"-> {fmt_range(sos['dist_result'])} from drone")
        except Exception as e:
            print(f"⚠ Receive error: {e}")
            time.sleep(1)


# ============================================================
# GUI - map + SOS list + signal/distance + rings
# ============================================================

# Rescuer reference position (used as ring center when no GPS).
# In the field, update with the rescuer's actual position or laptop GPS.
# or use the rescuer laptop's GPS.
RESCUER_POS = DEFAULT_VIEW     # (lat, lng) initial position

# Ring colors (inner -> outer)
RING_COLORS = ["#FF0000", "#FF6600", "#FFCC00"]


class RescueNetApp:
    def __init__(self, root):
        self.root = root
        root.title("RescueNet — Rescuer Station")
        root.geometry("1280x780")

        # Resizable split: drag the divider to widen/narrow the left panel
        paned = ttk.PanedWindow(root, orient="horizontal")
        paned.pack(fill="both", expand=True)

        # ---------- Left panel: incoming SOS ----------
        left = ttk.Frame(paned, width=430)
        paned.add(left, weight=0)

        ttk.Label(left, text="📡 Incoming SOS Alerts",
                  font=("Helvetica", 14, "bold")).pack(pady=(10, 5))

        # Priority classifier backend toggle (label on its own line so nothing is cut)
        pri_frame = ttk.Frame(left)
        pri_frame.pack(fill="x", padx=8, pady=(0, 3))
        ttk.Label(pri_frame, text="Priority engine:",
                  font=("Helvetica", 9, "bold")).pack(anchor="w")
        pri_radios = ttk.Frame(left)
        pri_radios.pack(fill="x", padx=8, pady=(0, 5))
        self.priority_backend = tk.StringVar(value="rule")
        ttk.Radiobutton(pri_radios, text="Rule-based (recommended)",
                        variable=self.priority_backend, value="rule",
                        command=self._reclassify_all).pack(anchor="w")
        ttk.Radiobutton(pri_radios, text="ML (needs scikit-learn)",
                        variable=self.priority_backend, value="ml",
                        command=self._reclassify_all).pack(anchor="w")

        # Priority legend so the meaning of colors is always visible
        legend = ttk.Label(
            left, text="🔴 CRITICAL   🟠 HIGH   🟡 MEDIUM   🟢 LOW",
            font=("Helvetica", 9))
        legend.pack(anchor="w", padx=8, pady=(0, 3))

        # Stats panel (wraps instead of being cut off)
        self.stats_var = tk.StringVar(value="Waiting for SOS...")
        ttk.Label(left, textvariable=self.stats_var, font=("Consolas", 9),
                  wraplength=410, justify="left").pack(anchor="w", padx=8, pady=(0, 5))

        self.listbox = tk.Listbox(left, font=("Consolas", 10),
                                  selectbackground="#2196F3")
        self.listbox.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        self.detail = tk.Text(left, height=11, wrap="word",
                              font=("Helvetica", 10), bg="#1a1a2e", fg="#e0e0e0")
        self.detail.pack(fill="x", padx=8, pady=(0, 8))
        self.detail.insert("1.0", "Waiting for SOS signal...")
        self.detail.config(state="disabled")

        # Drone altitude input (Pythagorean correction: slant -> ground distance)
        alt_frame = ttk.Frame(left)
        alt_frame.pack(fill="x", padx=8, pady=(0, 5))
        ttk.Label(alt_frame, text="🛩 Drone altitude (m):",
                  font=("Helvetica", 10)).pack(side="left")
        self.alt_var = tk.StringVar(value="0")
        alt_entry = ttk.Entry(alt_frame, textvariable=self.alt_var, width=6,
                              font=("Consolas", 11))
        alt_entry.pack(side="left", padx=(5, 0))
        ttk.Label(alt_frame, text="(0 = off)",
                  font=("Helvetica", 8)).pack(side="left", padx=(5, 0))
        # Re-render details live when altitude changes
        self.alt_var.trace_add("write", lambda *a: self._on_alt_change())

        # Sort + clear buttons
        btn_frame = ttk.Frame(left)
        btn_frame.pack(fill="x", padx=8, pady=(0, 10))
        ttk.Button(btn_frame, text="⚡ Sort by Priority",
                   command=self._sort_by_priority).pack(side="left", expand=True, fill="x")
        ttk.Button(btn_frame, text="🗑 Clear Map",
                   command=self.clear_map).pack(side="left", expand=True, fill="x", padx=(5, 0))

        # ---------- Right panel: offline map ----------
        right = ttk.Frame(paned)
        paned.add(right, weight=1)

        offline_ok = os.path.exists(TILE_DATABASE)
        self.map = tkintermapview.TkinterMapView(
            right,
            database_path=TILE_DATABASE if offline_ok else None,
            use_database_only=offline_ok,
        )
        self.map.pack(fill="both", expand=True)
        self.map.set_tile_server(TILE_SERVER)
        self.map.set_position(*DEFAULT_VIEW)
        self.map.set_zoom(DEFAULT_ZOOM)

        if not offline_ok:
            print("⚠ Not found:", TILE_DATABASE,
                  "- run download_offline_maps.py first.")

        self.records = []
        self._markers = []
        self._ring_markers = []
        self.poll_queue()

    def _on_alt_change(self):
        """When the altitude field changes, refresh the currently shown detail."""
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self.records):
            return
        sos = self.records[sel[0]]
        has_gps = sos["lat"] not in (None, 0) and sos["lng"] not in (None, 0)
        try:
            self.show_detail(sos, has_gps)
        except Exception:
            pass

    def _get_drone_alt(self):
        """Read drone altitude from the input field. Returns 0 if empty/invalid."""
        try:
            return max(0.0, float(self.alt_var.get()))
        except (ValueError, TypeError):
            return 0.0

    def _slant_to_ground(self, slant_m):
        """Pythagorean correction: slant range -> ground distance.
        If altitude >= slant, returns 0 (drone is directly above)."""
        alt = self._get_drone_alt()
        if alt <= 0 or slant_m is None:
            return slant_m
        if alt >= slant_m:
            return 0.0
        return math.sqrt(slant_m ** 2 - alt ** 2)

    def poll_queue(self):
        try:
            while True:
                self.add_sos(sos_queue.get_nowait())
        except queue.Empty:
            pass
        self.root.after(300, self.poll_queue)

    def add_sos(self, sos):
        idx = len(self.records)
        # Classify urgency from message text (rule-based by default)
        sos["priority_result"] = classify_priority(
            sos.get("message", ""), backend=self.priority_backend.get())
        self.records.append(sos)

        has_gps = sos["lat"] not in (None, 0) and sos["lng"] not in (None, 0)
        gps_tag = "📍" if has_gps else "📡"
        dist_s = fmt_distance(sos["distance_m"])
        pri = sos["priority_result"]["priority"]
        pri_tag = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡",
                  "LOW": "🟢", "UNKNOWN": "⚪"}.get(pri, "⚪")
        label = f"{pri_tag} {gps_tag} [{sos['time']}] {sos['name']}  {dist_s}  [{pri}]"
        self.listbox.insert("end", label)
        # Priority color takes precedence over the GPS/distance-only color
        self.listbox.itemconfig("end", bg=priority_color(pri), fg="white")
        self.listbox.see("end")
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set("end")

        if has_gps:
            m = self.map.set_marker(sos["lat"], sos["lng"],
                                    text=f"🆘 #{idx+1} {sos['name']} [{pri}]")
            self._markers.append(m)
            self.map.set_position(sos["lat"], sos["lng"])
            self.map.set_zoom(16)
        else:
            # No GPS: distance rings around reference position
            self._draw_distance_rings(sos, idx)

        self.show_detail(sos, has_gps)
        self._update_stats()

    def _reclassify_all(self):
        """Re-run priority classification on all existing SOS with the newly
        selected backend, and refresh the list colors/labels/details."""
        backend = self.priority_backend.get()
        for sos in self.records:
            sos["priority_result"] = classify_priority(sos.get("message", ""), backend=backend)
        self._refresh_listbox()

    def _refresh_listbox(self):
        """Rebuild the listbox contents from self.records (after reclassify/sort)."""
        selected = self.listbox.curselection()
        selected_idx = selected[0] if selected else None
        self.listbox.delete(0, "end")
        for sos in self.records:
            has_gps = sos["lat"] not in (None, 0) and sos["lng"] not in (None, 0)
            gps_tag = "📍" if has_gps else "📡"
            dist_s = fmt_distance(sos["distance_m"])
            pri = sos["priority_result"]["priority"]
            pri_tag = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡",
                      "LOW": "🟢", "UNKNOWN": "⚪"}.get(pri, "⚪")
            label = f"{pri_tag} {gps_tag} [{sos['time']}] {sos['name']}  {dist_s}  [{pri}]"
            self.listbox.insert("end", label)
            self.listbox.itemconfig("end", bg=priority_color(pri), fg="white")
        if selected_idx is not None and selected_idx < self.listbox.size():
            self.listbox.selection_set(selected_idx)

    def _sort_by_priority(self):
        """Sorts the SOS list so the most urgent (CRITICAL) appears first."""
        self.records.sort(key=lambda s: priority_rank(s["priority_result"]["priority"]))
        self._refresh_listbox()

    @staticmethod
    def _victim_line(sos):
        """Victim<->drone distance, measured at the hub from the client WiFi RSSI.
        Distinct from the LoRa drone<->rescuer range above. 0 = not reported."""
        w = sos.get("wifi_m", 0) or 0
        if w > 0:
            return f"Victim<->drone: ~{w:.0f} m   (WiFi RSSI at hub)\n"
        return "Victim<->drone: not reported (within WiFi range of drone)\n"

    def _draw_distance_rings(self, sos, idx):
        """Draws distance rings (min/estimate/max) on map around RESCUER_POS.
        Uses ground distance (Pythagorean correction) if drone altitude is set."""
        dr = sos.get("dist_result")
        if dr is None:
            return
        center = RESCUER_POS
        # Apply ground correction to all three radii
        gnd_min = self._slant_to_ground(dr["min_m"])
        gnd_est = self._slant_to_ground(dr["distance_m"])
        gnd_max = self._slant_to_ground(dr["max_m"])
        if gnd_min is None or gnd_est is None or gnd_max is None:
            return
        lo, hi = min(gnd_min, gnd_max), max(gnd_min, gnd_max)
        radii = [
            (lo, RING_COLORS[0], f"#{idx+1} near ({lo:.0f}m)"),
            (gnd_est, RING_COLORS[1], f"#{idx+1} est. ({gnd_est:.0f}m)"),
            (hi, RING_COLORS[2], f"#{idx+1} far ({hi:.0f}m)"),
        ]
        for radius_m, color, label in radii:
            ring_pts = self._circle_points(center[0], center[1], radius_m, 36)
            try:
                path = self.map.set_path(ring_pts, color=color, width=2)
                self._ring_markers.append(path)
            except Exception:
                pass
        # Marker at center (rescuer position)
        try:
            m = self.map.set_marker(center[0], center[1],
                                    text=f"📡 #{idx+1} {sos['name']} (~{dr['distance_m']:.0f}m)")
            self._markers.append(m)
        except Exception:
            pass
        self.map.set_position(*center)
        self.map.set_zoom(14)

    @staticmethod
    def _circle_points(lat, lng, radius_m, n=36):
        """Geodetic circle points around (lat, lng) in meters."""
        points = []
        for i in range(n + 1):
            angle = math.radians(360.0 * i / n)
            dlat = (radius_m * math.cos(angle)) / 111320.0
            dlng = (radius_m * math.sin(angle)) / (111320.0 * math.cos(math.radians(lat)))
            points.append((lat + dlat, lng + dlng))
        return points

    def clear_map(self):
        """Clears markers + rings."""
        for m in self._markers:
            try:
                m.delete()
            except Exception:
                pass
        for p in self._ring_markers:
            try:
                p.delete()
            except Exception:
                pass
        self._markers.clear()
        self._ring_markers.clear()

    def _update_stats(self):
        total = len(self.records)
        with_gps = sum(1 for r in self.records
                       if r["lat"] not in (None, 0) and r["lng"] not in (None, 0))
        n_crit = sum(1 for r in self.records
                    if r.get("priority_result", {}).get("priority") == "CRITICAL")
        n_high = sum(1 for r in self.records
                    if r.get("priority_result", {}).get("priority") == "HIGH")
        self.stats_var.set(
            f"Total: {total} | GPS: {with_gps} | Dist. only: {total - with_gps} | "
            f"🔴 Critical: {n_crit} | 🟠 High: {n_high}")

    def on_select(self, _event):
        sel = self.listbox.curselection()
        if not sel:
            return
        sos = self.records[sel[0]]
        has_gps = sos["lat"] not in (None, 0) and sos["lng"] not in (None, 0)
        if has_gps:
            self.map.set_position(sos["lat"], sos["lng"])
            self.map.set_zoom(16)
        self.show_detail(sos, has_gps)

    def show_detail(self, sos, has_gps):
        dr = sos.get("dist_result")
        alt = self._get_drone_alt()
        pr = sos.get("priority_result", {"priority": "UNKNOWN", "score": 0.0,
                                         "backend": "none", "matched": None})
        pri_line = f"{pr['priority']} (backend={pr['backend']}, score={pr['score']:.2f})"
        if pr.get("matched"):
            pri_line += f"  [matched: \"{pr['matched']}\"]"

        # Slant range (raw from LoRa RSSI)
        slant_line = fmt_range(dr)

        # Ground distance (Pythagorean correction)
        if dr and alt > 0:
            gnd = self._slant_to_ground(dr["distance_m"])
            gnd_min = self._slant_to_ground(dr["min_m"])
            gnd_max = self._slant_to_ground(dr["max_m"])
            if gnd is not None and gnd_min is not None and gnd_max is not None:
                lo, hi = min(gnd_min, gnd_max), max(gnd_min, gnd_max)
                if gnd < 1000:
                    ground_line = f"~{gnd:.0f} m ({lo:.0f}-{hi:.0f} m)"
                else:
                    ground_line = f"~{gnd/1000:.2f} km ({lo/1000:.2f}-{hi/1000:.2f} km)"
            else:
                ground_line = "directly above"
        else:
            ground_line = None

        if has_gps:
            coords = f"{sos['lat']:.6f}, {sos['lng']:.6f}"
            text = (
                f"📍 GPS COORDINATES AVAILABLE\n"
                f"{'─'*35}\n"
                f"Priority:      {pri_line}\n"
                f"{'─'*35}\n"
                f"Name:          {sos['name']}\n"
                f"Time:          {sos['time']}\n"
                f"Message:       {sos['message']}\n"
                f"Location:      {sos['location']}\n"
                f"Coords.:       {coords}\n"
                f"{'─'*35}\n"
                f"LoRa Signal:   RSSI {sos['rssi']} / SNR {sos['snr']}\n"
                f"Drone<->you:   {slant_line}   (LoRa slant range)\n"
            )
            if ground_line:
                text += f"  ground:      {ground_line}  (alt={alt:.0f}m)\n"
            text += self._victim_line(sos)
        else:
            text = (
                f"📡 NO GPS — DISTANCE ESTIMATION\n"
                f"{'─'*35}\n"
                f"Priority:      {pri_line}\n"
                f"{'─'*35}\n"
                f"Name:          {sos['name']}\n"
                f"Time:          {sos['time']}\n"
                f"Message:       {sos['message']}\n"
                f"Location:      {sos['location']}\n"
                f"{'─'*35}\n"
                f"LoRa Signal:   RSSI {sos['rssi']} / SNR {sos['snr']}\n"
                f"Drone<->you:   {slant_line}   (LoRa slant range)\n"
            )
            if ground_line:
                text += f"  ground:      {ground_line}  (alt={alt:.0f}m)\n"
            text += self._victim_line(sos)
            text += (
                f"Victim within: ~100 m of drone (WiFi range)\n"
                f"{'─'*35}\n"
                f"➜ Rings on map (red=near, yellow=far)"
            )
        self.detail.config(state="normal")
        self.detail.delete("1.0", "end")
        self.detail.insert("1.0", text)
        self.detail.config(state="disabled")


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 55)
    print("RescueNet — Rescuer Station (offline)")
    print("=" * 55)
    try:
        ser = init_lora()
    except Exception as e:
        print(f"✗ LoRa connection failed: {e}")
        return

    threading.Thread(target=lora_listen_thread, args=(ser,), daemon=True).start()

    root = tk.Tk()
    RescueNetApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
