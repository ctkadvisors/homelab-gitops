# Runbook: example.com wildcard TLS

One Certificate (`ingress-system/example-tls`, SANs: example.com,
*.example.com, *.apps.example.com) issued via DNS-01/Cloudflare, replicated
to all namespaces by kubernetes-reflector. Renewal is automatic ~30 days
before expiry. **Never add per-namespace Certificates for these names** —
that recreates the 2026-08-04 duplicate-order stampede and the LE
5-duplicates/week rate limit. Note: `*.apps.example.com` also exists to keep
the identifier set distinct from the exhausted 2026-08 set — don't remove it
casually.

Self-healing: the `cert-medic` CronJob (cert-manager ns, every 6h) detects a
wedged ACME flow (stuck challenge / errored order >1h), deletes stray
`_acme-challenge` TXT records with cert-manager's own Cloudflare token, and
clears the stuck challenges/orders so cert-manager rebuilds. It stands down
during LE rate limiting.

Alerts (Prometheus, monitoring stack): WildcardCertExpiringSoon (<21d),
WildcardCertExpiryCritical (<7d), CertificateNotReady (6h). NOTE: Alertmanager's
receiver is still a dead webhook — alerts are visible in the Alertmanager UI
only until a real receiver is wired.

Manual remediation (what medic automates), from a kubectl-capable host:
1. `kubectl describe challenge -n ingress-system` — look for CleanUpError /
   Cloudflare 7003 (empty zone id) — the stale-TXT wedge.
2. Delete stray TXT: `_acme-challenge.example.com` and
   `_acme-challenge.apps.example.com` in Cloudflare (token: secret
   `cert-manager/cloudflare-api-token`).
3. `kubectl delete challenges,orders -n ingress-system --all`
4. If rate-limited (order reason `rateLimited`): wait for the stated window,
   or change the identifier set (add a SAN) — solver selector is zone-scoped
   (`dnsZones: example.com`) so any name under the zone works.
5. Traefik serves stale certs after secret rotation only if the secret
   didn't actually change; a `kubectl delete pod -n ingress-system <traefik>`
   forces a clean reload if in doubt.
