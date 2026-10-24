#!/usr/bin/env python3
from flask import Flask, render_template_string, request, jsonify, redirect
from datetime import datetime
import json
import os
import glob
import serial
import time
from threading import Lock, Thread

app = Flask(__name__)

LORA_PORT = None                 # συμπληρώνεται ΑΥΤΟΜΑΤΑ από την ανίχνευση (βλ. detect_lora_port)
LORA_PORT_CANDIDATES = None      # None = auto (ttyUSB*/ttyACM*)· ή ρητά π.χ. ["/dev/ttyUSB0","/dev/ttyUSB1"]
BAUD_RATE = 115200
NETWORK_ID = 3
FREQUENCY = 868000000
POWER = 20

ser = None
sos_requests = []
sos_lock = Lock()
lora_lock = Lock()  # Serial port lock for threading safety

DATA_FILE = "emergency_data/sos_log.json"
os.makedirs("emergency_data", exist_ok=True)

if os.path.exists(DATA_FILE):
    try:
        with open(DATA_FILE, 'r') as f:
            sos_requests = json.load(f)
    except:
        pass

# ============================================================
# LORA FUNCTIONS - RescueNet Format
# ============================================================

def detect_lora_port():
    """
    Βρίσκει τη θύρα του LoRa δοκιμάζοντας AT σε κάθε υποψήφια (ttyUSB0, ttyUSB1, ... ,
    μετά ttyACM*). Επιστρέφει την πρώτη που απαντά +OK, ώστε να ΜΗΝ κολλάει σε λάθος
    θύρα. Αν καμία δεν απαντήσει αλλά υπάρχει θύρα, επιστρέφει την πρώτη (best effort).
    """
    if LORA_PORT_CANDIDATES:
        candidates = list(LORA_PORT_CANDIDATES)
    else:
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
                print(f"✓ LoRa εντοπίστηκε στη θύρα {port}")
                return port
        except Exception:
            continue
    print(f"⚠ Καμία θύρα δεν απάντησε σε AT — fallback στην {candidates[0]}")
    return candidates[0]


def init_lora():
    global ser, LORA_PORT
    try:
        LORA_PORT = detect_lora_port()
        if not LORA_PORT:
            print("✗ Δεν βρέθηκε καμία σειριακή θύρα LoRa (ttyUSB*/ttyACM*)")
            return False
        ser = serial.Serial(port=LORA_PORT, baudrate=BAUD_RATE, timeout=1)
        time.sleep(0.5)
        
        # Send AT Commands
        ser.write(b"AT\r\n")
        time.sleep(0.2)
        ser.write(b"AT+ADDRESS=0\r\n")
        time.sleep(0.2)
        ser.write(f"AT+NETWORKID={NETWORK_ID}\r\n".encode())
        time.sleep(0.2)
        ser.write(f"AT+BAND={FREQUENCY}\r\n".encode())
        time.sleep(0.2)
        ser.write(f"AT+CRFOP={POWER}\r\n".encode())
        time.sleep(0.2)
        ser.write(b"AT+PARAMETER=12,7,1,8\r\n")
        #SF=12 bw=7 cr=1 preamble=8
        time.sleep(0.2)
        print(f"✓ LoRa: {LORA_PORT}")
        print(f"✓ Address: 0 (HUB)")
        print(f"✓ Network: {NETWORK_ID}")
        print(f"✓ Frequency: {FREQUENCY/1000000} MHz")
        print(f"✓ Power: {POWER} dBm")
        
        return True
    except Exception as e:
        print(f"✗ LoRa error: {e}")
        return False

