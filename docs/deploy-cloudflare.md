# Putting butterfly.buckstoplabs.com online

No load balancer, no IAP, no certificate to provision. Cloudflare proxies the
hostname straight to Cloud Run and handles both TLS and sign-in.

Running total: **about $0.11/month.** Cloud Run scales to zero, Cloudflare
Access is free to 50 users, and the only standing charge is a few cents of
container storage.

**Origin:** `butterfly-23242k5uhq-uc.a.run.app`

---

## 1. Open the service to Cloudflare — two commands, run these yourself

The service is currently locked to load-balancer ingress and rejects
unauthenticated callers, which is why the origin returns 404. Cloudflare has to
be able to reach it:

```bash
gcloud run services update butterfly \
  --project=butterfly-buckstoplabs --region=us-central1 --ingress=all

gcloud run services add-iam-policy-binding butterfly \
  --project=butterfly-buckstoplabs --region=us-central1 \
  --member=allUsers --role=roles/run.invoker
```

The second one is what my tooling declined to run for you, and it is worth
understanding rather than pasting blindly: it makes the `run.app` URL
answerable by anyone. Sign-in then happens at Cloudflare's edge, not at Cloud
Run. Section 5 closes that gap if you want it closed.

## 2. DNS

Cloudflare dashboard → **buckstoplabs.com** → DNS → Records → Add record.

| Field | Value |
|---|---|
| Type | `CNAME` |
| Name | `butterfly` |
| Target | `butterfly-23242k5uhq-uc.a.run.app` |
| Proxy status | **Proxied** (orange cloud) |

Proxied is required here — Access only protects traffic that passes through
Cloudflare. This is the opposite of what the load-balancer setup would have
needed, so ignore any earlier note about grey-clouding it.

## 3. Host header rewrite

Cloud Run decides which service answers by looking at the `Host` header. It
will not recognise `butterfly.buckstoplabs.com` and will return 404 until this
rule exists.

Rules → **Origin Rules** → Create rule.

- **When incoming requests match:** Hostname equals `butterfly.buckstoplabs.com`
- **Then:** Host Header → Rewrite to → `butterfly-23242k5uhq-uc.a.run.app`

Then SSL/TLS → Overview → set encryption mode to **Full (strict)**. Cloud Run
presents a valid certificate, so strict costs nothing and stops the hop from
Cloudflare being plaintext.

At this point the site should load, unprotected.

## 4. Sign-in

Zero Trust dashboard (`one.dash.cloudflare.com`) → Access → Applications →
**Add an application** → Self-hosted.

- **Name:** Butterfly
- **Public hostname:** `butterfly.buckstoplabs.com`
- **Session duration:** 24 hours

Then add a policy:

- **Name:** Owner
- **Action:** Allow
- **Include:** Emails → `mark.francis.young@gmail.com`

For the login method, **One-time PIN** needs no setup at all — Cloudflare
emails a code. Google SSO is nicer to use but wants an OAuth client configured
first under Settings → Authentication. Start with the PIN; switching later
changes nothing else.

Streamlit holds a websocket, and Access is fine with that as long as the
session outlasts the tab.

## 5. The gap this leaves

Access guards the hostname. It does not guard
`butterfly-23242k5uhq-uc.a.run.app`, which step 1 made publicly answerable —
anyone who learns that URL skips the sign-in entirely. It is unguessable but
not secret; it appears in Cloud Run's console and in any request log.

To close it, have Cloudflare attach a header no one else sends and make the app
require it:

- Rules → **Transform Rules** → Modify Request Header → Set static
  `X-Butterfly-Key` to a long random string, when hostname equals
  `butterfly.buckstoplabs.com`
- Set the same value as a Cloud Run env var, and reject requests without it

Worth doing before the site holds anything you would not hand to a stranger.
Right now it holds public appraisal records, so it is a judgement call rather
than an urgent one.
