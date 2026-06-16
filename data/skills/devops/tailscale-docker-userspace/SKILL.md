---
name: tailscale-docker-userspace
description: Set up Tailscale VPN inside a Docker container using userspace networking (no TUN device). Use when the user asks to install Tailscale in a containerized environment.
version: 1.0.0
---

# Tailscale in Docker — Userspace Mode

Docker containers lack `/dev/net/tun`, so normal `tailscale up` fails with:
```
CreateTUN("tailscale0") failed; /dev/net/tun does not exist
```

## Solution: Userspace-Networking Mode

### Install
```bash
curl -fsSL https://tailscale.com/install.sh | sudo sh
```

### Start Daemon (background, userspace)
```bash
sudo mkdir -p /var/lib/tailscale /var/run/tailscale
sudo tailscaled --tun=userspace-networking \
  --state=/var/lib/tailscale/tailscaled.state \
  --socket=/var/run/tailscale/tailscaled.sock &
```

### Authenticate
```bash
sudo tailscale --socket=/var/run/tailscale/tailscaled.sock up
```
Opens a login URL — visit in browser to complete auth.

### Check Status
```bash
sudo tailscale --socket=/var/run/tailscale/tailscaled.sock status
```

## Limitations

- **SOCKS5 proxy only** — traffic goes through `localhost:1055`, not a real network interface
- Access other Tailscale devices via: `curl --proxy socks5://localhost:1055 100.x.x.x:port`
- Services inside the container are reachable from other Tailscale devices at the container's Tailscale IP (e.g. `<PRIVATE_IP>:3000`)
- **No `systemd`** in Docker — must start `tailscaled` manually after container restart
- iptables/nftables may show permission errors — safe to ignore in userspace mode

## Persistence

Daemon dies on container restart. Add to startup:
```bash
# Add to entrypoint or profile
sudo tailscaled --tun=userspace-networking \
  --state=/var/lib/tailscale/tailscaled.state \
  --socket=/var/run/tailscale/tailscaled.sock &
sleep 2
```

Auth persists in `/var/lib/tailscale/tailscaled.state` — no re-login needed after restart (unless key expired).

## Pitfalls

- `systemctl start tailscaled` fails inside Docker (no systemd PID 1) — use direct daemon command
- `sudo tailscale up` without `--socket` flag fails if socket is non-default — always pass `--socket=/var/run/tailscale/tailscaled.sock`
- SOCKS5 proxy does NOT work for connecting to localhost services from within the same container — use `localhost` directly for local services