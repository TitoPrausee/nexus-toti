# Recovery-Mode Command Cheat Sheet

## Quick Reference

```bash
export PATH="/Users/$USER/Library/Python/3.9/bin:$PATH"

# --- Identification ---
pymobiledevice3 restore devices                        # List recovery/DFU devices
pymobiledevice3 restore device-info --ecid <ECID>     # Detailed hardware info

# --- Exit / Restart ---
pymobiledevice3 restore exit                           # Signal iBoot → Normal Mode
pymobiledevice3 restore restart                        # Reboot (same mode if button stuck)
pymobiledevice3 restore enter-dfu                    # Force DFU Mode

# --- iBoot Shell ---
pymobiledevice3 restore shell --ecid <ECID>           # Interactive iBoot shell
# Inside shell: printenv, devicetree, bootargs, setenv, saveenv

# --- RAM Disk ---
pymobiledevice3 restore ramdisk                        # Auto-select signed IPSW
pymobiledevice3 restore ramdisk --ipsw <path/url>      # Use specific IPSW

# --- Restore (ERASES DATA) ---
pymobiledevice3 restore restore --ipsw <path>          # Full restore
pymobiledevice3 restore restore --ipsw <path> --erase # Explicit erase
pymobiledevice3 restore restore --ipsw <path> --no-baseband  # Skip baseband flash

# --- Debug / Advanced ---
pymobiledevice3 restore tss --ecid <ECID> --save      # Save SHSH blobs
pymobiledevice3 restore sep-firmware --ipsw <path>    # Update SEP firmware
pymobiledevice3 restore debug-server --start            # Remote debug bridge
pymobiledevice3 restore erase                           # Erase command (limited availability)
```

## Device State Check

```bash
# macOS
system_profiler SPUSBDataType | grep -A 5 "Product ID: 0x1281"  # Recovery
system_profiler SPUSBDataType | grep -A 5 "Product ID: 0x12a8"  # Normal
system_profiler SPUSBDataType | grep -A 5 "Product ID: 0x1227"  # DFU

# Linux
lsusb | grep "05ac:1281"   # Recovery
lsusb | grep "05ac:12a8"   # Normal
lsusb | grep "05ac:1227"   # DFU
```

## IPSW Workflow

```bash
# Check signing status before downloading
# Use: https://tsschecker.github.io or https://ipsw.me/signing

# Download IPSW (example for iPad mini 6 — adjust model)
curl -O https://updates.cdn-apple.com/.../iPad_Firmware_X.Y.Z_XYZ_Restore.ipsw

# Verify checksum (Apple publishes SHA1 in update manifests)
shasum -a 1 iPad_Firmware_*.ipsw
```
