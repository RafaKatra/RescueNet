# RescueNet — Hub (portable payload)

Runs on the Raspberry Pi 4 placed on an elevated fixed node (never flown; no airborne capability is claimed).
Raises the open Wi-Fi access point, serves the captive-portal distress form,
compacts and encrypts each report, and relays it over 868 MHz LoRa to the
rescuer station.

## Files
| File | Role |
|---|---|
| `run_complete_lora.sh` | Startup script: AP (airbase-ng), DHCP/DNS (dnsmasq), captive-portal firewall (iptables), then launches the portal. **Run this.** |
| `emergency_sos_lora.py` | Flask captive portal + LoRa sender (`broadcast_sos`: pack → encrypt → `AT+SEND`). |
| `compact_payload.py` | Report compaction (shared, identical to rescuer copy). |
| `crypto_lora.py` | AES-128-GCM transport, version 2: replay protection and per-mission keys (shared, identical to rescuer copy). |
| `crypto_lora_v1.py` | Version 1 (static pre-shared key), used for the field measurements; kept for reproducibility only. |
| `lora_at.py` | AT helper for the RYLR998: applies the radio settings, reads back the active ones, reports rejected commands; also a stand-alone diagnostic (shared). |
| `test_crypto_v2.py` | Software tests of version 2 (paper Table 17); runs in temporary folders. |
| `replay_demo.py` | Short demonstration of a rejected replayed frame. |
| `distance_model.py` | RSSI→distance log-distance model (shared, identical to rescuer copy). |
| `download_offline_maps.py` | One-time offline-tile pre-loader (shared helper). |

The shared files are **byte-for-byte identical** to the copies in
`rescuer/` on purpose: both ends must agree on the wire format and the key.

## First-time setup
```bash
sudo python3 -m pip install cryptography pyserial --break-system-packages
#   On the base station (rescuer laptop), per mission:
#     python3 crypto_lora.py newmission --hub 0
#   copy mission_<id>_hub0.key into this folder as mission.key.
#   The master key rescuenet.key stays on the base station and is NEVER copied here.
python3 crypto_lora.py status      # shows the mission and hub of this hub
```

## Run
```bash
sudo ./run_complete_lora.sh
```

## Never commit
`rescuenet.key`, `mission.key`, `mission_counter.json`, `cert.pem`, `key.pem`, `emergency_data/` — see `.gitignore`.
