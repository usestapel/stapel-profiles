# CONFIG.MD — stapel-profiles

Config registry for **stapel-profiles** (`static-scaffold-and-config.md` §2).
One row per configuration key the module reads, its **source** (`env` = the
process environment / the `STAPEL_PROFILES` settings dict), what it is for,
whether it is required, and its default.

Every key is read through `profiles_settings`
(`stapel_profiles.conf.AppSettings`, namespace `STAPEL_PROFILES`). Resolution
order per key: `settings.STAPEL_PROFILES` dict → a flat Django setting of the
same name → environment variable → the default below.

**Every switch here is closed by default, and every one announces itself when
a deployment opens it.** `checks.py` registers `manage.py check` warnings
`profiles.W001`–`W004` for exactly that; a switch nobody can see is a switch
nobody revisits.

## stapel-profiles

| Key | Source | Purpose | Required | Default |
|-----|--------|---------|----------|---------|
| PROFILES_AVATAR_CHECK | env | axis: how `validate_avatar` verifies a CDN reference — `comm` calls `cdn.media_exists`, `off` validates the format only. Fail-closed: an unverifiable reference is rejected. | no | comm |
| PROFILES_FIELDS | env | structural: the profile field-constructor manifest (§66) — identity preset + standard fields + custom field defs. `{}` is the hard core alone. | no | {} |
| PROFILES_BATCH_MAX_IDS | env | ceiling: ids one `POST .../batch` may carry. Over it the request is REFUSED with `error.400.too_many_ids` carrying both numbers — never silently truncated. | no | 100 |
| PROFILES_AVATAR_URL_ALLOWED_SCHEMES | env | boundary: schemes an `avatar_source=url` avatar may use, on import and on read. An active scheme is code, not a picture. | no | [https] |
| PROFILES_AVATAR_URL_ALLOWED_HOSTS | env | boundary: hosts an external avatar may point at. CLOSED by default — without an allowlist every profile view is a beacon carrying the viewer's IP. `["*"]` reopens "any host" as one greppable act. | no | [] |
| PROFILES_REFERRER_POLICY | env | the `Referrer-Policy` this service declares on its own responses; `""` leaves it to the host's middleware. | no | no-referrer |
| PROFILES_PUBLIC_FIELDS | env | policy: what a public lookup exposes to an authenticated caller. Both public endpoints serialize through one class, so they cannot disagree. | no | the full public set |
| PROFILES_PUBLIC_FIELDS_ANONYMOUS | env | policy: what a caller WITHOUT AN ACCOUNT sees (the unsigned internet and a guest session alike). Narrow by default; may only ever narrow `PROFILES_PUBLIC_FIELDS`. `None`/`["*"]` restores "anonymous sees what members see". | no | identity + avatar + seller type + tenure + contacts bit |
| PROFILES_PAIRS_MAX | env | ceiling: pairs one `profiles.relationships` call may carry. Over it the call RAISES — an uncheckable block must fail closed (503), not open. | no | 500 |
| PROFILES_CARD_MEDIA_FUNCTION | env | wiring: the name-addressed CDN read that fills a public card's avatar with render metadata. `""` degrades the card, never fails it. | no | cdn.describe_many |
| PROFILES_LOOKUP_RATE | env | tuning: per-caller ceiling on single public lookups (DRF rate string). `None`/`""` disables it. | no | 120/min |
| PROFILES_BATCH_RATE | env | tuning: per-caller ceiling on batch resolution — deliberately tighter, one request answers for up to `PROFILES_BATCH_MAX_IDS` people. | no | 30/min |
| CONTACTS | env | the seller-contacts block — the module's one NESTED key. Read key by key (host value over default), so a deployment may state one knob without losing the others. See below. | no | see below |

## `STAPEL_PROFILES["CONTACTS"]`

`AppSettings` REPLACES a key's value rather than merging into it. For a scalar
that is right; for a dict of independent knobs it is a trap — stating only
`REVEAL_PER_HOUR` would silently drop the OTP seam. So `contacts_setting()`
merges per key over these defaults, and this is legal:

```python
STAPEL_PROFILES = {"CONTACTS": {"REVEAL_PER_HOUR": 10}}
```

| Key | Source | Purpose | Required | Default |
|-----|--------|---------|----------|---------|
| REVEAL_PER_HOUR | env | ceiling: reveals one VIEWER may perform per hour, spent BEFORE the journal row is written. The ceiling is on the viewer, not on the number — the thing worth stopping is one account walking the catalogue, not many buyers calling one popular seller. Over it: 429 `error.429.contacts_reveal_budget` with `retry_after`. `0` removes the ceiling. | no | 30 |
| POLICIES | env | axis: the policy vocabulary this deployment offers, in picker order; the first entry is the default for a new contact. Narrowing it to `["verified", "nobody"]` makes every published number require a verified account. A name this module does not implement is ignored — a policy accepted at the write boundary and enforced by nothing at the read one is worse than no policy. | no | [members, verified, nobody] |
| OTP_PROVIDER | env | seam: dotted path to the phone-verification provider — `send_verification_code(phone)` + `verify_code(phone, code)` with stapel-auth's envelopes. Defaults to stapel-auth's phone service; when that module is not installed the built-in `contacts.otp.CoreOneTimeCodeProvider` takes over. An explicitly configured path that cannot be imported RAISES — only the default falls back. | no | stapel_auth.otp.services.PhoneVerificationService |

## Host settings this module reads (not its own namespace)

| Setting | Why |
|---|---|
| `LANGUAGES` | a declared language list materialises `Language` rows on its own (`models.ensure_declared_languages`); without it the picker is whatever `sync_languages` seeded. |
| `CACHES["default"]` | the public-lookup throttles and the contacts reveal budget are cache-backed counters. A deployment with no shared cache gets per-process ceilings. |
| `STAPEL_NETINTEL["TRUSTED_PROXY_HEADER"]` | how `stapel_core.netintel.client_ip` reads the viewer IP written into the reveal journal. Behind a proxy that does NOT overwrite the header, leave it unset — any client can spoof `X-Forwarded-For`. |
| `STAPEL_GDPR["DATA_OWNERS"]` | must contain `{"profile": ["account"]}` for the erasure/probe path to be consumed. |
