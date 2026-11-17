# Field measurement data

Data behind the field results of the paper (Tables 5, 10, 11 and 16, Figures 9 and 10).
Every report was received at the rescuer station over the encrypted 868 MHz LoRa
link (SF9, 125 kHz, CR 4/5, 12-symbol preamble, 20 dBm, version-1 frame format) and accepted only
after GCM tag verification.

| File | Paper | Content |
|---|---|---|
| `table5_short_range_session.csv` | Table 5, Figure 5 | The nine-message short-range session: message as received, whether a GPS fix was carried, RSSI/SNR at the rescuer station, priority assigned by the rule tier and the matched keyword. |
| `table10_elevated_series.csv` | Table 10, Figure 9 | The elevated open-terrain series and the earlier 2807 m deployment: distance computed from the browser GPS fix and the station position, RSSI/SNR, assigned priority and matched keyword. Line of sight was not verified for each path. |
| `table11_link_tests.csv` | Table 11, Figure 10 | Repeated-delivery test (30 reports, about 5 m; summary values) and ground-level test (hub in a vehicle, one report from each of eight positions, 18 m to 3.45 km). |
| `table11a_repeated_delivery_reports.csv` | Table 11 (A), Table 6 | The 30 reports of the repeated-delivery test, one row each: time received, RSSI and priority assigned by the rule tier. SNR was not logged per report. Labels S18 and S21 were not sent. |
| `radio_readback_2026-11-14.txt` | Section 2.7, Table 2 | Settings read back from the hub module, and its answer to the spreading-factor-12 command. |
| `table16_client_devices.csv` | Table 16 | Captive-portal compatibility on six client devices (mobile data disabled), and the two failure-path trials on one device. |

Each row of the per-report files is one received frame. Absolute GPS coordinates
of the sending device and of the rescuer station are withheld for privacy;
distances were computed from them before release. No device identifiers
(IMEI, serial numbers, MAC addresses) are included. All distress messages were
typed by the corresponding author.
