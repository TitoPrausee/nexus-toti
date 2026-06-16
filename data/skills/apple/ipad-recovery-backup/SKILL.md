---
name: ipad-recovery-backup
description: Create and manage iPad/iPhone backups when the device is stuck in Recovery Mode. Covers pymobiledevice3 usage, recovery-mode capabilities, limitations, iBoot shell access, RAM disk boot, firmware operations, and data preservation strategies.
version: 1.1.0
author: Toti
metadata:
  hermes:
    tags: [Apple, iOS, Recovery Mode, Backup, pymobiledevice3, iPad, iBoot, Firmware]
---

# iPad/iPhone Recovery-Mode Skill

## Overview

When an iPad/iPhone is stuck in Recovery Mode (e.g., from a broken hardware button), standard iTunes/Finder backups via `idevicebackup2` are impossible because they require **Lockdown mode** (Normal Mode).

This skill documents **all available tools, commands, and capabilities** when a device is in Recovery Mode — plus realistic limitations and fallback strategies.

## Identifying Recovery Mode

### Via USB (macOS/Linux)

```bash
system_profiler SPUSBDataType   # macOS
lsusb | grep -i apple           # Linux
```

Look for:
```
Product ID: 0x1281              # Recovery Mode identifier
Vendor ID: 0x05ac (Apple Inc.)
Serial Number: <visible>
```

### USB Product ID Reference

| Mode | Product ID | Description |
|---|---|---|
| Normal (Lockdown) | 0x12a8 | Full iOS running; all services available |
| Recovery Mode | 0x1281 | iBoot loaded; limited firmware operations |
| DFU Mode | 0x1227 | Bootrom loaded; lowest-level restore possible |

## Tools

### pymobiledevice3 (Primary Tool)

Install on macOS/Linux (no sudo required):
```bash
pip3 install --user pymobiledevice3
export PATH="/Users/$USER/Library/Python/3.9/bin:$PATH"
```

## Complete Recovery-Mode Capability Reference

### 1. Device Identification & Info

```bash
# List all connected devices in Recovery/DFU mode
pymobiledevice3 restore devices

# Get detailed device info (ECID, CPID, BDID, SRTG, etc.)
pymobiledevice3 restore device-info --ecid <ECID>
```

**Extracted identifiers (our test device):**
| Field | Value |
|---|---|
| Serial Number | JKM6MK4QXD |
| ECID | 000631003643601E |
| CPID | 8112 |
| Board ID | BDID:12 |
| Chip | Apple A15 Bionic |
| Likely Model | iPad mini (6th gen) or iPad Air (5th gen) |

### 2. Exit Recovery Mode

```bash
# Signal iBoot to exit Recovery and boot normally
pymobiledevice3 restore exit

# Equivalent verbose
pymobiledevice3 restore exit --ecid <ECID>
```

**Requirements:** Power/Volume buttons must NOT be physically stuck. If the button remains shorted, the device immediately re-enters Recovery Mode.

### 3. Restart from Recovery Mode

```bash
# Reboot the device (stays in same mode if buttons stuck)
pymobiledevice3 restore restart
```

### 4. iBoot Interactive Shell

```bash
# Open an IPython shell for low-level iBoot interaction
pymobiledevice3 restore shell --ecid <ECID>
```

**What you can do in iBoot shell (advanced):**
- Read iBoot variables (`printenv`)
- Query device tree (`devicetree`)
- Inspect boot arguments (`bootargs`)
- Explore iBoot memory regions
- Limited filesystem inspection (not user data)

**What you CANNOT do:**
- Read photos, messages, or app data
- Mount the user partition in readable form
- Extract keychain or app containers

### 5. Boot Update RAM Disk

```bash
# Boot a signed IPSW's update ramdisk WITHOUT restoring
# This temporarily loads a mini-OS into RAM
pymobiledevice3 restore ramdisk --ipsw <path-or-url-to-ipsw>

# Or let it auto-select a signed build interactively
pymobiledevice3 restore ramdisk
```

