# imaginationapplied.ai — DNS migration record

**Zone captured 2026-08-11T00:37Z, before any change.** Nameservers were
GoDaddy (`ns21`/`ns22.domaincontrol.com`).

This domain carries **live Google Workspace email**. The nameserver move drops
any record not carried across, so this file exists to make the move mechanical:
recreate exactly this set in Cloudflare, verify, then switch.

## Why the nameservers have to move at all

Every canonical URL on this site is apex-form
(`https://imaginationapplied.ai/publications/...`). GoDaddy has no ALIAS/ANAME
record, so the apex cannot point at Cloudflare Pages while GoDaddy holds DNS —
it can only *forward*, which makes the canonical URL a 301 hop. That
reintroduces the redirect fragility the whole static build exists to avoid.
Cloudflare flattens CNAMEs at the apex, so the apex can serve directly.

## Records as captured (recreate all of these)

### Mail — the ones that must not be lost

| Type | Name | Value | TTL |
|---|---|---|---|
| MX | `@` | `1 smtp.google.com.` | auto |
| TXT | `google._domainkey` | `v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAsrianmjSTPGWDn1Jzuv9wmJgMYwqQ9DGeOtjWDjKCYkGWeYbUn4olfZDDhzbRSNhq0BGOiwMLlLzDwVhvxak33Rktam9a786S2XhZeqvXk01n33M89uUxIZckBJBzM5sw+DTW7DZBBgSCkYFWgN0TYT3eyhxFa9AGgHvJkulii5BL5Wb918VY0Vx9/cxCyIXOn8VWqnRfWDVnIgB0S9dFUZuH7JPWwgg3SblzszhVvNCE5YbK1EWv8K5oBCmPdwSeqldJ31cKq1Hv0C+14LXJKLhRGPKppw5VRrBk+l/wHTml/+7Bd2U1hj/h53WtpmAeQhSZWNr3B8Y8jC3pgIGrwIDAQAB` | auto |
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:dmarc@imaginationapplied.ai` | auto |

> The DKIM value is one string split across two quoted chunks in DNS. Paste it
> as a single unbroken value; Cloudflare re-chunks it automatically.

### Verification

| Type | Name | Value |
|---|---|---|
| TXT | `@` | `google-site-verification=oGfuwtqXSxUEdQirIRZBpGu3gag7z_wK5eHBWLlFH2s` |

### SPF — fix this during the move

The zone currently has **two** `v=spf1` records:

```
v=spf1 include:_spf.google.com include:secureserver.net ~all
v=spf1 include:_spf.google.com include:amazonses.com ~all
```

RFC 7208 §4.5 makes more than one SPF record a `permerror` — receivers may
treat SPF as failing outright. This is pre-existing and unrelated to the site,
but recreating both would carry a live fault forward. Replace with one:

```
v=spf1 include:_spf.google.com include:amazonses.com ~all
```

**Settled (Josh, 2026-08-10): drop `secureserver.net`.** Nothing sends through
GoDaddy's relay any more — mail is on Google Workspace. Amazon SES is kept
because dropping a sender silently breaks whatever uses it. The single record
above is what to apply.

### Web — the records that change

| Type | Name | Old (GoDaddy forwarding) | New |
|---|---|---|---|
| A | `@` | `15.197.225.128`, `3.33.251.168` | **delete** — replaced by the Pages CNAME |
| A | `www` | `185.158.133.1` | **delete** |
| CNAME | `@` | — | `<project>.pages.dev` (proxied) |
| CNAME | `www` | — | `<project>.pages.dev` (proxied) |

The old apex A records are GoDaddy's forwarding service, which is what makes
`imaginationapplied.ai` 301 to `www.joshpenzell.com` today. Removing them is
what retires the redirect.

### ⚠️ Records this file originally MISSED

**Corrected 2026-08-12.** The first capture was built by probing a guessed list
of record names with `dig`. Public DNS cannot be enumerated — you only find
names you think to ask for — so that method silently misses anything not on the
list. Cloudflare's scan (which reads the registrar's actual zone) found three
records the probe never asked about, two of them mail-critical:

| Type | Name | Content | Why it matters |
|---|---|---|---|
| MX | `send` | `feedback-smtp.us-east-1.amazonses.com` (10) | Amazon SES bounce/complaint handling |
| TXT | `resend._domainkey` | `p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDsSqPCqOhsWxSMPoojq4VhrPJUERNQ+NiZzyqP/wazvQ7JxOT5nqVsck/DaSYxQSb3BWYfbWoyX8c6DTXu4mts1PV44g7LEVVgwinOrzEv3BJwFqWGku8WgZiewR95t2kFpNznUtqv8AkUoFMsB79ztY2Z/tupPxI2ATji80wk2wIDAQAB` | Resend DKIM signing |
| CNAME | `_domainconnect` | `_domainconnect.gd.domaincontrol.com` | GoDaddy Domain Connect; harmless |

Rebuilding the zone by hand from the original capture would have dropped SES
bounce handling and broken Resend's DKIM signatures. **Prefer the provider's
own zone scan or an AXFR/zone export over probe-based reconstruction.**

Both are confirmed live and both are now in the Cloudflare zone.

### Confirmed absent

No AAAA, no CAA, no SRV, and no CNAMEs on any of: `mail`, `autodiscover`,
`calendar`, `drive`, `docs`, `sites`, `m`, `ftp`, `cpanel`, `webmail`, `blog`,
`www2`, `staging`.

## Order of operations

1. Add the site to Cloudflare. Its scan imports most of the above — **do not
   trust the import**, diff it against this file record by record.
2. Fix SPF to a single record. Confirm MX, DKIM, DMARC and the Google
   verification TXT are all present in the Cloudflare zone.
3. Add the custom domain in the Pages project (apex and `www`).
4. **Only then** change the nameservers at the registrar.
5. After propagation, verify — mail first:

```bash
dig +short MX imaginationapplied.ai
dig +short TXT google._domainkey.imaginationapplied.ai
dig +short TXT _dmarc.imaginationapplied.ai
dig +short TXT imaginationapplied.ai | grep spf   # expect exactly ONE line
curl -s https://imaginationapplied.ai/ | grep -i -e '<title' -e canonical
```

6. Send a test email to and from the domain before considering it done.

## DNSSEC — checked, and it is off

Verified 2026-08-12: no `DS` at the parent, no `DNSKEY` published. This matters
because changing nameservers while DNSSEC is enabled makes the domain fail to
resolve **entirely** — web and mail — until the DS record is removed and that
removal propagates. Re-check with:

```bash
dig DS imaginationapplied.ai +noall +answer   # must be empty
```

## Progress

- Zone created in Cloudflare (Free), records imported from the registrar scan.
- Duplicate SPF removed; a single record remains:
  `v=spf1 include:_spf.google.com include:amazonses.com ~all`
- Assigned Cloudflare nameservers: `dan.ns.cloudflare.com`, `violet.ns.cloudflare.com`
- **Nameservers NOT yet changed at GoDaddy.** Until they are, this zone is
  inert and the live domain still resolves through GoDaddy exactly as before.

Still to do: attach the apex + `www` custom domain to the Pages project, remove
the three GoDaddy forwarding A records, then flip the nameservers.

## Known trap

GoDaddy silently injects its own `_dmarc` record at `p=quarantine` when it
takes over a zone. That bit the theaterthink.com migration: two DMARC records
is invalid under RFC 7489, which means no policy applies at all. This move goes
the other way, so it should not apply here — but re-check `_dmarc` returns
exactly one record after any DNS change, in either direction.

## Rollback

Point the nameservers back at `ns21.domaincontrol.com` / `ns22.domaincontrol.com`.
The GoDaddy zone is retained for a period after a nameserver change, so the old
forwarding behaviour returns once propagation completes. This is the reason to
do the DNS step last, and only after the `*.pages.dev` URL is verified working.
