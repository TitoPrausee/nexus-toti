---
name: tailscale-docker
description: Set up Tailscale VPN inside a Docker container using userspace networking (no TUN device required).
version: 1.0.0
---

# Tailscale in Docker Container

Docker containers lack `/dev/net/tun` and kernel module access. Tailscale's normal mode fails with `CreateTUN("tailscale0") failed; /dev/net/tun does not exist`. Use **userspace-networking** mode instead.

## Installation

```bash
curl -fsSL https://tailscale.com/install.sh | sudo sh
```

## Startup (Userspace Mode)

```bash
# Create dirs
sudo mkdir -p /var/lib/tailscale /var/run/tailscale

# Start daemon (foreground — use background=true in Hermes terminal)
sudo tailscaled --tun=userspace-networking \
  --state=/var/lib/tailscale/tailscaled.state \
  --socket=/var/run/tailscale/tailscaled.sock

# Authenticate (open the URL in browser)
sudo tailscale --socket=/var/run/tailscale/tailscaled.sock up
```

## After Auth

```bash
# Check status
sudo tailscale --socket=/var/run/tailscale/tailscaled.sock status

# Use SOCKS5 proxy at localhost:1055 for traffic routing
# Example: curl via Tailscale network
curl --socks5 localhost:1055 http://<tailscale-ip>:<port>
```

## Key Facts

- **No TUN device needed** — userspace-networking routes through a SOCKS5 proxy on `localhost:1055`
- **Must specify socket** — all `tailscale` commands need `--socket=/var/run/tailscale/tailscaled.sock`
- **Not persistent** — daemon must be restarted after container restart (no systemd in Docker)
- **Background daemon** — start with `terminal(background=true)` in Hermes, foreground `&` is blocked

## Pitfalls

- `systemctl start tailscaled` fails in Docker — no systemd. Start daemon manually.
- Normal `tailscale up` won't work — must use `--tun=userspace-networking` flag.
- iptables errors in logs are cosmetic — userspace mode doesn't need them.
- Container restart kills the daemon — needs a startup script or cron job.

## Auto-start on Container Boot

Add to crontab or a startup script:

```bash
# In crontab (@reboot)
@reboot sudo mkdir -p /var/lib/tailscale /var/run/tailscale && sudo tailscaled --tun=userspace-networking --state=/var/lib/tailscale/tailscaled.state --socket=/var/run/tailscale/tailscaled.sock &
```

Or use Hermes cronjob with a startup script.