def broadcast_sos(sos_data):
    """Broadcast using RescueNet format (encrypted with AES-128-GCM)"""
    if not ser:
        return False
    with lora_lock:  # Prevent threading conflicts
        try:
            from compact_payload import pack
            from crypto_lora import encrypt

            message = pack(
                sos_data.get('name'),
                sos_data.get('message'),
                sos_data.get('location'),
                sos_data.get('lat'),
                sos_data.get('lng'),
                wifi_m=sos_data.get('wifi_m', 0),   # <-- απόσταση θύματος->hub
            )
            payload = encrypt(message)

            # Send via LoRa to address 1 (rescuer) — encrypted payload
            cmd = f"AT+SEND=1,{len(payload)},{payload}"
            ser.write((cmd + "\r\n").encode())
            time.sleep(0.2)
            response = ser.read(1000).decode('utf-8', errors='ignore')

            if "+OK" in response:
                print(f"✓ Broadcast SOS #{sos_data.get('id')}")
                print(f"  To: Rescuer station (Address 1)")
                return True
            else:
                print(f"✗ Broadcast failed — response: {response!r}")
                return False

        except Exception as e:
            print(f"✗ Error: {e}")
            return False
# ============================================================
# HTML PORTAL
# ============================================================

PORTAL_HTML = '''
<!DOCTYPE html>
<html lang="el">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>⛑ Emergency SOS</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 500px;
            width: 100%;
        }
        .header {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
            padding: 40px 30px;
            text-align: center;
        }
        .pulse { animation: pulse 2s infinite; font-size: 60px; }
        @keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.1); } }
        .form-container { padding: 30px; }
        .input-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 8px; font-weight: 600; color: #333; }
        input, textarea {
            width: 100%;
            padding: 12px;
            border: 2px solid #e5e5e5;
            border-radius: 10px;
            font-size: 16px;
        }
        textarea { min-height: 100px; }
        .btn {
            width: 100%;
            padding: 14px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-size: 16px;
            font-weight: bold;
            margin-bottom: 10px;
        }
        .btn-gps { background: #667eea; color: white; }
        .btn-submit { background: #f5576c; color: white; }
        .alert { padding: 15px; border-radius: 10px; margin-bottom: 20px; background: #d4edda; color: #155724; }
        .gps-status { padding: 12px; border-radius: 8px; margin: 10px 0; display: none; background: #d1ecf1; color: #0c5460; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="pulse">⛑</div>
            <h2>Emergency SOS Wifi</h2>
	   <h1>Stay Calm</h1>
	   <h3>Follow the instuctions carefully and rescuers will soon receive your information.</h3>	

            <p>LoRa Network by Rafail Katramados</p>

        </div>
        <div class="form-container">
            <div id="alert-box"></div>
            
            <!-- HTTPS GPS Notice -->
            <div class="https-notice" style="background: #e3f2fd; border: 2px solid #2196f3; border-radius: 12px; padding: 16px; margin-bottom: 20px;">
                <div style="display: flex; align-items: center; justify-content: center; gap: 10px; margin-bottom: 10px;">
                    <span style="font-size: 24px;">🔒</span>
                    <strong style="color: #1565c0; font-size: 15px;">Δεν εντοπίζεται το GPS;</strong>
                </div>
                <p style="color: #1976d2; font-size: 13px; margin: 8px 0;">
                    ΠΡΟΣΟΧΗ! Αν το GPS δεν λειτουργεί αυτόματα, χρειάζεται ασφαλής σύνδεση
                </p>
                <a href="https://10.20.0.1" target="_blank" 
                   style="display: inline-block; margin-top: 12px; padding: 12px 24px; 
                          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                          color: white; text-decoration: none; border-radius: 8px; 
                          font-weight: bold; font-size: 14px; 
                          box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
                          transition: transform 0.2s;"
                   onmouseover="this.style.transform='translateY(-2px)'"
                   onmouseout="this.style.transform='translateY(0)'">
                    🌍 Άνοιγμα Safe Mode Browser για GPS or type -> https://10.20.0.1
                </a>
                <div style="margin-top: 10px; padding: 8px; background: #fff3cd; border-radius: 6px;">
                    <small style="color: #856404; font-size: 11px;">
                        ⚠️ Θα εμφανιστεί προειδοποίηση ασφαλείας<br>
                        Πατήστε <strong>"Σύνθετες ρυθμίσεις"</strong> → <strong>"Συνέχεια"</strong>
                    </small>
                </div>
        <div class="form-container">
            <div id="alert-box"></div>
            
            <form id="sos-form">
                <div class="input-group">
                    <label>Name:</label>
                    <input type="text" id="name" required placeholder="Your name">
                </div>
                
                <div class="input-group">
                    <label>Emergency Message:</label>
                   <textarea id="message" required maxlength="80"
          placeholder="Describe your emergency..."
          oninput="updateCounter()"></textarea>
<small id="char-counter" style="color: #666; font-size: 12px;">80 characters left</small>
                </div>
                
                <div class="input-group">
                    <label>Location:</label>
                    <input type="text" id="location" placeholder="Your location">
                    <small style="color: #666; font-size: 12px;">
                        💡 GPS tip: Go outside, away from buildings/trees for accurate results
                    </small>
                </div>
                
                <button type="button" class="btn btn-gps" onclick="getLocation()">
                    🌍 Get GPS Location (Wait 30-60s)
                </button>
                
                <div id="gps-status" class="gps-status"></div>
                
                <button type="submit" class="btn btn-submit">
                    🚑 SEND SOS
                </button>
            </form>
        </div>
    </div>
    
    <script>
        let userCoordinates = null;

        function updateCounter() {
            const msg = document.getElementById('message');
            const counter = document.getElementById('char-counter');
            const left = 80 - msg.value.length;
            counter.textContent = left + ' characters left';
            counter.style.color = left < 15 ? '#f5576c' : '#666';
        }

        function getLocation() {
            const statusDiv = document.getElementById('gps-status');
            statusDiv.style.display = 'block';
            statusDiv.innerHTML = '📡 Getting GPS (this may take 30-60 seconds)...';
            
            if (navigator.geolocation) {
                // CRITICAL: Force real GPS, not WiFi/cell positioning
                const options = {
                    enableHighAccuracy: true,      // Force GPS satellite
                    timeout: 60000,                // 60 seconds timeout
                    maximumAge: 0                  // Don't use cached position
                };
                
                navigator.geolocation.getCurrentPosition(
                    (position) => {
                        const accuracy = position.coords.accuracy;
                        
                        // Reject if accuracy is worse than 500m (likely WiFi/cell, not GPS)
                        if (accuracy > 500) {
                            statusDiv.innerHTML = '⚠️ GPS accuracy too low (' + Math.round(accuracy) + 'm)<br>This is likely WiFi positioning, not real GPS.<br>Go outside and try again, or enter location manually.';
                            userCoordinates = null;
                            return;
                        }
                        
                        userCoordinates = {
                            lat: position.coords.latitude,
                            lng: position.coords.longitude
                        };
                        
                        let accuracyWarning = '';
                        if (accuracy > 100) {
                            accuracyWarning = '<br>⚠️ Moderate accuracy. Move to open area if possible.';
                        }
                        
                        statusDiv.innerHTML = '✅ GPS OK<br>Lat: ' + userCoordinates.lat.toFixed(6) + '<br>Lng: ' + userCoordinates.lng.toFixed(6) + '<br>Accuracy: ±' + Math.round(accuracy) + 'm' + accuracyWarning;
                    },
                    (error) => {
                        let errorMsg = 'GPS Error: ';
                        if (error.code === 1) errorMsg += 'Permission denied';
                        else if (error.code === 2) errorMsg += 'Position unavailable';
                        else if (error.code === 3) errorMsg += 'Timeout (try again in open area)';
                        
                        statusDiv.innerHTML = '⚠️ ' + errorMsg + '<br>Enter location manually.';
                    },
                    options  // Pass the options!
                );
            }
        }
        
        document.getElementById('sos-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const btn = document.querySelector('.btn-submit');
            btn.disabled = true;
            btn.innerHTML = 'Sending...';
            
            const data = {
                name: document.getElementById('name').value,
                message: document.getElementById('message').value,
                location: document.getElementById('location').value,
                lat: userCoordinates ? userCoordinates.lat : 0,
                lng: userCoordinates ? userCoordinates.lng : 0
            };
            
            try {
                const response = await fetch('/submit_sos', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });
                
                const result = await response.json();
                if (result.success) {
                    document.getElementById('alert-box').innerHTML = '<div class="alert">✅ ' + result.message + '</div>';
                    document.getElementById('sos-form').reset();
                    userCoordinates = null;
                }
            } catch (error) {
                document.getElementById('alert-box').innerHTML = '<div class="alert">❌ Error sending SOS</div>';
            } finally {
                btn.disabled = false;
                btn.innerHTML = '🚑 SEND SOS';
            }
        });
    </script>
</body>
</html>
'''

