# RescueNet — Rescuer station (offline laptop)

Runs on the responder's laptop. Receives LoRa reports, verifies the GCM tag,
decrypts and unpacks them, triages each message by urgency, estimates distance
from RSSI, and plots GPS-bearing reports on maps preloaded before deployment.
No internet is needed in the field.

## Files
| File | Role |
|---|---|
| `rescuer_receiver_en.py` | Receiver + Tk GUI (`parse_rcv`: decrypt → unpack → classify → distance → map). **Run this.** |
| `priority_classifier.py` | Triage: rule tier (default) + optional TF-IDF/LogReg ML backend. |
| `training_data.py` | 200-message synthetic triage corpus (50 per class, Section 2.5). |
| `eval_triage.py` | Regenerates **Table 5** and the Section 3.3 statistics. |
| `queue_sim.py` | Regenerates **Figure 6** and the Section 3.4 delay figures. |
| `compact_payload.py` | Report compaction (shared, identical to hub copy). |
| `crypto_lora.py` | AES-128-GCM transport (shared, identical to hub copy). |
| `distance_model.py` | RSSI→distance log-distance model (shared, identical to hub copy). |
| `download_offline_maps.py` | One-time offline-tile pre-loader (edit the area, run once online). |

The four shared files are **byte-for-byte identical** to the copies in `hub/`.

## First-time setup
```bash
sudo python3 -m pip install cryptography pyserial scikit-learn tkintermapview --break-system-packages
sudo apt install python3-tk
#   copy rescuenet.key from the hub machine into this folder
python3 download_offline_maps.py          # once, online; edit the area box first
```

## Run (field)
```bash
python3 rescuer_receiver_en.py
```

## Reproduce the paper results (no hardware, no network)
```bash
python3 eval_triage.py          # Table 5 + Section 3.3
python3 queue_sim.py --plot     # Section 3.4 + Figure 6 (writes figure6_queue.png)
python3 priority_classifier.py train   # optional: trains the ML backend (priority_model.pkl)
```

## Never commit
`rescuenet.key`, `priority_model.pkl`, `rescuenet_tiles.db` — see `.gitignore`.
