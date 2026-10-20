# Field measurement data

Data supporting Tables 4 and 6 and Figure 7 of the paper. All reports were
received at the rescuer station over the encrypted 868 MHz LoRa link
(SF12, 125 kHz, CR 4/5, 20 dBm) and accepted only after GCM tag verification.

| File | Content |
|---|---|
| `table4_short_range_session.csv` | The nine-message short-range session (Table 4): message as received, whether a GPS fix was carried, RSSI/SNR at the rescuer station, priority assigned by the rule tier and the matched keyword. |
| `table6_elevated_los_series.csv` | The elevated line-of-sight series (Table 6) and the earlier 2807 m deployment (Figure 7): true distance computed from the browser GPS fix and the station position, RSSI/SNR, assigned priority and matched keyword. |

Each row is one received frame. Absolute GPS coordinates of the sending
device and of the rescuer station are withheld for privacy; distances were
computed from them before release. All distress messages were typed by the
corresponding author.
