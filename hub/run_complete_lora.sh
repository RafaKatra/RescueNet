#!/bin/bash
# ==========================================================
#  Rescue WiFi Portal with LoRa v1
#  Developer: Rafail Katramados
#  Description: Startup script for initializing the Rescue WiFi Drone
#               communication portal using LoRa connectivity.
#  Version: 1.0
#  Date: $(date +"%Y-%m-%d")

echo "==============================================="
echo "      ⛑    Rescue WiFi Portal with LoRa v1 ⛑   "
echo "-----------------------------------------------"
echo "        Developer: Rafail Katramados"
echo "        Starting system initialization..."
echo "==============================================="
echo ""

# ==========================================================
#  ΑΠΕΝΕΡΓΟΠΟΙΗΣΗ SLEEP / SCREEN BLANKING / POWER-SAVE
#  Ώστε το Kali να ΜΗΝ πέφτει σε αδράνεια και να μη σβήνουν λειτουργίες.
# ==========================================================
echo "🔌 Απενεργοποίηση sleep/screensaver/power-save..."
# Suspend/hibernate σε επίπεδο συστήματος (μόνιμο· αναιρείται με systemctl unmask)
sudo systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null
# Console blanking (TTY)
sudo setterm -blank 0 -powersave off -powerdown 0 2>/dev/null || true
setterm -blank 0 -powersave off 2>/dev/null || true
# X screensaver/DPMS (αν τρέχει γραφικό περιβάλλον)
if command -v xset >/dev/null 2>&1; then
    xset s off 2>/dev/null; xset -dpms 2>/dev/null; xset s noblank 2>/dev/null
fi
# systemd-logind: αγνόησε idle/lid (best effort)
sudo mkdir -p /etc/systemd/logind.conf.d 2>/dev/null
echo -e "[Login]\nIdleAction=ignore\nHandleLidSwitch=ignore" | sudo tee /etc/systemd/logind.conf.d/nosleep.conf >/dev/null 2>&1

# ==========================================================
#  ΑΥΤΟΜΑΤΟΣ ΕΝΤΟΠΙΣΜΟΣ WiFi ADAPTER (wlan0 / wlan1 -> σωστό mon)
#  ΧΕΙΡΟΚΙΝΗΤΗ ΠΑΡΑΚΑΜΨΗ: βάλε π.χ. FORCE_WIFI_IFACE="wlan1" για να μη γίνει auto.
# ==========================================================
FORCE_WIFI_IFACE=""          # άφησέ το κενό για auto-detect, ή βάλε "wlan1"/"wlan0"
AP_CHANNEL=1                 # κανάλι AP. 1/6/11 επιτρέπονται ΠΑΝΤΟΥ. Το 12/13 θέλει σωστό regdomain.

# --- Καθάρισμα προηγούμενου run: διεργασίες + επαναφορά monitor σε managed ---
# (Αλλιώς ο adapter μένει "wlan0mon" και το auto-detect μπερδεύεται.)
sudo killall airbase-ng dnsmasq 2>/dev/null
sudo pkill -f emergency_sos_lora 2>/dev/null
sudo pkill -f captive_portal 2>/dev/null
sudo fuser -k 80/tcp 443/tcp 2>/dev/null
for d in /sys/class/net/*/phy80211; do
    [ -e "$d" ] || continue
    ifc=$(basename "$(dirname "$d")")
    if iw dev "$ifc" info 2>/dev/null | grep -q "type monitor"; then
        echo "   (επαναφορά $ifc: monitor -> managed)"
        sudo airmon-ng stop "$ifc" >/dev/null 2>&1
    fi
done
sleep 2

echo "🔎 Διαθέσιμοι ασύρματοι adapters:"
for d in /sys/class/net/*/phy80211; do
    [ -e "$d" ] || continue
    ifc=$(basename "$(dirname "$d")")
    drv=$(basename "$(readlink -f "/sys/class/net/$ifc/device/driver" 2>/dev/null)" 2>/dev/null)
    echo "   - $ifc  (driver: ${drv:-?})"
done