**What a RAM disk can do:**
- Mount filesystem partitions in read-only mode
- Inspect system logs
- Access diagnostic partitions
- Potentially mount the data partition for manual extraction

**Caveat:** The RAM disk environment is limited and does not mount user data by default. Mounting `/private/var` requires extra steps and may fail with encryption.

### 6. Full Firmware Restore (Erase Mode)

```bash
# Restore to factory settings using IPSW (ERASES ALL DATA)
pymobiledevice3 restore restore --ipsw <path-to-ipsw>

# Or auto-download signed IPSW
pymobiledevice3 restore restore --ipsw <url>
```

**Stages of a restore:**
1. Send TSS request to Apple — get signed firmware blobs.
2. Upload iBEC (secondary bootloader) to device.
3. Upload kernelcache and device tree.
4. Flash filesystem image to NAND.
5. Boot into fresh iOS (Activation screen).

**After restore:** Device is factory-fresh, Activation Lock still active if FindMy was on.

### 7. DFU Mode Transition (From Recovery)

```bash
# Force device into DFU mode (deeper than Recovery)
pymobiledevice3 restore enter-dfu --ecid <ECID>
```

**DFU Mode differences from Recovery:**
- Uses Product ID `0x1227`
- Bootrom (not iBoot) is active — most primitive state
- Required for downgrades (with SHSH blobs) or severe corruption
- Even fewer user-data access possibilities

### 8. Activation State Check

```bash
# Some recovery interfaces expose activation status
pymobiledevice3 activation activate
# or query
pymobiledevice3 activation state
```

**Note:** Usually requires Normal Mode (lockdown), but some builds expose activation info via recovery.

### 9. Save SHSH Blobs

```bash
# ApTickets/SHSH blobs can be saved for potential downgrade
pymobiledevice3 restore tss --ecid <ECID> --save
```

**Useful for:** Future jailbreaks or unsigned downgrades with checkm8/checkra1n (not applicable for A15 — no bootrom exploit).

### 10. Set Boot Arguments (iBoot)

Via the iBoot shell:
```python
# Example within iBoot shell
setenv boot-args "-v debug=0x14e"
saveenv
```

**Can enable:** Verbose boot logging, kernel debugging flags.

### 11. Restore with Custom Options

```bash
# Restore but preserve user data (if possible)
pymobiledevice3 restore restore --ipsw <path> --erase

# Restore without baseband update
pymobiledevice3 restore restore --ipsw <path> --no-baseband

# Restore with custom TSS server (e.g., for beta firmware)
pymobiledevice3 restore restore --ipsw <path> --tss-server <url>
```

### 12. Erase Device (Without Firmware Restore)

```bash
# Send erase command via recovery (not always available)
pymobiledevice3 restore erase
```

**Availability:** Limited; often requires Normal Mode lockdown service.

### 13. Debug Bridge (For Development/Debugging)

```bash
# Access remote debugging interfaces available in recovery
pymobiledevice3 restore debug-server --start
```

**Use case:** iOS/kernel debugging with Xcode or lldb. Requires developer knowledge.

### 14. Update SE/SEP Firmware

```bash
# Update Secure Enclave firmware (separate from iOS)
pymobiledevice3 restore sep-firmware --ipsw <path>
```

**Use case:** Fixing Touch ID/Face ID issues after restore failures.

---

## Recovery Mode: Complete Capability Matrix

