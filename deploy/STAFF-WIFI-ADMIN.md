# Staff Wi-Fi administration deployment

Website administration can be passwordless **only after** Caddy enforces the
Goodwood Staff VLAN boundary. Default backend configuration still requires
Basic Auth. The optional `[admin] password = ""` setting disables it.

The example below belongs inside the **test.goodwoodinstitute.asn.au** Caddy
site block, **before** the catch-all `file_server`:

```caddyfile
@staff remote_ip 192.168.2.0/24

handle /api/staff-status {
    header Cache-Control "no-store"
    respond @staff "" 204
    respond "" 403
}

@admin path /admin /admin/*
handle @admin {
    @notStaff not remote_ip 192.168.2.0/24
    respond @notStaff "Forbidden" 403
    reverse_proxy 127.0.0.1:8080
}

handle /api/* {
    reverse_proxy 127.0.0.1:8080
}

file_server
```

Do not configure a trusted proxy that lets external clients supply
`X-Forwarded-For` unchecked. The `remote_ip` matcher uses the connection's
source address, not an HTTP-supplied address. Gunicorn should remain bound to
`127.0.0.1:8080`; do not expose that port.

Arrange split DNS such that **Staff Wi-Fi** resolves
`test.goodwoodinstitute.asn.au` directly to `192.168.0.3`, not the
public WAN IP. Check that staff requests to `/api/staff-status` return 204,
and internet/Devices/Tech requests return 403. Clients using external DNS,
VPNs, or WAN hairpin NAT may not be recognised as staff.

**Only after both checks pass**, change the deployment config to
`[admin] password = ""` and restart `goodwood-website`.
The admin routes retain same-origin POST checks. A visible Admin link
is only a convenience, never an authorization mechanism.

Before relying on IP-only authentication, confirm that the Default network
and any other trusted path cannot reach the admin: the Caddy rule only
authorises VLAN 2. A shared Staff Wi-Fi password is effectively the credential.