# ============================================================
# ROUTES
# ============================================================

# ============================================================
# ΕΚΤΙΜΗΣΗ ΑΠΟΣΤΑΣΗΣ ΘΥΜΑΤΟΣ ΑΠΟ WiFi RSSI (drone -> θύμα)
# ============================================================
import subprocess as _sp

try:
    from distance_model import DistanceEstimator, WIFI_CALIBRATION as _CAL
    _wifi_est = DistanceEstimator(_CAL)
    _HAS_MODEL = True
    print(f"✓ Μοντέλο απόστασης: n={_wifi_est.n:.2f}, A={_wifi_est.A:.1f} dBm "
          f"({len(_CAL)} σημεία βαθμονόμησης)")
except ImportError:
    _HAS_MODEL = False
    print("⚠ distance_model.py δεν βρέθηκε — απόσταση μόνο ως RSSI")


# Τελευταία μετρημένη απόσταση θύματος->hub σε μέτρα (0 = άγνωστη).
_WIFI_LAST = {"m": 0}


def get_client_wifi_distance(client_ip):
    """
    Ρωτάει το AP (at0) για το WiFi RSSI του θύματος βάσει IP.
    Επιστρέφει (rssi_dBm, distance_string) ή (None, None).
    """
    try:
        # Βρες MAC από IP μέσω ARP table
        arp = _sp.run("cat /proc/net/arp", shell=True, capture_output=True, text=True).stdout
        mac = None
        for line in arp.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[0] == client_ip:
                mac = parts[3]
                break
        if not mac or mac == "00:00:00:00:00:00":
            return None, None

        # Βρες RSSI από station dump
        import re
        dump = _sp.run(f"iw dev at0 station get {mac}", shell=True,
                       capture_output=True, text=True).stdout
        m = re.search(r"signal:\s*(-?\d+)", dump)
        if not m:
            return None, None
        rssi = int(m.group(1))

        # Εκτίμηση απόστασης
        if _HAS_MODEL:
            r = _wifi_est.update(rssi)
            if r:
                d = r["distance_m"]
                lo, hi = r["min_m"], r["max_m"]
                _WIFI_LAST["m"] = d          # <-- κρατάμε τα μέτρα για το LoRa frame
                if d < 1000:
                    return rssi, f"~{d:.0f}m ({lo:.0f}–{hi:.0f}m)"
                return rssi, f"~{d/1000:.2f}km ({lo/1000:.2f}–{hi/1000:.2f}km)"
        return rssi, f"RSSI {rssi} dBm (μοντέλο μη διαθέσιμο)"
    except Exception:
        return None, None


