# Cloud Armor and load balancer — NOT APPLIED

This directory is committed but not deployed. `terraform validate` passes; nothing
here exists in the project until somebody runs `terraform apply`.

## Why it is unapplied

A global external Application Load Balancer costs roughly **USD 18-25 per month
before any traffic**, plus Cloud Armor policy and per-request charges. Cloud Armor
cannot attach to a Cloud Run service directly — it attaches to a backend service,
which needs a serverless NEG, which needs a load balancer — so there is no cheaper
way to have it. This project runs on limited credit, so the free
application-layer defences were built first.

## What the application already does, and what this adds

The application layer closes the holes that were actually exploited: an API key on
every write, `MAX_CONTENT_LENGTH` before the body is buffered, per-route rate
limits on anything that calls a model, and `ProxyFix` so those limits key on the
real client IP.

What it cannot do, and this can:

| | Application | Cloud Armor |
|---|---|---|
| Refuses a request before it is billed | No — after gunicorn parses it | Yes, at Google's edge |
| Rate limit is global | No — `memory://` is per-instance and resets on replacement | Yes |
| Volumetric DDoS absorption | No | Yes |
| OWASP signatures (SQLi, XSS, LFI, RCE, scanners) | No | Yes |
| Geo and IP policy | Cannot express it | Yes |

## Applying it

```bash
terraform init
terraform plan  -var="domain=api.example.com"
terraform apply -var="domain=api.example.com"
```

`domain` has no default on purpose: a Google-managed certificate cannot be issued
for a `*.run.app` hostname, so a placeholder leaves the certificate stuck in
`PROVISIONING` with no obvious cause.

### The second step is the one that matters

After the load balancer serves traffic and the certificate is `ACTIVE`, lock the
services down so the load balancer is the only way in:

```bash
gcloud run services update vf-logistics --region=asia-southeast1 \
  --ingress=internal-and-cloud-load-balancing
gcloud run services update vf-console --region=asia-southeast1 \
  --ingress=internal-and-cloud-load-balancing
```

`terraform output ingress_lockdown_command` prints these.

**Skipping this makes the whole policy decorative.** Cloud Run's `*.run.app` URL
keeps answering directly, so every rule in `armor.tf` is bypassed by addressing it
— and the WAF looks like it is working while it is not. Do not do the first step
without planning the second.

## Tuning notes

- **OWASP sensitivity is 1 everywhere.** Higher values false-positive on ordinary
  JSON, and this API ingests shipping documents whose cargo descriptions are free
  text — exactly what trips an aggressive SQLi signature. A WAF that blocks real
  shipments gets switched off, which is worse than one tuned low. These rules are
  defence in depth: there is no SQL in this system (Firestore), and the injection
  that actually threatens it is prompt injection, which no WAF signature
  describes — `model_armor.py` and `untrusted.py` handle that.
- **The default rule is `allow`.** The perimeter is not the authorisation
  boundary; the API key and the role floor are, and they live where they can see
  who is asking. Default-deny here would mean maintaining an IP allow-list for a
  public API.
- **Rate limits are deliberately looser than the application's.** The application
  limit is the real budget. These are the backstop for when instances are being
  replaced fast enough that per-instance counters keep resetting.
- **`enable_adaptive_protection` is off.** It requires Cloud Armor Enterprise and
  is billed separately.
- **`blocked_countries` is empty.** A trade compliance API has legitimate
  counterparties nearly everywhere; that list is for whoever knows the customer
  base.
