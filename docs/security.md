---
title: Security
---

# Security

Pi-Spy-RF is designed for **trusted LAN / lab use**. Treat it like any SDR control panel: if someone can reach the web UI without auth, they can start spectrum scans, queue decodes, and run wireless scans.

Version **0.8.1** applies Claude review fixes (deadlocks, nmcli parse, device cache, insecure LAN refuse).

Version **0.8.0** included a hardening pass for multi-OS deployment (Linux, macOS, Windows, Raspberry Pi).

---

## Threat model (short)

| You trust | Risk if exposed without auth |
|-----------|------------------------------|
| Localhost only | Low |
| Home LAN with auth | Medium (shared WiFi users) |
| Public internet | **Do not expose** |

This app runs local subprocesses (`rtl_power`, `rtl_fm`, `multimon-ng`, `nmcli`, `iw`, `bluetoothctl`) with **fixed argument lists** (no shell). User-controlled values are validated/clamped before use.

---

## Hardening changes (0.8.0 / 0.8.1)

1. **Default bind** in `config.example.yaml` is `127.0.0.1` (local only). Open LAN only when you enable auth.
2. **Startup warning** if listening on `0.0.0.0` / `::` with auth disabled.
3. **Login rate limit** (8 attempts / 5 minutes per client IP).
4. **Session cookies**: `HttpOnly`, `SameSite=Lax`; set `PI_SPY_SECURE_COOKIE=1` behind HTTPS.
5. **Security headers**: `X-Content-Type-Options`, `X-Frame-Options`, CSP, `Referrer-Policy`, `Permissions-Policy`.
6. **Input clamps**: decode frequency 1–6000 MHz; decode duration 2–60 s; spectrum span ≤ 200 MHz; WiFi iface name whitelist; event text length limits.
7. **Demo SDR placeholders** can be disabled with `PI_SPY_NO_DEMO=1`.
8. **YAML** loaded with `yaml.safe_load` only.
9. **SQLite** uses parameterized queries.
10. **UI** escapes dynamic HTML (`escapeHtml` in `app.js`).

---

## Recommended production config (LAN)

```yaml
server:
  host: "0.0.0.0"
  port: 8080

auth:
  enabled: true
  username: "ops"
  password: ""   # use env instead
```

```bash
export PI_SPY_PASSWORD='choose-a-long-password'
# optional behind reverse proxy TLS:
export PI_SPY_SECURE_COOKIE=1
./run.sh
```

Windows PowerShell:

```powershell
$env:PI_SPY_PASSWORD = "choose-a-long-password"
.\run.bat
```

---

## What we do NOT claim

- Not a hardened internet-facing appliance
- Not suitable as a public SaaS without reverse proxy, TLS, and stronger identity
- Wireless/SDR tools may need OS permissions (USB, BlueZ, NetworkManager)
- Encrypted digital voice is **detected/flagged**, not broken

---

## Reporting issues

Open a GitHub issue on https://github.com/Sid3b00m/Pi-Spy-RF with steps to reproduce. Do not post live credentials.


### Insecure LAN override

To force bind `0.0.0.0` without auth (lab only):

```bash
export PI_SPY_ALLOW_INSECURE_LAN=1
```
