---
name: tailscale-docker-setup
title: Tailscale in Docker/Container (No TUN)
description: Install and run Tailscale in a containerized environment without /dev/net/tun, using userspace-networking mode.
---

# Tailscale Setup in Docker/Container (No TUN Device)

Use when running Tailscale in a container, Docker, or any environment without `/dev/net/tun` and without root/privileged mode.

## Prerequisites

- A Tailscale account (https://tailscale.com)
- The static binary archive for your arch (e.g. `tailscale_1.96.4_arm64.tgz`)
- No root access needed — runs entirely in userspace

## Step-by-Step

### 1. Download the Static Binary

```bash
# Find latest version
curl -s https://api.github.com/repos/tailscale/tailscale/releases/latest | \
  python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'])"

# Download for your arch (aarch64 or x86_64)
ARCH="arm64"  # or "amd64"
wget -q "https://pkgs.tailscale.com/stable/tailscale_1.96.4_linux_${ARCH}.tgz" -O /tmp/tailscale.tgz

# Extract
tar -xzf /tmp/tailscale.tgz -C /tmp/
# Binaries at /tmp/tailscale_1.96.4_linux_${ARCH}/tailscale and tailscaled
```

### 2. Start the Daemon (userspace mode)

```bash
# CRITICAL: --tun=userspace-networking goes on tailscaled, NOT tailscale up
/tmp/tailscale_1.96.4_arm64/tailscaled \
  --tun=userspace-networking \
  --socket=/tmp/tailscale.sock \
  --state=/tmp/tailscale.state \
  --verbose=0 &
```

The daemon runs in background. No TUN device, no root needed.

### 3. Authenticate

```bash
/tmp/tailscale_1.96.4_arm64/tailscale --socket=/tmp/tailscale.sock up --ssh
```

This prints a URL like `https://login.tailscale.com/a/xxxxxx`. Open it in a browser to authenticate.

### 4. Verify Connection

```bash
/tmp/tailscale_1.96.4_arm64/tailscale --socket=/tmp/tailscale.sock status
```

Shows all devices in the tailnet with their IPs.

## Pitfalls Discovered

- ❌ Do NOT pass `--tun` to `tailscale up` — it says "flag provided but not defined"
- ✅ `--tun=userspace-networking` goes on `tailscaled` (the daemon), not the client
- ❌ `--netfilter-mode=off` is NOT supported in older versions — just don't use it
- ❌ The default socket is `/var/run/tailscale/tailscaled.sock` which needs root — use `--socket=/tmp/tailscale.sock` instead
- ⚠️ The `TAILSCALE_SOCKET` env var doesn't work consistently — always use `--socket=/tmp/tailscale.sock` on both daemon AND client
- ⚠️ After `tailscale up`, the command blocks waiting for auth. Press Ctrl+C after you see the URL, or set a timeout
- ✅ Daemon stays running after `tailscale up` exits — the connection persists
- 🎯 Multiple devices in the same tailnet can communicate via their `100.x.x.x` IPs
