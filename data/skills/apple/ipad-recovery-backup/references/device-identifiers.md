# Known Device Identifiers

## iPad "Holger" — Recovery Mode Test Case

| Field | Value |
|---|---|
| Serial Number | JKM6MK4QXD |
| ECID | 000631003643601E |
| CPID | 8112 |
| Board ID | BDID:12 |
| Chip | Apple A15 Bionic |
| Likely Model | iPad mini (6th gen) or iPad Air (5th gen) |
| Hardware Issue | Defective/stuck power button (causes permanent Recovery Mode) |
| Status | In Recovery Mode as of 2026-05-22 |
| Connected To | MacHome (Mac mini, macOS via SSH) |

## Recovery Mode USB Signature

```
Vendor ID: 0x05ac (Apple Inc.)
Product ID: 0x1281 (Recovery Mode)
Location ID: 0x14500000 / N (varies by USB port)
```

## Tested Commands & Results

| Command | Result |
|---|---|
| `pymobiledevice3 restore exit` | Exit code 0, device re-enters Recovery immediately |
| `pymobiledevice3 restore restart` | Exit code 0, same behavior |
| `pymobiledevice3 backup2 backup` | Requires Normal Mode — never reached |

## Notes

- A15 chip devices boot to Recovery if the power button is held during startup.
- `pymobiledevice3 restore exit` sends the exit command to iBoot, but if the button remains shorted/pressed, the device loops back.
- Hardware fix required before any user data can be extracted.