detect_wifi_iface() {
    # 1) Προτίμηση στον εξωτερικό Atheros (ath9k_htc = AR9271)
    for d in /sys/class/net/*/phy80211; do
        [ -e "$d" ] || continue
        ifc=$(basename "$(dirname "$d")")
        drv=$(basename "$(readlink -f "/sys/class/net/$ifc/device/driver" 2>/dev/null)" 2>/dev/null)
        [ "$drv" = "ath9k_htc" ] && { echo "$ifc"; return; }
    done
    # 2) Οποιοσδήποτε ασύρματος ΕΚΤΟΣ από το ενσωματωμένο Broadcom του Pi
    for d in /sys/class/net/*/phy80211; do
        [ -e "$d" ] || continue
        ifc=$(basename "$(dirname "$d")")
        drv=$(basename "$(readlink -f "/sys/class/net/$ifc/device/driver" 2>/dev/null)" 2>/dev/null)
        [ -n "$drv" ] && [ "$drv" != "brcmfmac" ] && [ "$drv" != "brcmsmac" ] && { echo "$ifc"; return; }
    done
    # 3) Ασφαλές fallback: το δουλεμένο wlan1 αν υπάρχει
    [ -d /sys/class/net/wlan1/phy80211 ] && { echo "wlan1"; return; }
    # 4) Τελευταία λύση: ο πρώτος ασύρματος
    for d in /sys/class/net/*/phy80211; do
        [ -e "$d" ] || continue
        basename "$(dirname "$d")"; return
    done
}

if [ -n "$FORCE_WIFI_IFACE" ]; then
    WIFI_IFACE="$FORCE_WIFI_IFACE"
    echo "📶 WiFi adapter (χειροκίνητα): $WIFI_IFACE"
else
    WIFI_IFACE="$(detect_wifi_iface)"
    echo "📶 WiFi adapter (auto): ${WIFI_IFACE:-<κανένας>}"
fi

if [ -z "$WIFI_IFACE" ] || [ ! -d "/sys/class/net/$WIFI_IFACE/phy80211" ]; then
    echo "✗ Δεν βρέθηκε έγκυρος ασύρματος adapter ($WIFI_IFACE). Έλεγξε το USB ή βάλε FORCE_WIFI_IFACE."
    exit 1
fi

# Clean
sudo killall python3 2>/dev/null
sudo killall dnsmasq 2>/dev/null
sudo killall airbase-ng 2>/dev/null
sudo fuser -k 80/tcp 443/tcp 53/udp 67/udp 2>/dev/null
sudo airmon-ng stop "${WIFI_IFACE}mon" 2>/dev/null
sudo airmon-ng stop wlan0mon 2>/dev/null
sudo airmon-ng stop wlan1mon 2>/dev/null
sudo airmon-ng stop mon0 2>/dev/null
sleep 2

# Τρέξε από τον φάκελο ΟΠΟΥ βρίσκεται ΑΥΤΟ το script, ώστε να χρησιμοποιεί
# ΤΑ ΔΙΚΑ ΣΟΥ αρχεία (π.χ. ~/Desktop/rescue_lora_08-2026) και ΟΧΙ παλιά στο /opt.
cd "$(dirname "$(readlink -f "$0")")" || cd /opt/emergency_sos_wifi
echo "📂 Φάκελος εργασίας: $(pwd)"

# Create SSL if needed
if [ ! -f cert.pem ]; then
    echo "Creating SSL certificates..."
    openssl req -x509 -newkey rsa:2048 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=10.20.0.1"
fi

# Create emergency_data directory
mkdir -p emergency_data

# Start monitor mode
echo "📡 Starting monitor mode..."
# Regulatory domain -> Ελλάδα: ξεκλειδώνει όλα τα κανάλια EU (12/13 χωρίς no-IR)
sudo iw reg set GR 2>/dev/null
sudo airmon-ng check kill

# Αν ο adapter είναι ΗΔΗ σε monitor, χρησιμοποίησέ τον ως έχει (μη τον σπάσεις).
if iw dev "$WIFI_IFACE" info 2>/dev/null | grep -q "type monitor"; then
    MON_IFACE="$WIFI_IFACE"
    echo "   (ο $WIFI_IFACE είναι ήδη σε monitor — χρήση ως έχει)"
else
    sudo airmon-ng start "$WIFI_IFACE" >/dev/null 2>&1
    MON_IFACE=""
fi

# Εντοπισμός του ΠΡΑΓΜΑΤΙΚΟΥ monitor interface μέσω iw dev (πιο αξιόπιστο)
if [ -z "$MON_IFACE" ]; then
    MON_IFACE=$(iw dev 2>/dev/null | awk '/Interface/{i=$2} /type monitor/{print i; exit}')
fi
# Fallback σε γνωστά ονόματα
if [ -z "$MON_IFACE" ]; then
    for cand in "${WIFI_IFACE}mon" mon0 wlan0mon wlan1mon; do
        [ -d "/sys/class/net/$cand" ] && MON_IFACE="$cand" && break
    done
fi
if [ -z "$MON_IFACE" ]; then
    echo "✗ Δεν εντοπίστηκε monitor interface."
    iw dev 2>/dev/null | grep -E 'Interface|type'
    exit 1
fi
echo "📡 Monitor interface: $MON_IFACE"

# Create AP
echo "📶 Creating Access Point (κανάλι $AP_CHANNEL)..."
sudo airbase-ng -e "SOS_WIFI_LoRa" -c "$AP_CHANNEL" "$MON_IFACE" &
sleep 5

# Επαλήθευση ότι το AP (at0) δημιουργήθηκε — αλλιώς διαγνωστικά
if [ ! -d /sys/class/net/at0 ]; then
    echo "✗ ΤΟ AP ΔΕΝ ΔΗΜΙΟΥΡΓΗΘΗΚΕ (δεν υπάρχει at0)."
    echo "  Πιθανό αίτιο: λάθος adapter σε monitor, ή το airbase-ng απέτυχε."
    echo "  --- Διαγνωστικά ---"
    echo "  WIFI_IFACE=$WIFI_IFACE  MON_IFACE=$MON_IFACE"
    iw dev 2>/dev/null | grep -E 'Interface|type'
    echo "  Δοκίμασε: βάλε FORCE_WIFI_IFACE=\"wlan1\" (ή wlan0) στην αρχή του script."
    echo "  -------------------"
else
    echo "✓ AP ενεργό: at0 (SSID: SOS_WIFI_LoRa, κανάλι $AP_CHANNEL)"
fi

# Configure network
echo "🌐 Configuring network..."
sudo ifconfig at0 up
sudo ifconfig at0 10.20.0.1 netmask 255.255.255.0

# DNS with captive portal
echo "🛜 Starting DNS with captive portal..."
cat > /tmp/dns.conf << 'EOF'
interface=at0
bind-interfaces
dhcp-authoritative
dhcp-range=10.20.0.50,10.20.0.250,12h
dhcp-option=3,10.20.0.1
dhcp-option=6,10.20.0.1

# Force ALL domains to our server
address=/#/10.20.0.1

# Specific captive portal domains
address=/connectivitycheck.gstatic.com/10.20.0.1
address=/www.gstatic.com/10.20.0.1
address=/connectivitycheck.android.com/10.20.0.1
address=/clients3.google.com/10.20.0.1
address=/clients.l.google.com/10.20.0.1

# Apple
address=/captive.apple.com/10.20.0.1
address=/www.apple.com/10.20.0.1

# Microsoft
address=/www.msftconnecttest.com/10.20.0.1
address=/www.msftncsi.com/10.20.0.1

# Firefox
address=/detectportal.firefox.com/10.20.0.1

log-queries
EOF

# Ελευθέρωσε 53/67 (αλλιώς dnsmasq: "Address already in use" -> ΚΑΝΕΝΑ DHCP)
sudo systemctl stop systemd-resolved 2>/dev/null
sudo killall dnsmasq 2>/dev/null
sudo fuser -k 53/udp 67/udp 2>/dev/null
sleep 1

sudo dnsmasq -C /tmp/dns.conf &
sleep 2
# Επαλήθευση ότι το dnsmasq ζει (αλλιώς δεν δίνεται IP -> «συνδέεται αλλά δεν μπαίνει»)
if ! pgrep -x dnsmasq >/dev/null; then
    echo "⚠️  Το dnsmasq ΔΕΝ ξεκίνησε — έλεγξε θύρα 53/67. Χωρίς αυτό δεν δίνεται DHCP."
else
    echo "✓ dnsmasq ενεργό (DHCP + DNS)"
fi

# Firewall for captive portal
echo "🔥 Setting firewall for captive portal..."
# Κανένα forwarding: τα θύματα δεν δρομολογούνται πουθενά πέρα από το hub
sudo sysctl -w net.ipv4.ip_forward=0 2>/dev/null

# Καθαρισμός
sudo iptables -F
sudo iptables -t nat -F
sudo iptables -t mangle -F

# ACCEPT: DNS, DHCP, HTTP, HTTPS
sudo iptables -A INPUT -i at0 -p udp --dport 53 -j ACCEPT
sudo iptables -A INPUT -i at0 -p tcp --dport 53 -j ACCEPT
sudo iptables -A INPUT -i at0 -p udp --dport 67:68 -j ACCEPT
sudo iptables -A INPUT -i at0 -p tcp --dport 80 -j ACCEPT
sudo iptables -A INPUT -i at0 -p tcp --dport 443 -j ACCEPT
# Οτιδήποτε άλλο από το δίκτυο των θυμάτων (π.χ. SSH 22) απορρίπτεται.
# Μόνο στο at0 — οι άλλες διεπαφές του operator (eth0/wlan0) δεν επηρεάζονται.
sudo iptables -A INPUT -i at0 -j DROP
sudo iptables -A FORWARD -i at0 -j DROP

# Εξαναγκασμός DNS: ακόμη κι αν η συσκευή χρησιμοποιεί 8.8.8.8, πάει στο δικό μας dnsmasq
sudo iptables -t nat -A PREROUTING -i at0 -p udp --dport 53 -j DNAT --to-destination 10.20.0.1
sudo iptables -t nat -A PREROUTING -i at0 -p tcp --dport 53 -j DNAT --to-destination 10.20.0.1

# HTTP -> portal (ΟΧΙ redirect στο 443 — αυτό ΣΚΟΤΩΝΕ το captive-detection auto-open)
sudo iptables -t nat -A PREROUTING -i at0 -p tcp --dport 80 -j DNAT --to-destination 10.20.0.1:80

echo "✓ iptables: DNS forced + HTTP→portal, όλα τα άλλα από at0 -> DROP"


# (Αφαιρέθηκε το captive_portal.py — το emergency_sos_lora.py κάνει ήδη το captive
#  portal μέσω των routes /captive και /generate_204. Το να τρέχουν ΚΑΙ ΤΑ ΔΥΟ
#  προκαλούσε σύγκρουση στη θύρα 80.)
# (Αφαιρέθηκε επίσης το χαλασμένο "sleep 2sudo iptables -F ..." που ΕΣΒΗΝΕ τους
#  κανόνες iptables του captive portal αμέσως μετά που μπαίνανε.)


# Start Emergency SOS System με LoRa
echo "⛑ Starting Emergency SOS Portal με LoRa..."
sudo python3 emergency_sos_lora.py &
sleep 3

echo ""
echo "=========================================="
echo "✅ SYSTEM READY!"
echo "=========================================="

echo "📱 WiFi SSID: SOS_WIFI_LoRa"
echo "🌐 Portal: https://10.20.0.1/ (HTTP: 10.20.0.1)"
echo "📡 LoRa Hub: Ready for broadcasts"
echo ""
echo " Rescuer Setup Instructions:"
echo " For technical issues, contact the operator."
echo ""
echo "=========================================="
echo ""

# Keep the system running
while true; do
    sleep 5
    
    # Check if processes are still running
    if ! pgrep -f "python3 emergency_sos_lora.py" > /dev/null; then
        echo "⚠️ Emergency SOS process died, restarting..."
        sudo python3 emergency_sos_lora.py &
    fi
    
    if ! pgrep -f "dnsmasq" > /dev/null; then
        echo "⚠️ DNS process died, restarting..."
        sudo dnsmasq -C /tmp/dns.conf &
    fi
done
