# RescueNet

**A portable LoRa system that reaches unmodified smartphones with no app,
no account and no surviving infrastructure — for search and rescue.**

RescueNet repurposes offensive wireless techniques (a rogue access point, DNS
hijacking and captive-portal redirection) into a humanitarian channel. A ~249 g
portable Raspberry Pi payload, placed on an elevated fixed point (it was not flown
and no airborne capability is claimed), broadcasts an open Wi-Fi network; any phone that joins is automatically shown a
distress form through the operating system's own captive-portal detection. The
report is compacted, protected with AES-128-GCM, and relayed over an 868 MHz LoRa
link to a fully offline rescuer station that triages it by urgency and plots it
on maps preloaded before deployment. The whole chain runs without Internet in the
field.

This repository contains the source code, the labelled triage corpus and the
field-measurement data supporting the paper:

> R. Katramados, M. Iatrou, C. Liambas. *Ethical Hacking Methods for Search and
> Rescue: A Portable LoRa System with Authenticated Encryption and
> Machine-Learning Triage.* Submitted to *Information* (MDPI), Special Issue
> "AI-Driven Information Analytics for Cybersecurity and Privacy", 2026.

> **Status:** under peer review. A DOI will be added here once assigned by the
> publisher.

## Repository layout

```
hub/        Portable payload (Raspberry Pi 4): open AP, captive portal,
            pack → AES-128-GCM → LoRa transmit.  See hub/README.md
rescuer/    Offline rescuer station (laptop): LoRa receive → verify → decrypt →
            unpack → triage → offline map.  See rescuer/README.md
field_data/ Field measurements behind Tables 5, 10, 11 and 16 (CSV).
```

The two folders are self-contained. The transport/helper files
(`compact_payload.py`, `crypto_lora.py`, `crypto_lora_v1.py`, `distance_model.py`,
`download_offline_maps.py`, `lora_at.py`) appear in **both** folders and are kept byte-for-byte
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

Keys (transport version 2: replay protection and per-mission keys). The master
key stays on the base station (rescuer laptop) and is **never** copied to a hub:

```bash
cd rescuer
python3 crypto_lora.py genkey               # once: master key rescuenet.key (base station only)
python3 crypto_lora.py newmission --hub 0   # per mission: writes mission_<id>_hub0.key
#   copy mission_<id>_hub0.key to hub/ as mission.key, then delete the copy here and on the USB stick
python3 crypto_lora.py closemission <id>    # after the mission: its frames are refused
python3 crypto_lora.py status               # what is on this machine
```

Check the radio on each machine (prints the settings the module is actually
using; a setting the firmware rejects is reported, not assumed):

```bash
python3 lora_at.py                  # active address, network, band, SF/BW/CR/preamble, power
python3 lora_at.py --try 9,7,1,12   # does this module accept the requested AT+PARAMETER?
```

Run:

```bash
# hub (needs a monitor-mode Wi-Fi adapter and root)
cd hub && sudo ./run_complete_lora.sh

# rescuer
cd rescuer && python3 download_offline_maps.py   # once, online, for your area
cd rescuer && python3 rescuer_receiver_en.py
```

`crypto_lora_v1.py` is version 1 of the transport (one static pre-shared key, no
replay protection). It was used for all field measurements of the paper and is
kept only to reproduce that frame format; version-2 receivers reject version-1 frames.

## Reproduce the paper results

No radio and no network required. Scripts in `rescuer/eval/` import
`training_data.py` from `rescuer/`, so keep the folder structure.

| Paper | Command |
|---|---|
| Table 3, Table C1 | airtime from Appendix C (also printed by `rescuer/eval/test_compact_payload.py`) |
| Table 4 | `cd rescuer/eval && python3 test_compact_payload.py` |
| Table 7 and Section 3.3 statistics | `cd rescuer && python3 eval_triage.py` |
| Table 8, Figure 6 | `cd rescuer/eval && python3 evaluate.py && python3 plot_cm.py` |
| Table 9, Figure 7 | `cd rescuer/eval && python3 compare_models.py && python3 plot_revision.py` |
| Figure 8 and Section 3.4 | `cd rescuer && python3 queue_sim.py --plot` |
| Figure 10 | `cd rescuer/eval && python3 plot_revision.py` (values inline, identical to `field_data/table10_*.csv` and `table11_*.csv`) |
| Table 17 | `cd hub && python3 test_crypto_v2.py` (temporary folders; nothing on the machine is changed) |
| Tables 13–15, Figure 12 | see External validation below |

