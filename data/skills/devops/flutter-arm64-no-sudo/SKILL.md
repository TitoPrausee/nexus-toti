---
name: flutter-arm64-no-sudo
description: Install Flutter SDK on ARM64 Linux (aarch64) without root or apt. Handles the missing unzip, x86_64 tarball trap, and Dart SDK initialization.
tags:
  - flutter
  - arm64
  - aarch64
  - linux
  - setup
---

# Flutter on ARM64 Linux (No Sudo)

Installing Flutter on aarch64 Linux is **not** straightforward. The standard tarball from `flutter.dev` is x86_64-only and will crash with:

```
rosetta error: failed to open elf at /lib64/ld-linux-x86-64.so.2
```

Use this approach instead.

## Prerequisites

- `git`, `curl`, `python3` (these are usually present)
- No `unzip`, no `flutter`, no `dart` required — we build it all

## Step 1: Clone Flutter SDK (not the tarball!)

```bash
cd /opt/data/home
git clone --depth=1 -b stable https://github.com/flutter/flutter.git flutter-sdk
```

The git clone gives you a **native ARM64 Dart engine** — the official tarballs are x86_64 only.

## Step 2: Create a Python unzip shim

Flutter's setup script calls `unzip` to extract Dart SDK. If `unzip` isn't installed (common in containers), create this shim:

```python
# Write to: /opt/data/home/flutter-sdk/bin/unzip
import sys, zipfile, os

args = [a for a in sys.argv[1:] if not a.startswith('-')]

if len(args) < 1:
    print("Usage: unzip file.zip [-d directory]")
    sys.exit(1)

archive = args[0]
dest = '.'
if '-d' in sys.argv:
    idx = sys.argv.index('-d')
    if idx + 1 < len(sys.argv):
        dest = sys.argv[idx + 1]

os.makedirs(dest, exist_ok=True)
with zipfile.ZipFile(archive) as z:
    z.extractall(dest)
```

Make it executable:
```bash
chmod +x /opt/data/home/flutter-sdk/bin/unzip
```

## Step 3: First run (triggers Dart SDK download)

```bash
export PATH="/opt/data/home/flutter-sdk/bin:$PATH"
flutter --version
```

Flutter will detect the missing Dart SDK, download the ARM64 variant via `curl`, and extract it using your Python unzip shim. This works because Flutter's internal download logic checks `uname -m` and fetches the correct architecture.

## Step 4: Fix permissions if needed

```bash
chmod -R +x /opt/data/home/flutter-sdk/bin/cache/dart-sdk/bin/
# Verify:
flutter --version
```

## Step 5: Handle integration_test dependency

If `flutter pub get` fails with `integration_test from sdk which doesn't exist`, remove it from `pubspec.yaml`:

```yaml
dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^4.0.0
  mocktail: ^1.0.0
  # REMOVE: integration_test:  (requires full Flutter SDK)
```

## Step 6: Verify

```bash
flutter pub get
flutter analyze
```

## Common Pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| `rosetta error: failed to open elf` | Used x86_64 tarball | Clone from git instead |
| `unzip: command not found` | No unzip binary | Use Python shim (Step 2) |
| `dart: Permission denied` | Extracted without +x | `chmod -R +x bin/cache/dart-sdk/bin/` |
| `integration_test from sdk which doesn't exist` | Flutter SDK not in standard location | Remove from pubspec.yaml |
| `Downloading Linux arm64 Dart SDK...` loops | Corrupted zip | Delete `bin/cache/dart-sdk` directory and re-run |

## Verification

```bash
flutter --version
# Expected: Flutter 3.41.x • channel stable • on linux_arm64
# Dart 3.11.x • DevTools 2.54.x
```