| Capability | Recovery Mode | DFU Mode | Normal Mode |
|---|---|---|---|
| Full user data backup | ❌ No | ❌ No | ✅ Yes |
| Photo extraction | ❌ No | ❌ No | ✅ Yes |
| App data extraction | ❌ No | ❌ No | ✅ Yes |
| iBoot shell access | ✅ Yes | ❌ No (bootrom) | ❌ No |
| Firmware restore (IPSW) | ✅ Yes | ✅ Yes | ❌ No |
| RAM disk boot | ✅ Yes | ❌ No | ❌ No |
| Device info (ECID/Serial) | ✅ Yes | ✅ Yes | ✅ Yes |
| Exit to Normal Mode | ⚠️ Conditional* | ❌ No | N/A |
| Force DFU | ✅ Yes | N/A | ❌ No |
| SHSH blob saving | ✅ Yes | ⚠️ Partial | ❌ No |
| Verbose boot args | ✅ Via iBoot | ❌ No | ❌ No |
| SEP/Secure Enclave update | ⚠️ During restore | ⚠️ During restore | ❌ No |
| Activation check | ⚠️ Sometimes | ❌ No | ✅ Yes |
| Recovery Mode entry | N/A | N/A | ✅ Yes (button combo) |

*Requires hardware buttons to be free (not stuck).

## Data Preservation Strategies

### Strategy A: Fix Hardware → Enter Normal Mode → Backup

**Best case.** See `apple-device-button-failure` skill for repair guidance.

Once in Normal Mode:
```bash
# Full local backup
pymobiledevice3 backup2 backup --backup-directory ~/Backups/

# Also trigger iCloud backup manually on device
```

### Strategy B: iCloud Recovery (Pre-existing Backup)

Log into https://icloud.com from any browser:
- Photos, Drive files, Contacts, Calendar, Notes
- Device backup itself: can only restore to a replacement device

### Strategy C: RAM Disk Manual Mount (Expert/Risky)

If you have the correct IPSW and experience:
```bash
# 1. Boot RAM disk with IPSW
pymobiledevice3 restore ramdisk --ipsw <path>

# 2. Inside RAM disk environment, manually mount partitions
#    (requires understanding of iOS partition layout: /dev/disk0s1s1 system, /dev/disk0s1s2 data)
# 3. If data partition is encrypted, it's inaccessible without the passcode.
```

**Reality:** For modern devices (A12+), the data partition is FileVault-encrypted with the passcode. Without the passcode entered in Normal Mode, RAM disk cannot decrypt it.

### Strategy D: DFU Restore (Last Resort — Data Loss)

```bash
# Enter DFU manually (if button combo works), then:
pymobiledevice3 restore restore --ipsw <path-to-ipsw>
```

**Warning:** Complete data loss. Only viable if:
1. iCloud backup exists, OR
2. Data is acceptable to lose.

## iOS Version & IPSW Matching

1. Identify model from Serial: https://checkcoverage.apple.com
2. Download IPSW: https://ipsw.me or https://appledb.dev
3. Verify Apple signing status: https://tsschecker.github.io or https://ipsw.me/signing

**For A15 devices (iPad mini 6 / iPad Air 5):**
- Unsigned IPSW **will not restore** — check signing status first.
- No bootrom exploit exists for A15 — no downgrade without signed firmware.

## Common Failures

| Symptom | Cause | Fix |
|---|---|---|
| `restore exit` returns 0 but device stays in Recovery | Button physically pressed | Fix hardware first |
| `backup2` fails with "Could not connect to lockdown" | Device in Recovery Mode | Not fixable without Normal Mode |
| Product ID switches briefly then back to 0x1281 | Button shorted/bouncing | Clean/repair button |
| Restore IPSW fails "not signed" | Apple stopped signing that version | Use currently signed version |
| RAM disk boot hangs | Wrong IPSW for device | Verify exact model + build |

## Documentation & References

- pymobiledevice3 GitHub: https://github.com/doronz88/pymobiledevice3
- iPhone Wiki — Recovery Mode: https://theiphonewiki.com/wiki/Recovery_Mode
- iPhone Wiki — DFU Mode: https://theiphonewiki.com/wiki/DFU_Mode
- IPSW library: https://appledb.dev
- SHSH/checkm8 status: https://checkm8.info

## Skill Files

- [references/device-identifiers.md](references/device-identifiers.md) — Known serials, ECIDs, model mappings
- [references/recovery-commands.md](references/recovery-commands.md) — Quick command cheat sheet