@app.route('/')
def index():
    return render_template_string(PORTAL_HTML)

@app.route('/submit_sos', methods=['POST'])
def submit_sos():
    data = request.get_json(silent=True) or {}
    
    sos_entry = {
        'id': len(sos_requests) + 1,
        'timestamp': datetime.now().isoformat(),
        'name': data.get('name', 'Anonymous'),
        'message': data.get('message', ''),
        'location': data.get('location', ''),
        'lat': data.get('lat', 0),
        'lng': data.get('lng', 0),
        'ip_address': request.remote_addr,
        'status': 'pending'
    }
    
    with sos_lock:
        sos_requests.append(sos_entry)
        with open(DATA_FILE, 'w') as f:
            json.dump(sos_requests, f, indent=2)
    
    # Εκτίμηση απόστασης θύματος από WiFi RSSI (signal strength στο AP)
    _WIFI_LAST['m'] = 0
    wifi_rssi, wifi_dist = get_client_wifi_distance(sos_entry['ip_address'])
    sos_entry['wifi_m'] = _WIFI_LAST.get('m', 0)
    
    print(f"\n{'='*60}")
    print(f"🆘 SOS #{sos_entry['id']} from {sos_entry['name']}")
    print(f"   Μήνυμα:    {sos_entry['message']}")
    print(f"   Τοποθεσία: {sos_entry['location']}")
    has_gps = sos_entry['lat'] not in (None, 0, '0') and sos_entry['lng'] not in (None, 0, '0')
    if has_gps:
        print(f"   GPS:        {sos_entry['lat']}, {sos_entry['lng']}")
    else:
        print(f"   GPS:        ΔΕΝ ΥΠΑΡΧΕΙ")
    if wifi_rssi is not None:
        print(f"   WiFi σήμα:  {wifi_rssi} dBm -> θύμα {wifi_dist}")
    else:
        print(f"   WiFi σήμα:  δεν εντοπίστηκε (θύμα εντός εμβέλειας WiFi)")
    print(f"{'='*60}")
    
    # Broadcast via LoRa using RescueNet format
    broadcast_sos(sos_entry)
    
    return jsonify({
        'success': True,
        'id': sos_entry['id'],
        'message': f'SOS received - ID #{sos_entry["id"]}'
    })