Timing figures (Table 9, Table 17) depend on the machine and vary slightly between runs.

## External validation (paper Sections 2.9 and 3.7)

The 200-message corpus is synthetic and shares its author with the tier
definitions and the lexicon, so its figures are internal. The scripts below test
the **released, frozen** configuration on independent, human-labelled crisis
messages and retrain the same pipeline on real data. The third-party data are
**not** redistributed here; download them from the sources below and pass the
folders on the command line.

```bash
# Run from inside rescuer/: the scripts import eval_triage.py, priority_classifier.py
# and training_data.py from the same folder, so copy the whole folder, not one file.
cd rescuer
python3 eval_crisisbench.py    --data /path/to/all_data_en       # Table 13
python3 eval_crisisbench_v2.py --data /path/to/all_data_en       # Tables 14-15
python3 plot_cb.py                                                # Figure 12
python3 eval_external.py   --appen /path/to/disaster_response --sms /path/to/spam.tsv
python3 train_external.py  --drm   /path/to/disaster_response --sms /path/to/spam.csv
```

| Collection | Used for | Source |
|---|---|---|
| CrisisBench (English, humanitarian task; includes CrisisLexT6, CrisisLexT26, CrisisNLP) | main external test (`eval_crisisbench.py`) | Alam et al., ICWSM 2021, https://crisisnlp.qcri.org/crisis_datasets_benchmarks |
| Disaster Response Messages (direct genre, CC BY 4.0) | first-person-style messages (`eval_external.py`, `train_external.py`) | R. Munro, https://github.com/rmunro/disaster_response_messages |
| SMS Spam Collection (CC BY 4.0) | non-emergency reference | Almeida et al., DocEng 2011, https://doi.org/10.24432/C5CC84 |
| CrisisLex T6 / T26 | components of CrisisBench | https://crisislex.org/data-collections.html |

Limits: the collections are English and mostly third-party tweets, the mapping
of their labels to urgency is ours, and the retrained model is binary (it does
not replace the four-tier backends). Reference outputs: `external_validation_crisisbench_results.txt`, `external_validation_results.txt`, `training_external_results.txt`.

## Data

- `rescuer/training_data.py` — the 200-message synthetic triage corpus (50 per
  class), LLM-generated from author-written tier definitions and labelled by the
  author (paper Section 2.5). It is balanced and synthetic; the absolute triage
  figures are an upper bound on a controlled distribution, not a field result.
- `field_data/` — the field measurements behind Tables 5, 10, 11 and 16:
  link quality (RSSI/SNR), distance, assigned priority and client-device results.
  Absolute GPS coordinates and device identifiers are withheld for privacy.

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
the paper (Sections 4.5–4.6). Version 2 of the transport adds replay protection
and per-mission keys, verified in software (Table 17) but not yet over the radio.
Still open: the open Wi-Fi leg between the phone and the hub, the self-signed
certificate, fabricated reports from anyone within Wi-Fi range, impersonation of
the hub, and jamming. Do not rely on it as a production safety system.

## Not included

Secrets and per-deployment state are never committed (see `.gitignore`): the
master key `rescuenet.key`, mission keys (`mission.key`, `mission_*_hub*.key`),
the counter and replay state files, the TLS `cert.pem`/`key.pem`, the trained
model `priority_model.pkl`, the offline tile cache `rescuenet_tiles.db`, and the
`emergency_data/` report log.

## License

Released under the **PolyForm Noncommercial License 1.0.0** (see [`LICENSE`](LICENSE)).
You may read, run, modify and share the code for any **noncommercial** purpose —
including research, study, education and use by public bodies and charities.
Commercial use requires a separate licence from the authors.

Required Notice: Copyright (c) 2026 R. Katramados, M. Iatrou, C. Liambas.

The system described here is the subject of a patent application filed with the
Hellenic Industrial Property Organisation (OBI) (application no. 18638, under
examination); the noncommercial licence above does not grant rights for
commercial exploitation.

## How to cite

R. Katramados, M. Iatrou, C. Liambas. *Ethical Hacking Methods for Search and
Rescue: A Portable LoRa System with Authenticated Encryption and
Machine-Learning Triage.* *Information* (MDPI), 2026. (DOI to be added.)

## Contact

Rafail Katramados (corresponding author) — raf.katramados@gmail.com
