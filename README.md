# RescueNet

**A drone-portable LoRa system that reaches unmodified smartphones with no app,
no account and no surviving infrastructure — for search and rescue.**

RescueNet repurposes offensive wireless techniques (a rogue access point, DNS
hijacking and captive-portal redirection) into a humanitarian channel. A ~249 g
Raspberry Pi payload, carried by a UAV or placed on an elevated fixed point,
broadcasts an open Wi-Fi network; any phone that joins is automatically shown a
distress form through the operating system's own captive-portal detection. The
report is compacted, protected with AES-128-GCM, and relayed over an 868 MHz LoRa
link to a fully offline rescuer station that triages it by urgency and plots it
on maps preloaded before deployment. The whole chain runs without Internet in the
field.

This repository contains the source code, the labelled triage corpus and the
field-measurement data supporting the paper:

> R. Katramados, *Ethical Hacking Methods for Search and
> Rescue: A Drone-Portable LoRa System with Authenticated Encryption and
> Machine-Learning Triage.* Submitted to *Information* (MDPI), Special Issue
> "AI-Driven Information Analytics for Cybersecurity and Privacy", 2026.

> **Status:** under peer review. A DOI will be added here once assigned by the
> publisher.

## Repository layout

```
hub/        Drone-portable payload (Raspberry Pi 4): open AP, captive portal,
            pack → AES-128-GCM → LoRa transmit.  See hub/README.md
rescuer/    Offline rescuer station (laptop): LoRa receive → verify → decrypt →
            unpack → triage → offline map.  See rescuer/README.md
field_data/ Field measurements behind Tables 4 and 6 and Figure 7 (CSV).
```

The two folders are self-contained. The four transport/helper files
(`compact_payload.py`, `crypto_lora.py`, `distance_model.py`,
`download_offline_maps.py`) appear in **both** folders and are kept byte-for-byte
identical on purpose — the hub and the rescuer must agree exactly on the wire
format and share the same key.

## Quick start

Both machines:

```bash
sudo python3 -m pip install cryptography pyserial --break-system-packages
# on the rescuer also:
sudo python3 -m pip install scikit-learn tkintermapview --break-system-packages
sudo apt install python3-tk
```

Generate the shared key once, on the hub, and copy the **same** file to the
rescuer:

```bash
cd hub && python3 crypto_lora.py genkey      # writes rescuenet.key (mode 0600)
#   copy hub/rescuenet.key -> rescuer/rescuenet.key
```

Run:

```bash
# hub (needs a monitor-mode Wi-Fi adapter and root)
cd hub && sudo ./run_complete_lora.sh

# rescuer
cd rescuer && python3 download_offline_maps.py   # once, online, for your area
cd rescuer && python3 rescuer_receiver_en.py
```

## Reproduce the paper results

No radio and no network required:

```bash
cd rescuer
python3 eval_triage.py          # Table 5 and the Section 3.3 statistics
python3 queue_sim.py --plot     # Section 3.4 and Figure 6 (-> figure6_queue.png)
```

The airtime figures of Table 3 / Table A2 follow from the LoRa time-on-air
expression in Appendix C of the paper.

## Data

- `rescuer/training_data.py` — the 200-message synthetic triage corpus (50 per
  class), LLM-generated from author-written tier definitions and labelled by the
  author (paper Section 2.5). It is balanced and synthetic; the absolute triage
  figures are an upper bound on a controlled distribution, not a field result.
- `field_data/` — the field measurements behind Tables 4 and 6 and Figure 7:
  link quality (RSSI/SNR), distance and assigned priority per received frame.
  Absolute GPS coordinates from the trials are withheld for privacy.

## Responsible use

RescueNet is built from techniques (open rogue access point, DNS hijacking,
captive-portal redirection) that are **offensive** in any other context, and a
running node is indistinguishable at the radio layer from a hostile one.
Operating an open access point that intercepts and redirects nearby devices is
regulated or unlawful in many jurisdictions outside an authorised emergency or
research setting, and transmit power and duty on the 868 MHz band are subject to
national rules. Run it only:

- with explicit authorisation, in a controlled test or a declared emergency;
- under the coordination of the responsible civil-protection authority;
- within the radio regulations that apply where you operate.

The project is a research prototype. Its security limits are stated plainly in
the paper (Sections 4.5–4.6): there is **no replay protection**, and key
management uses a **single static pre-shared key** without rotation. Do not rely
on it as a production safety system without addressing those.

## Not included

Secrets and per-deployment state are never committed (see `.gitignore` in each
folder): the AES key `rescuenet.key`, the TLS `cert.pem`/`key.pem`, the trained
model `priority_model.pkl`, the offline tile cache `rescuenet_tiles.db`, and the
`emergency_data/` report log.

## License

Released under the **PolyForm Noncommercial License 1.0.0** (see [`LICENSE`](LICENSE)).
You may read, run, modify and share the code for any **noncommercial** purpose —
including research, study, education and use by public bodies and charities.
Commercial use requires a separate licence from the authors.

Required Notice: Copyright (c) 2026 R. Katramados, M. Iatrou, C. Liampas.

The system described here is also the subject of a Hellenic Industrial Property
Organisation (OBI) patent and utility-model certificate; the noncommercial
licence above does not grant rights for commercial exploitation.

## How to cite

R. Katramados, M. Iatrou, C. Liampas. *Ethical Hacking Methods for Search and
Rescue: A Drone-Portable LoRa System with Authenticated Encryption and
Machine-Learning Triage.* *Information* (MDPI), 2026. (DOI to be added.)

## Contact

Rafail Katramados (corresponding author) — raf.katramados@gmail.com
