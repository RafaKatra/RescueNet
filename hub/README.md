# RescueNet — Hub (drone-portable payload)

Runs on the Raspberry Pi 4 carried by the UAV (or on the elevated fixed node).
Raises the open Wi-Fi access point, serves the captive-portal distress form,
compacts and encrypts each report, and relays it over 868 MHz LoRa to the
rescuer station.

## Files
| File | Role |
|---|---|
| `run_complete_lora.sh` | Startup script: AP (airbase-ng), DHCP/DNS (dnsmasq), captive-portal firewall (iptables), then launches the portal. **Run this.** |
| `emergency_sos_lora.py` | Flask captive portal + LoRa sender (`broadcast_sos`: pack → encrypt → `AT+SEND`). |
| `compact_payload.py` | Report compaction (shared, identical to rescuer copy). |
| `crypto_lora.py` | AES-128-GCM transport (shared, identical to rescuer copy). |
| `distance_model.py` | RSSI→distance log-distance model (shared, identical to rescuer copy). |
| `download_offline_maps.py` | One-time offline-tile pre-loader (shared helper). |

The four shared files are **byte-for-byte identical** to the copies in
`rescuer/` on purpose: both ends must agree on the wire format and the key.

## First-time setup (both machines)
```bash
sudo python3 -m pip install cryptography pyserial --break-system-packages
python3 crypto_lora.py genkey      # creates rescuenet.key (0600) — run ONCE
#   copy the SAME rescuenet.key to the rescuer machine
```

## Run
```bash
sudo ./run_complete_lora.sh
```

## Never commit
`rescuenet.key`, `cert.pem`, `key.pem`, `emergency_data/` — see `.gitignore`.
