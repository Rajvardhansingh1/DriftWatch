# Supabase Auth settings (project "DriftWatch")

Verify each item in Dashboard > Authentication. Re-check after any project change.

| Setting | Value | Why (finding) |
|---|---|---|
| Confirm email | ON | B1: no key or free quota before a verified email |
| Minimum password length | 10 | B2 |
| Leaked password protection (HIBP) | ON | B2 |
| Password requirements | letters and digits | B2 |
| Site URL | https://<prod-domain> | B3 |
| Redirect URLs | exact `https://<prod-domain>/auth/callback` and `http://localhost:3000/auth/callback`; no host wildcards | B3 |
| JWT expiry | 900 seconds | A5, B5: short-lived tokens |
| Refresh token reuse detection | ON | B5 |
| Rate limits (sign-in, sign-up, OTP, refresh) | defaults or stricter | B1, B2 |
| MFA (TOTP) | enabled | B2: required for platform admins |
| Anonymous sign-ins | OFF | B1 |
| CAPTCHA (Cloudflare Turnstile) | ON, **only after** the widget is deployed with `NEXT_PUBLIC_TURNSTILE_SITE_KEY` set on Vercel | B1. Turning it on first locks everyone out (R3). |

GitHub disables scheduled workflows after 60 days of no repository activity; the keep-alive workflow then stops and Supabase pauses an idle free project after 7 more days. Push, or re-enable the workflow, at least every 8 weeks.

Verified on: ____ by: ____