@app.route('/captive')
@app.route('/generate_204')
@app.route('/gen_204')
def captive():
    # Android: μη-204 απάντηση (302) -> εμφανίζεται το «Σύνδεση στο δίκτυο»
    return redirect('/', code=302)

# Catch-all: ΚΑΘΕ άλλο URL επιστρέφει το portal. Χωρίς αυτό, τα captive-detection
# URLs (iOS hotspot-detect.html, Windows ncsi.txt/connecttest.txt, Firefox
# detectportal) έπαιρναν 404 και το portal ΔΕΝ άνοιγε αυτόματα.
@app.route('/<path:path>')
def catch_all(path):
    return render_template_string(PORTAL_HTML), 200

# ============================================================
# DUAL PORT SERVERS (HTTP + HTTPS)
# ============================================================

def run_http():
    """HTTP server on port 80"""
    # Ελευθέρωσε τη θύρα αν κάτι την κρατά (leftover instance)
    try:
        _sp.run("fuser -k 80/tcp", shell=True, capture_output=True, timeout=3)
        import time; time.sleep(0.5)
    except Exception:
        pass
    app.run(host='0.0.0.0', port=80, debug=False, threaded=True, use_reloader=False)

def run_https():
    """HTTPS server on port 443"""
    if os.path.exists('cert.pem') and os.path.exists('key.pem'):
        app.run(host='0.0.0.0', port=443, ssl_context=('cert.pem', 'key.pem'), 
                debug=False, threaded=True, use_reloader=False)
    else:
        print("⚠️  SSL certificates not found")

# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    print("="*60)
    print("🚑 EMERGENCY DRONE PORTAL")
    print("="*60)
    print()
    
    if not init_lora():
        print("✗ Failed to initialize LoRa")
        exit(1)
    
    print()
    print("✅ System Ready")
    print("📱 Portal: http://10.20.0.1")
    
    # Check for SSL certificates
    has_ssl = os.path.exists('cert.pem') and os.path.exists('key.pem')
    
    if has_ssl:
        print("🔒 Portal: https://10.20.0.1 (GPS enabled)")
        print()
        
        # Start HTTP in background thread
        http_thread = Thread(target=run_http, daemon=True)
        http_thread.start()
        print("✓ HTTP server started on port 80")
        
        # Start HTTPS in main thread (blocks)
        print("✓ HTTPS server starting on port 443...")
        run_https()
    else:
        print("⚠️  HTTPS not available (no SSL certificates)")
        print()
        
        # Run HTTP only
        run_http()
