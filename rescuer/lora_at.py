#!/usr/bin/env python3
"""
RescueNet - lora_at.py
======================
AT helper for the REYAX RYLR998 LoRa module. IDENTICAL file on hub and rescuer.

Why it exists: the module answers every AT command with +OK or +ERR=<n>.
A command that the module rejects (for example a spreading factor or preamble
outside what the firmware allows) leaves the PREVIOUS setting in force, so the
radio may run with parameters other than the ones requested. This helper sends
each command, reads the answer, and then asks the module which settings are
actually active, so the configuration that is reported is the one in use.

Use as a library:
    from lora_at import configure
    actual = configure(ser, address=0, network_id=3, band=868000000,
                       parameter="9,7,1,12", power=20)

Use as a diagnostic (prints the active settings, changes nothing):
    python3 lora_at.py                 # auto-detect port
    python3 lora_at.py /dev/ttyUSB0
    python3 lora_at.py --try 9,7,1,12  # also test whether the module accepts
                                       # this AT+PARAMETER value, then restore
"""
import glob
import sys
import time

BAUD_RATE = 115200

ERRORS = {
    "1": "no CR/LF at the end of the command",
    "2": "command does not start with AT",
    "4": "unknown command",
    "5": "data length does not match",
    "10": "TX over time",
    "12": "CRC error",
    "13": "TX data longer than 240 bytes",
    "14": "flash write failed",
    "15": "unknown failure",
    "17": "previous TX not completed",
    "18": "preamble value not allowed",
    "19": "RX failed, header error",
    "20": "smart-receive time setting not allowed",
}


def at(ser, cmd, timeout=1.5):
    """Send one AT command and return the module's answer (stripped text)."""
    try:
        ser.reset_input_buffer()
    except Exception:
        pass
    ser.write((cmd + "\r\n").encode())
    deadline = time.time() + timeout
    buf = ""
    while time.time() < deadline:
        chunk = ser.read(max(1, getattr(ser, "in_waiting", 0) or 1))
        if chunk:
            buf += chunk.decode("utf-8", errors="ignore")
            if "\n" in buf and ("+OK" in buf or "+ERR" in buf or "=" in buf):
                break
    return buf.strip()


def explain(resp):
    """Human-readable form of an answer."""
    if "+ERR=" in resp:
        code = resp.split("+ERR=", 1)[1].strip().split()[0]
        return f"+ERR={code} ({ERRORS.get(code, 'see AT manual')})"
    return resp or "(no answer)"


def query(ser, name):
    """AT+<name>?  ->  value string, or None if the module did not answer."""
    resp = at(ser, f"AT+{name}?")
    tag = f"+{name}="
    for line in resp.splitlines():
        line = line.strip()
        if line.startswith(tag):
            return line[len(tag):].strip()
    return None


def read_settings(ser):
    """Settings currently active in the module."""
    return {
        "version": query(ser, "VER"),
        "address": query(ser, "ADDRESS"),
        "network_id": query(ser, "NETWORKID"),
        "band": query(ser, "BAND"),
        "parameter": query(ser, "PARAMETER"),
        "power": query(ser, "CRFOP"),
    }


def describe_parameter(p):
    """'9,7,1,12' -> 'SF9, 125 kHz, CR 4/5, preamble 12'."""
    try:
        sf, bw, cr, pre = [int(x) for x in p.split(",")]
        bw_khz = {7: 125, 8: 250, 9: 500}.get(bw, f"code {bw}")
        return f"SF{sf}, {bw_khz} kHz, CR 4/{cr + 4}, preamble {pre}"
    except Exception:
        return str(p)


def configure(ser, address, network_id, band, parameter, power, log=print):
    """Apply the settings, report every rejected command, return what is ACTIVE.

    Never raises on a rejected command: the node keeps running with the
    settings the module holds, and the mismatch is printed prominently.
    """
    wanted = {
        "address": str(address),
        "network_id": str(network_id),
        "band": str(band),
        "parameter": str(parameter),
        "power": str(power),
    }
    at(ser, "AT")
    for cmd in (f"AT+ADDRESS={address}",
                f"AT+NETWORKID={network_id}",
                f"AT+BAND={band}",
                f"AT+PARAMETER={parameter}",
                f"AT+CRFOP={power}"):
        resp = at(ser, cmd)
        if "+OK" not in resp:
            log(f"⚠ {cmd} -> {explain(resp)}")

    actual = read_settings(ser)
    mismatch = [k for k, v in wanted.items()
                if actual.get(k) is not None and actual[k] != v]
    unknown = [k for k in wanted if actual.get(k) is None]
    for k in mismatch:
        log(f"⚠ LoRa {k}: requested {wanted[k]}, ACTIVE {actual[k]}")
    if "parameter" in mismatch:
        log(f"⚠ The radio is running at {describe_parameter(actual['parameter'])}, "
            f"not {describe_parameter(parameter)}. Both ends must match.")
    if unknown:
        log(f"⚠ Could not read back: {', '.join(unknown)}")
    actual["ok"] = not mismatch and not unknown
    return actual


# ------------------------------------------------------------------ diagnostic
def _detect():
    for port in sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*")):
        try:
            import serial
            t = serial.Serial(port=port, baudrate=BAUD_RATE, timeout=0.3)
            time.sleep(0.3)
            ok = "OK" in at(t, "AT")
            t.close()
            if ok:
                return port
        except Exception:
            continue
    return None


def main(argv):
    import serial
    args = [a for a in argv if not a.startswith("--")]
    try_value = None
    if "--try" in argv:
        try_value = argv[argv.index("--try") + 1]
        args = [a for a in args if a != try_value]
    port = args[0] if args else _detect()
    if not port:
        print("No LoRa module answered on /dev/ttyUSB* or /dev/ttyACM*. "
              "Give the port, e.g.  python3 lora_at.py /dev/ttyUSB0  (Windows: COM5)")
        return 1
    ser = serial.Serial(port=port, baudrate=BAUD_RATE, timeout=0.3)
    time.sleep(0.5)
    s = read_settings(ser)
    print(f"Port:       {port}")
    print(f"Firmware:   {s['version']}")
    print(f"Address:    {s['address']}")
    print(f"Network ID: {s['network_id']}")
    print(f"Band:       {s['band']} Hz")
    print(f"Parameter:  {s['parameter']}  ->  {describe_parameter(s['parameter'])}")
    print(f"Power:      {s['power']} dBm")
    if try_value:
        before = s["parameter"]
        resp = at(ser, f"AT+PARAMETER={try_value}")
        after = query(ser, "PARAMETER")
        print(f"\nAT+PARAMETER={try_value}  ->  {explain(resp)}")
        print(f"Active after the command: {after}  ->  {describe_parameter(after)}")
        if before and after != before:
            at(ser, f"AT+PARAMETER={before}")
            print(f"Restored: {query(ser, 'PARAMETER')}")
    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
