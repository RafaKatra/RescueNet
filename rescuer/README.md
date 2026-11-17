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
| `eval_triage.py` | Regenerates **Table 7** and the Section 3.3 statistics. |
| `queue_sim.py` | Regenerates **Figure 8** and the Section 3.4 delay figures. |
| `eval_crisisbench.py`, `eval_crisisbench_v2.py`, `plot_cb.py` | External validation on CrisisBench (Tables 13–15, Figure 12). |
| `eval_external.py`, `train_external.py` | Disaster Response Messages and SMS Spam Collection (Section 3.7). |
| `eval/` | Scripts for Tables 4, 8 and 9 and Figures 6, 7 and 10 (see the main README). |
| `compact_payload.py` | Report compaction (shared, identical to hub copy). |
| `crypto_lora.py` | AES-128-GCM transport, version 2 (shared, identical to hub copy). Also issues and closes mission keys. |
| `lora_at.py` | AT helper and radio diagnostic for the RYLR998 (shared, identical to hub copy). |
| `crypto_lora_v1.py` | Version 1, used for the field measurements; kept for reproducibility only. |
| `distance_model.py` | RSSI→distance log-distance model (shared, identical to hub copy). |
| `download_offline_maps.py` | One-time offline-tile pre-loader (edit the area, run once online). |

The shared files are **byte-for-byte identical** to the copies in `hub/`.

## First-time setup
```bash
sudo python3 -m pip install cryptography pyserial scikit-learn tkintermapview --break-system-packages
sudo apt install python3-tk
python3 crypto_lora.py genkey               # once: master key (stays on this machine only)
python3 crypto_lora.py newmission --hub 0   # per mission: key for hub 0 -> copy to the hub as mission.key
python3 download_offline_maps.py          # once, online; edit the area box first
```

## Run (field)
```bash
python3 rescuer_receiver_en.py
```

## Reproduce the paper results (no hardware, no network)
```bash
python3 eval_triage.py          # Table 7 + Section 3.3
python3 queue_sim.py --plot     # Section 3.4 + Figure 8 (writes figure8_queue.png)
python3 priority_classifier.py train   # optional: trains the ML backend (priority_model.pkl)
```

## Never commit
`rescuenet.key`, `mission_*_hub*.key`, `missions_issued.json`, `replay_state.json`, `priority_model.pkl`, `rescuenet_tiles.db` — see `.gitignore`.
