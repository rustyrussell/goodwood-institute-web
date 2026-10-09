# Staff Wi-Fi and remote password access to website administration

Protect the entire `/admin/` subtree **in Caddy**. Staff Wi-Fi
(VLAN 2, `192.168.2.0/24`) bypasses HTTP Basic authentication; visitors
arriving from any other network must supply a password. The Flask admin
password can remain empty in the private `config.toml`, provided that all
public admin traffic passes through this Caddy rule.

This configuration belongs inside the `test.goodwoodinstitute.asn.au`
Caddy site block, before its catch-all file server:

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
    basic_auth @notStaff {
        admin YOUR_BCRYPT_HASH_HERE
    }
    reverse_proxy 127.0.0.1:8080
}

handle /api/* {
    reverse_proxy 127.0.0.1:8080
}

file_server
```

Run `caddy hash-password` interactively (password input is hidden),
and paste the resulting **hash** in place of `YOUR_BCRYPT_HASH_HERE`.
Choose a new password rather than reusing the previously exposed
`staging-only` test password. Never put the plaintext password in the
Caddyfile, Git, command-line arguments or shell history.

Validate and reload Caddy (as root):

```sh
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

From outside Staff Wi-Fi, `curl -I
https://test.goodwoodinstitute.asn.au/admin/` should respond **401**
and advertise the Basic authentication realm. The browser prompts for
username `admin` and your password, then displays admin. From Staff
Wi-Fi, the same URL should return **200** without credentials.
`/api/staff-status` remains 204 from Staff Wi-Fi and 403 elsewhere,
so the main website displays the Admin link only to on-site staff
even though authenticated visitors can navigate to it directly.

Do not configure a trusted proxy that lets external clients supply
`X-Forwarded-For` unchecked. The `remote_ip` matcher checks the
network connection's address, not a client-supplied HTTP header.
Gunicorn must remain bound to `127.0.0.1:8080`, not exposed publicly.

Split DNS should resolve `test.goodwoodinstitute.asn.au` to
`192.168.0.3` on Staff Wi-Fi. Clients using public DNS, VPNs,
or WAN hairpin NAT may be treated as remote users and see the
password prompt; that is the secure default.

If this Caddy pattern is later used for the production hostname,
apply it explicitly in the production vhost as well. Caddy site
blocks do not inherit one another's access control.
