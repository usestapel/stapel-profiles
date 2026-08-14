# Changelog

## [Unreleased]

### Added — the avatar URL boundary, a public visibility policy, enumeration limits

Security audit PROFILE-01: the avatar was a free-form user-controlled value
handed to every consumer, and the public profile surface had no written-down
answer to "what does it expose" or "how much of the user base may one caller
walk".

- **URL boundary.** `avatar_source=url` is accepted only for the schemes a
  deployment allows (`PROFILES_AVATAR_URL_ALLOWED_SCHEMES`, https by
  default) and only from allowlisted hosts
  (`PROFILES_AVATAR_URL_ALLOWED_HOSTS`); `avatar_source=gravatar` must be an
  email hash, not a path interpolated into a gravatar URL. The read path
  holds the same line: a stored value today's policy would refuse is no
  longer emitted (it degrades to "no avatar"), so a legacy row cannot turn
  into a write failure and cannot reach a client either. New keys
  `error.400.avatar_url_scheme`, `error.400.avatar_url_host`,
  `error.400.avatar_gravatar_hash` (en/ru/es).
- **Referrer policy.** Profile responses declare `PROFILES_REFERRER_POLICY`
  (default `no-referrer`); MODULE.md states the client half of the contract.
- **Public visibility policy.** `PROFILES_PUBLIC_FIELDS` and
  `PROFILES_PUBLIC_FIELDS_ANONYMOUS` (may only narrow) govern what
  `GET .../<user_id>` and `POST .../batch` expose — both go through one
  serializer, so the two doors cannot disagree. The member-facing default is
  the historical field set; the anonymous default is narrower (see below).
- **Enumeration limits.** Per-caller throttles over the existing batching
  cap: `PROFILES_LOOKUP_RATE` (default `120/min`) and the deliberately
  tighter `PROFILES_BATCH_RATE` (default `30/min`), keyed by user when
  authenticated and by IP otherwise; `None` switches one off.

### Changed — two permissive defaults closed (UPGRADE NOTE)

Follow-up to the 2026-08-11 audit. Both switches above shipped open, which
means the safe value was the one nobody had chosen yet. They are now closed
by default, and opening them is an explicit, greppable act. **Both can change
what an existing deployment returns — read this before upgrading.**

- **External avatar hosts are refused unless allowlisted.**
  `PROFILES_AVATAR_URL_ALLOWED_HOSTS` still defaults to `[]`, but `[]` now
  means "no external host is trusted" instead of "any host". An
  `avatar_source=url` avatar is refused on write (`error.400.avatar_url_host`)
  and suppressed on read (`avatar_image` degrades to `null`; the raw `avatar`
  string is untouched in the database) until the deployment names the hosts
  it trusts. Rationale: without an allowlist every profile view fetches an
  image from a host the profile's OWNER picked — a cross-site beacon carrying
  the VIEWER's IP, user agent and referring page.
  *Upgrade:* list your hosts — `STAPEL_PROFILES = {"PROFILES_AVATAR_URL_ALLOWED_HOSTS": ["cdn.example.com", ".example.com"]}`.
  *Opt-out restoring the old behaviour:* `["*"]` (any host), stated once and
  findable by grep. `avatar_source=cdn`/`file`/`gravatar` are unaffected.

- **Anonymous callers get a narrower field set.**
  `PROFILES_PUBLIC_FIELDS_ANONYMOUS` now defaults to
  `["user_id", "display_name", "avatar_source", "avatar", "avatar_image"]`
  instead of `None` ("the same as members"). `GET .../<user_id>` and
  `POST .../batch` are `AllowAny` and answer for any user id, so the old
  default let the open internet walk the member directory for coarse AND
  narrow location plus follower/following counts; throttles bound the rate,
  not the content. `relationship_status` is also gone for anonymous callers —
  it has no meaning without a viewer. Authenticated callers are unaffected.
  *Upgrade:* clients that render location or follow counts for logged-out
  visitors must either authenticate or the deployment must widen the list.
  *Opt-out restoring the old behaviour:*
  `STAPEL_PROFILES = {"PROFILES_PUBLIC_FIELDS_ANONYMOUS": None}` — or `["*"]`
  where a flat setting / env var cannot carry `None`.

The emitted OpenAPI contract is unchanged: it describes the endpoints'
declared surface (the member policy), not one caller's subset.

### Added — `checks.py`, so an opened switch is never silent

`manage.py check` now reports every security switch a deployment has opened
(same genre as `stapel_gdpr.checks` W003 / `stapel_cdn.checks`). Warnings,
not errors — a host is allowed to open them, it just may not do so quietly:
`profiles.W001` (`PROFILES_AVATAR_CHECK="off"` — an avatar reference stored
without confirming the CDN object exists), `profiles.W002`
(`PROFILES_AVATAR_URL_ALLOWED_HOSTS=["*"]`), `profiles.W003` (anonymous
callers given the full member field set) and `profiles.W004`
(`PROFILES_LOOKUP_RATE` / `PROFILES_BATCH_RATE` disabled, so one caller may
enumerate the user base as fast as the service answers).

## [0.12.5] — 2026-08-10

### Fixed — the error reference is gated as reproducible, not merely as present

0.12.4 dropped the 41 core-owned duplicates from `translations/errors.{ru,es}.json`
and shipped. What it could not know: `build_error_docs` read this module's
`translations/` directory and nothing else, while the reference it renders
covers the whole registry — so `docs/errors.ru.md` was correct only because it
had been generated *before* the prune. Regenerating it produced **41 of its 53
rows in English** (`_(en)_` fallbacks), and nothing would have said so:
`test_error_docs_exist_for_every_language` reads the committed file, which was
green.

stapel-core 0.23.1 fixes the reader — `module_catalog` resolves a key this
module does not own from its owner's catalog — so a fresh regeneration is once
again byte-identical to the committed reference (verified: 53/53 ru rows in
Russian, zero `_(en)_`). `test_error_reference_matches_a_fresh_regeneration`
now compares those bytes on every run, so a committed reference can no longer
be green while being unreproducible.

The `stapel-core` pin moves to `>=0.23.1`. It was `>=0.16`, under which 0.12.4's
pruned catalogs resolve to **English at runtime** — the pin, not just the docs,
was the part 0.12.4 left behind.


All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.12.4] — 2026-08-10

### Fixed — this module translates only the error keys it owns

stapel-core 0.22.0 ships its own error catalogs and the loader merges the
owner's, so the 41 core-owned keys duplicated in `translations/errors.ru.json`
and `errors.es.json` were a second, drifting copy — the new catalog gate calls
them `foreign` and fails on them, which is what took 0.12.3's release build
down. Dropped them, and scoped the coverage test to the keys this module owns
(`owned_keys` / `owner_of_dir`). Ships 0.12.3's picker fix, which never
reached PyPI.

## [0.12.3] — 2026-08-10

### Fixed — the language picker is no longer empty either

0.12.2 made a declared language *writable*; the settings screen still had
nothing to offer, because `GET /languages/` lists `Language` rows and the
table is only ever filled by `manage.py sync_languages`. Half a fix: a user
cannot state a preference they are never shown.

`ensure_declared_languages()` materialises a row for every code the project
declared, called from the language list. "Declared" means the project set
`LANGUAGES` itself — Django's 100-entry default is not a claim anybody made,
so an unconfigured project keeps the old behaviour exactly (only seeded rows).
Best-effort: a read-only replica or a race degrades to "show what rows
exist", never to a 500 on the settings screen. `sync_languages` remains the
way to get flags and curated names.

## [0.12.2] — 2026-08-10

### Fixed — a language the deployment declares can actually be chosen

`app_language` and `understands` validated writes against the `Language`
reference table alone, which is populated by `manage.py sync_languages`. So
whether a user could state their language depended on whether anybody had
ever run that command — and nothing anywhere said so. A deployment that
declared `LANGUAGES = [("ru", …), ("en", …)]` and never ran it served an
empty picker (the read side already intersects with `settings.LANGUAGES`)
and answered 400 `does_not_exist` to every write.

Measured on the meettoday sandbox, 2026-08: 0 `Language` rows, 0 of 66
profiles with an `app_language`, and `PATCH {"app_language": "en"}` rejected
as nonexistent while `settings.LANGUAGES` declared exactly `en`. That is
the answer to "did nobody choose, or could nobody choose": **nobody could**.
Downstream, every notification had to guess at its recipient's language.

`LanguageCodeField` now accepts any code the deployment declares and
materialises its row on first use (name from `settings.LANGUAGES`; flags
remain a `sync_languages` concern). Existing rows keep working unchanged and
an undeclared code is still rejected — this widens what a write may say,
never narrows it.

## [0.12.1] — 2026-08-10

### Added — `profiles.language`: ask the owner instead of mirroring the field

A sibling that needs to know which language a user reads in now asks by name:

    call("profiles.language", {"user_id": str(user_id)})
    # -> {"app_language": "en", "auto_detected_language": "ru"}

Two facts, kept apart because a caller ranks them differently — the language
the user **chose** in their language settings, and the one merely **observed**
from an Accept-Language header. Both `null` when absent, including for a
`user_id` with no profile row at all: that is the normal state of an invitee
who has not accepted an invitation yet, and it is an *answer*, not a failure.

The alternative is what it replaces. stapel-notifications mirrored
`app_language` into a local table fed by a bus consumer, and the mirror was
empty for its entire lifetime — 0 rows against 66 profiles on the meettoday
sandbox — for two independent reasons: a monolith on the in-process bus cannot
run a standalone consumer at all (core 0.14.2 now refuses instead of
restart-looping), and the consumer listened on `stapel.profiles.profile-changed`
while the comm plane publishes under the action name `profile.changed`. The
consequence was invisible because a mirror answers `None` both for "the user
chose nothing" and for "the sync never ran", and every notification fell
through to the language of whoever *triggered* it. A call cannot hide that: it
either answers or raises.

Swap-aware like the rest of this module's comm surface (`get_profile_model`),
and a profile model carrying neither field answers `null`/`null` with a
warning rather than raising — "this deployment holds no stated language for
anybody" is a legitimate answer. Contract:
`schemas/functions/profiles.language.json`.

## [0.12.0] — 2026-08-09

### Fixed — the avatar/avatar_source pair can no longer be stored inconsistently

`avatar` and `avatar_source` are one value in two columns, and nothing held
them together. `validate_avatar` only checked the reference when the source
ALREADY said `cdn` — exactly the case that was already correct — so a client
that PATCHed `{avatar: "avatar/<hash>"}` without a source got the model default
(`file`) written next to a CDN ref, silently.

On the meettoday sandbox that was not an edge case. **2 of 2** profiles that
had ever set an avatar were stored this way, on two different people — a 100%
failure rate of the manual upload path. Serializing such a row routed the ref
to the PIL provider, which opened stapel-cdn's variant DIRECTORY as a plain
file and raised: `GET /profiles/api/v1/me` and `POST /profiles/api/v1/batch`
both 500'd. The frontend then read no `display_name`, concluded the account was
unnamed, blocked the meeting door with an "enter your name" dialog, and that
dialog's PATCH re-serialized the same avatar and 500'd again. A cosmetic
reference locked two people out of the product.

The rule is stated once and enforced twice:

- **Model** — `is_cdn_avatar_reference` / `resolve_avatar_source`: an
  `avatar/<64-hex>` reference is produced by exactly one writer in the fleet,
  so it is self-describing. `ProfileCore.save()` writes the source the
  reference implies (widening `update_fields` so a partial save cannot drop the
  repair) and logs the correction at WARNING; `clean()` rejects the pair for
  callers that validate. Every writer — admin, shell, data migration,
  `update_or_create` — passes this gate.
- **Serializer** — a request that STATES a source the reference contradicts is
  refused with the new `error.400.avatar_source_mismatch`, because coercing an
  assertion hides the caller's bug. A request that states nothing has the
  source derived and returned in the response body: there is no assertion to
  correct, and refusing would turn a cosmetic defect into a write failure on
  unrelated fields — the escalation this incident was.

Deriving server-side is the NET. The MECHANISM is `@stapel/profiles-react`
0.15.0, where `useAvatarUpload().upload()` now resolves `{ref, source}` instead
of a bare string and `useSetAvatar()` makes setting an avatar one operation —
the provenance is transported from the one place that knows it, rather than
inferred later.

Pairs with the `stapel_core.media` fix (0.20.1) that stops any unresolvable
reference from raising out of `image()` in the first place.

### Fixed — contract drift that made 0.11.0 unpublishable

0.11.0 bumped `pyproject.toml` without regenerating `docs/capabilities.json`,
which embeds the version. The drift gate failed, the tag built nothing, and
0.11.0 does not exist on PyPI — its Spanish catalogue ships here instead.

## [0.11.0] — 2026-08-09

### Added — Spanish ships as a language of the library, not as a host override

`translations/errors.es.json` (52 keys) + `docs/errors.es.md`, generated by the
same contour that produces Russian — no hand-written JSON, no product-side
override file. 49 values are lifted verbatim from the curated
`stapel-translate` builtin corpus (`origin: seed:stapel-builtin`), which is what
"clients don't spend tokens" means in practice: the corpus was paid for once.
The remaining 3 are machine translations of this module's own keys, recorded
`origin: llm` — **unreviewed**, and counted as such by the gate now that
stapel-core 0.20.1 stopped treating a curated corpus as human sign-off. Nobody
has read these; `translate_catalogs --approve` is the state transition that
changes that, and it has not been run.

Register and terminology follow the corpus rather than being invented per
module: informal *tú* address, *espacio de trabajo*, *llave de acceso*, *nombre
para mostrar*.

The harness in `tests/test_error_i18n.py` is now language-generic — a language
is a tag in `LANGUAGES` plus whatever the corpus does not carry, and the
catalog, the provenance sidecar, the reference page and the gate all follow.
Adding the next language is not a second copy of this work.

### Fixed — the translation catalogs were built into the wheel and then left out of it

`translations/errors.ru.json` has been in this repository since the i18n wave,
and it has never reached anyone who installed the package. `[tool.setuptools.package-data]`
listed `schemas/`, `migrations/`, `docs/` — and not `translations/`, so setuptools
dropped the directory on the way into the wheel. Verified by installing the built
wheel into an empty virtualenv: no `translations/` under the installed package,
and `load_app_catalogs()` therefore found nothing to merge. Every host running
this module in Russian was silently reading the English canon.

`translations/*.json` is now declared, and the check is the install, not the
manifest: the wheel is built, installed into a clean virtualenv, and the
catalogs are listed on disk.

## [0.10.0] — 2026-08-09

### Added — profiles publishes its name surface as comm Functions

Until now this module's "Provides (function)" row read `—`: a sibling that
needed a name had nothing to call by name. stapel-workspaces 0.19.0 filled
that gap the only way left to it — asking Django's app registry whether
`stapel_profiles` runs in this process and then resolving
`stapel_profiles.validators.validate_display_name`,
`stapel_profiles.models.get_profile_model` and
`stapel_profiles.events.publish_profile_changed` **by dotted path**. That
worked where profiles was co-mounted and nowhere else: in a split
deployment the roster's name-edit endpoint answered a permanent
`error.503.profiles_unavailable`. It was also the fleet's only cross-module
symbol resolution. The fix belongs here, not there — the data owner
publishes the operation (`tasks/who-owns-the-name-write.md`):

- **`profiles.set_display_name`** — payload `{user_id, display_name}`, result
  `{ok, display_name, reason}`. The named write of the canonical name,
  performed by profiles on another module's authority, exactly as
  `billing.debit` lets workspaces move credits in billing's ledger: the
  caller's edge already authorized the act, and the owner enforces its own
  invariants — the `validate_display_name` canon, the swap-aware
  `get_profile_model` (SWAP001), get-or-create, and the `profile.changed`
  emission every downstream projection depends on. Refusals are
  **structural** (`ok=False` + `reason`), never exceptions: `reason` is the
  trailing name of this module's own error keys (`display_name_emoji` →
  `error.400.display_name_emoji`), so a caller re-declaring those keys maps
  one to one instead of minting a second name vocabulary. No idempotency key
  — the write is last-write-wins on one field, so at-least-once delivery is
  harmless.
- **`profiles.validate_display_name`** — payload `{display_name}`, result
  `{ok, reason}`. The canon alone, no write, for a caller that stores a
  *displayed* name of its own (workspaces' `WorkspaceInvitation.display_name_hint`
  is the first) and must not grow a second, weaker regex.
- **`profiles.display_names`** — payload `{user_ids}`, result
  `{display_names: {user_id: name}}`. The comm form of `POST /batch`
  narrowed to the field a roster needs, with the same "missing is not
  invented" contract: an id with no row, or an empty name, is absent.

Registered from `apps.ready()`; payload contracts committed under
`schemas/functions/`. No HTTP surface changed, no migration, nothing
removed — a deployment that calls none of these is byte-for-byte unaffected.

## [0.9.1] — 2026-08-02

### Changed — packaging/CI only, no runtime change

- Badge canon + Python 3.14 trove classifier.
- `docs/llms.txt` — the fifth contract artifact (badge-canon §3): the
  module's own context slice for an agent, rendered from
  `capabilities.json` + the contract triad, regenerated by `make contract`
  and checked by the drift gate alongside the existing triad; now shipped
  inside the wheel (`package-data`).
- `package-data` also picks up `docs/capabilities.json`, `docs/flows.json`,
  `docs/errors.json` and `CONFIG.MD` (#184) — a module whose contract
  documents stayed repo-only was publishing code an agent in an installed
  environment could not see.

## [0.9.0] — 2026-07-30

### Changed — every view says, in its own source, what a guest may do (#168)

`stapel-core` 0.16 turns the `AUTH_ANONYMOUS` axis into a question this module
never answered. A guest session is `is_authenticated`, so a bare
`IsAuthenticated` gate lets it through — and nine views here were gated on
exactly that. Nothing in the source said whether that was wanted, which meant
a consumer reading this module could not tell an open door from an oversight.
`stapel_core.adoption` W002 reported all nine against a real deployment.

They now answer, and the answer is one rule:

> **a guest may see the social graph, and may not write to it.**

- **Reads stay open, deliberately.** `GET /me`, `/me/followers`,
  `/me/following`, `/me/blocked` and `/{user_id}/relationship` are scoped to
  `request.user.id`, so a guest's answer is their own — an empty list, or
  `neutral`. That empty answer is the truth and is what a frontend wants when
  it renders a "Follow" button for a visitor who has not registered; a 403
  would only make it render an error. Declared
  `stapel_anonymous_access = ANONYMOUS_ALLOWED`.
- **`GET`/`PATCH /me` is load-bearing for guests, not merely tolerated.** It
  is the view a guest uses to name themselves *before* joining a call in
  meettoday. Closing it would have broken a product in production, mid-call.
  Its declaration is now the line that stops that from happening by accident.

### Changed (BREAKING for anonymous callers) — follow/block require a real account

`POST /{user_id}/follow`, `/unfollow`, `/block`, `/unblock` now carry
`IsNotAnonymousUser`: an anonymous session gets **403** where it previously
got 200. A follow or a block is a durable `UserRelationship` edge and an
anonymous account is throwaway by construction — the edge outlives the session
that minted it, with nobody left who can undo it. A block is the worse half: a
moderation decision no one can revisit.

Minor, not patch: for a deployment with `AUTH_ANONYMOUS` on, this is a
behaviour change on a live surface, and it is visible in the published
contract (`docs/schema.json` now documents `IsNotAnonymousUser` on those four
operations). Deployments without guest sessions are unaffected — an ordinary
authenticated user passes `IsNotAnonymousUser` exactly as before.

### Changed

- Minimum `stapel-core` raised to `>=0.16` (the release that added
  `ANONYMOUS_ALLOWED` / `ANONYMOUS_DENIED`).

## [0.8.0] — 2026-07-30

### Added — `POST /profiles/api/v1/batch`: many public profiles in one request (#111)

A 16-tile contact grid fired 16 `GET .../<id>` calls and took a **404 for
every person who had never opened settings** — sixteen red console lines for a
screen working exactly as designed. Two things were wrong: the fan-out, and
calling a normal state an error. The second is the one that mattered.

**Why POST with a body, not `GET ?ids=`.** A people grid resolves 50-100 UUIDs
at once — 1.9-3.7 kB of them, past the conservative 2 kB URL ceiling old
proxies/WAFs still enforce and into nginx's default 8 kB request-line budget
once a JWT cookie rides along. A 414 there would read to the user as "the
profile service is down", the exact failure this endpoint exists to remove. A
body also keeps the roster of who is being looked at out of access logs and
`Referer` headers. POST is the transport, not the semantics: the call changes
nothing and is safe to repeat, and giving up HTTP caching costs nothing —
the caller batches precisely *because* it keeps its own per-id cache.

**Missing is not an error.** The answer is `{profiles, missing}`:

* id in `profiles` — there is a profile, here it is;
* id in `missing` — asked, none exists: render the placeholder, cache the
  negative, do not retry, nothing is broken;
* id in neither — it was not part of this request.

The two lists always cover the de-duplicated input exactly, so "absent" is
never a guess. Nothing is invented for a missing id — a filled-in stub would
be this service asserting a display name for a person who never chose one.
Status is `200` in every case, including all-missing.

**The ceiling refuses, it does not truncate.** New `PROFILES_BATCH_MAX_IDS`
(default 100). Over it the request is rejected with the new
`error.400.too_many_ids` carrying **both** numbers (`requested`, `limit`) so a
caller can chunk deterministically. A silent truncation would answer 200 with
a short list and the UI would render the overflow as people who "have no
profile" — a wrong answer delivered as a successful one, with nothing
anywhere saying part of the question was dropped. The count is taken on the
payload as submitted, before de-duplication and before UUID parsing: the
ceiling bounds what the caller sends (a limit that "sometimes lets 150
through" is not one anybody can code against), and a 10k-id body costs no
parses to reject.

`_batch_social_context()` precomputes `followers_count` / `following_count` /
`relationship_status` for the whole page, so the query count is flat in page
size — otherwise a 50-profile batch would have traded 50 HTTP round-trips for
150 SQL queries. Pinned by a test.

### Fixed — the `user.registered` `display_name` hint was read and thrown away (#149)

`actions.handle_user_registered` pulled only `avatar_url` out of the payload,
so the name an org admin typed while provisioning a login never reached the
profile: onboarding always opened on a blank field even though `stapel-auth`
had been shipping `display_name` in the event for a while.

The hint is a **pre-fill, not an assignment** — the owner of a name is the
person it names, never the person who invited them. So the write is guarded
twice, not once. "The stored name is empty" alone is **not** the guard:
delivery is at-least-once, so a user who deliberately *clears* their name
would get the admin's version resurrected by the next redelivery. The pre-fill
therefore also stops at the onboarding boundary (`initial_setup_passed`) —
past setup the name is the human's, empty included, and a late hint is a
no-op.

The hint is untrusted cross-service input, so it is held to this module's own
name canon (`validate_display_name` + the model's `max_length`); a failing
hint is **declined and logged**, never truncated or sanitised into something
the admin did not type, and a whitespace-only hint conjures no profile row at
all. Handled before the avatar import and independently of it: a cosmetic
network failure must not cost the account its name.

Not a patch: the subscriber now writes a field it previously left alone.

## [0.7.3] — 2026-07-26

### Added — `error-keys/` is finally mounted

`ProfilesErrorKeysView` has existed since the port but no `urls*.py` ever mounted it — in
*any* stapel library. stapel-translate's `error_collector` polls
`/{prefix}/api/v1/error-keys/` on every service, so the whole endpoint class
answered 404 from Django's URL resolver and the collector harvested nothing
while reporting a plain `HTTP 404`. It is now mounted in `urls_v1.py` at
`error-keys/` (v1 canon), service/staff-gated as the base view declares.

Deliberately **not** in the contract triad: `ErrorKeysView` sets
`schema = None` and `/error-keys` is on the flows allowlist, so `make
contract` is a no-op diff — this is infrastructure, not product surface.

## [0.7.2] — 2026-07-24

### Fixed — `docs/capabilities.json` version drift (0.7.1 never published)

0.7.1's tag was cut before `docs/capabilities.json` was regenerated against
the bumped `pyproject.toml` version, so CI's contract-drift gate correctly
failed the release on `test_capabilities_envelope` (envelope said 0.7.0,
`pyproject.toml` said 0.7.1) before the package ever built — nothing named
0.7.1 reached PyPI. This release is otherwise identical to 0.7.1.

## [0.7.1] — 2026-07-24

### Fixed — `PATCH /me` silently dropped `display_name`/`theme`

`ProfileCreateUpdateSerializer` (the write side of `/me`) never got
`display_name`/`theme` added to its `fields` when 0.7.0 moved them back into
the `ProfileCore` hard core — only the READ serializer (`ProfileSerializer`)
picked them up. A `PATCH /me` carrying either field validated fine (DRF
silently drops unknown keys) and returned 200, but never wrote the columns —
confirmed against the DB. `ProfileUpdateRequest` (the OpenAPI doc dataclass)
had the same gap; both now declare the two fields, contract regenerated.

## [0.7.0] — 2026-07-22

### Changed — `display_name` + `theme` back in the hard core (partial §66 reversal)

Owner directive 2026-07-22: every product wants a name to show and a
light/dark toggle, and making agents/scaffolds opt into them through the field
registry was friction with no upside. `display_name` (was an identity preset)
and `theme` (was a standard field) are now plain `models.ProfileCore` fields —
present on every profile (default and swapped), serialized on `/me` and the
public profile. `currency_code`/`measurement_units`/`geohash` stay opt-in in
the registry; `first_last_name` remains the one identity preset. Migration
`0017` adds the two columns. Frontends can still hide either field in the
default skin per host — "in the default" is not "forced on screen".

## [0.6.0] — 2026-07-22

### Added — `avatar_image` (renderable descriptor next to the raw ref)

`ProfileResponse` (`/me`) and the public profile now carry `avatar_image`: a
source-agnostic `StapelImage` (`stapel_core.media.image`) denormalized from
`avatar` + `avatar_source`, so a frontend `<Image>` renders the right ladder
tier + blur-up without a second round-trip. The raw `avatar` ref stays writable
for the upload round-trip. `AvatarSource` maps onto the core sources — CDN→cdn
(routed to the CDN provider so its own variant naming is read, the fix for the
empty-ladder avatar gap), FILE→file, URL→link, GRAVATAR→link.

### Changed

- Requires `stapel-core>=0.13` (the `StapelImage` descriptor lives there).

## [0.5.0] — 2026-07-17

### Changed — BREAKING: Profile = constructor (§66, docs/pending/profile-fields.md)

Owner GO (2026-07-17): the hard `Profile` model shrinks to a core every
project needs regardless of domain — `user_id`, avatar (now `avatar_source`
+ `avatar`, prep for §67's source+ref cdn/gravatar/url/file model), the
whole language block, notifications, location, consent, onboarding,
timestamps. `theme`, `currency_code`, `measurement_units` and identity
(`display_name` / `first_name`+`last_name`) leave the hard model —
deletion-driven, one alpha-cut migration, no compat shim (pre-1.0 policy).

- **`field_defs.py`** (new): `STANDARD_FIELDS` / `IDENTITY_PRESETS` registry
  — `ProfileFieldDef` (mandatory docstring), `ProfileFieldKind`,
  `StapelProfileEnum`, `Theme`, `MeasurementUnit`; `assemble_profile_fields()`
  and `build_profile_model()` let a project assemble its own extended
  `Profile` subclass (standard fields + an identity preset + its own custom
  `ProfileFieldDef`s) in its OWN app.
- **`STAPEL_SWAP["PROFILES_PROFILE_MODEL"]`** (new): the first real
  `get_model()` case in the framework — `models.get_profile_model()` is now
  the only sanctioned way any internal code (views/serializers/admin/gdpr/
  events/actions/management commands) reaches the Profile DAO; a project's
  extended model is swapped in by dotted path, no fork required.
- **`GET /profiles/api/v1/field-manifest/`** (new): the active field
  manifest (`STAPEL_PROFILES["FIELDS"]` / `PROFILES_FIELDS`) as
  `[{name, kind, enum_values?, docstring, required, order}]` — the canon
  source for a data-driven frontend skin (owner addendum 17.07, tier 1 of
  the two-tier front-pair answer).
- `avatar` is now source+ref: `avatar_source` (`file` default | `url` |
  `gravatar` | `cdn`) + `avatar` (free-form string, format/existence
  validation applies only when `avatar_source=cdn`). The §67 system check
  for "source=cdn but no cdn service configured" is out of scope here.
- Migration `0016_field_constructor_alpha_cut` (marked `# stapel:
  contract-phase`): removes `display_name`/`currency_code`/
  `measurement_units`/`theme`, adds `avatar_source`, converts `avatar` to a
  plain `CharField`, and detaches the language FK/M2M `related_name`s (now
  `"+"`, since two concrete Profile models may coexist across an app).

## [0.4.5] — 2026-07-17

### Fixed — `GET /languages/` now reflects the project's own configured languages

Owner UX audit (miттудей settings screens, point 5): the endpoint returned
every `Language` row with `is_active=True` regardless of what the PROJECT
actually supports — since `is_active` defaults `True` and nothing seeds/syncs
the table automatically (`sync_languages` is a manual management command),
a deployment that never ran it got an EMPTY list (the frontend then fell
back to showing just the current language, e.g. a single "EN" — the exact
symptom reported), and one that did got the full global fixture (33
languages) regardless of project scope.

- `LanguageViewSet.get_queryset()` now additionally intersects
  `is_active=True` with the project's own `django.conf.settings.LANGUAGES`
  (the standard Django i18n axis) when configured — a project with
  `LANGUAGES = [("en", …), ("ru", …)]` gets exactly those two. A project that
  never touched `LANGUAGES` still gets Django's own large built-in default —
  a permissive no-op, not a behavior change.
- Kept a static `queryset` class attribute alongside `get_queryset()` solely
  so drf-spectacular still introspects the PK field (`code`) correctly for
  the `retrieve` path parameter — dropping it silently renamed the generated
  `{code}` path param to a generic `{id}`.

## [0.4.4] — 2026-07-17

### Fixed — currency default drift: EUR → USD (docs + model)

`Profile.currency_code` still defaulted to `'EUR'` (and every doc/test
example mirrored it), even though the workspace-wide currency default
moved to USD (2026-07-08, `stapel-currencies`/`stapel-listings`
`BASE_CURRENCY`). `test_matches_monolith_profiles_slice` caught the
resulting drift against the monolith's own already-USD schema slice.

- `Profile.currency_code` default `'EUR'` → `'USD'` (migration 0015;
  `help_text` example order flipped to lead with USD).
- `docs/schema.json` / `dto.py` docstrings / tests regenerated and updated
  to match — `make contract` re-run after the version bump (0.4.2/0.4.3's
  known gotcha: `docs/capabilities.json` embeds the package version, so
  bump first or regenerate again).
- `test_matches_monolith_profiles_slice` verified green with no skip hatch.

## [0.4.3] — 2026-07-17

Fix-up #2: 0.4.2's regen still baked the old version into
`docs/capabilities.json` (`make contract` ran before the version bump
landed). Re-ran with 0.4.3 already in `pyproject.toml`; verified match,
suite green.

## [0.4.2] — 2026-07-17

Fix-up: 0.4.1's CI/publish failed on contract drift — `docs/capabilities.json`
embeds the package version and wasn't regenerated for the 0.4.1 bump.
Regenerated via `make contract`; no other diff.

## [0.4.1] — 2026-07-17

Fleet follow-up to stapel-core 0.12.0 (legacy shim sweep). No source
changes needed — the one `stapel_core.kafka` import
(`management/commands/publish_all_profiles.py`) uses `EventType`/`TOPIC_*`,
which core 0.12.0 keeps. Full suite green against core 0.12.0.

### Changed
- `stapel-core` dependency ceiling `<0.12` → `<0.13`.

## [0.4.0] — 2026-07-17

### Removed
- **Breaking:** legacy `PROFILES_AVATAR_CHECK = "http"` mode (direct HTTP
  avatar-existence check via `check_cdn_media_exists`). Valid values are now
  `"comm"` (default, name-addressed `cdn.media_exists` call) and `"off"`;
  any other value falls through to `"comm"`. Hosts still setting `"http"`
  should drop the setting (or set `"off"`). Docs (`conf.py`, `MODULE.md`,
  `docs/capabilities*.json`) and the legacy-mode tests removed with it.

## [0.3.15] — 2026-07-17

### Fixed
- `docs/capabilities.json` regenerated again — 0.3.14's release commit ran
  `make contract` before the version bump landed, so the committed file
  still baked in `0.3.13` (caught by `test_capabilities_envelope` in the
  0.3.14 publish retry, which also failed CI on py3.12 for this reason).

## [0.3.14] — 2026-07-17

### Changed
- `stapel-core` ceiling raised `>=0.10,<0.11` → `>=0.10,<0.12` (core 0.11
  fleet re-pin: default bus, nav, config-checks, error params/language —
  additive for modules).
- `docs/schema.json` regenerated against core 0.11.2 — error object gained
  `error_language` field and a reworded `error` description; no drift
  otherwise.

## [0.3.13] — 2026-07-16

### Changed
- **v1 canon sweep §60** (api-versioning.md §2, §6): `urls.py` renamed to
  `urls_v1.py` (paths inside unchanged); the new root `urls.py` mounts it
  under `v1/` and re-exports `GATE_REGISTRY`. Hosts including
  `stapel_profiles.urls` under `profiles/api/` now serve
  `/profiles/api/v1/...`; bare paths no longer exist (sweep lands before the
  §3 API00x gates are enabled).
- Contract artifacts regenerated (`make contract`): `/v1/` in schema paths —
  the single expected diff.
- `_capabilities.py` canonical_prefix → `/profiles/api/v1`.
- Lint hygiene to a clean `stapel-verify`: explicit `# noqa: R006/R007` on
  pre-existing findings.

### Added — per-module contract emission: `schema` + `flows` triad (contract-pipeline.md Wave 1)

stapel-profiles now emits its **own** API contract per-module, completing the
triad `docs/{schema,flows,errors}.json` (`errors.json` already existed). The
frontend codegen can now read profiles' committed artifacts instead of the
monolith aggregate at floating `main` — contract-pipeline.md verdict **A**
(contract = a reviewable, version-pinned commit). Copied from stapel-auth's
reference implementation (contract-pipeline.md §2-3, ETALON).

- **Harness** (reuses `stapel_tools.codegen`, adds ~90 lines of per-module config):
  - `_codegen_settings.py` — single source of truth for the `settings.configure`
    block, shared with `conftest.py` (extracted, no test-behavior change); a
    `contract=True` mode swaps in the production `REST_FRAMEWORK`.
  - `codegen_urls.py` — mounts `stapel_profiles.urls` alone at the canonical
    `profiles/api/` prefix (no co-mounted sibling — the monolith mounts
    profiles by itself), so emitted paths are `/profiles/api/...` not bare
    `/me`.
  - `_codegen.py` — the `python -m stapel_profiles._codegen --out docs`
    entrypoint. Also explicitly registers drf-spectacular's
    `JWTCookieAuthenticationExtension` (`stapel_core...swagger._register_jwt_auth_extension`)
    — the monolith performs this registration as a side effect of its own
    dev-only Swagger URLs (`DJANGO_ENV=local` in `codegen/generate.sh`), which
    is *global* process state, not tied to any one module's urls.py. Without
    it, protected endpoints would emit without their `security:
    [{"JWTCookieAuth": []}]` entry and diverge from the monolith slice.
- **`docs/schema.json`** (new) — drf-spectacular OpenAPI for profiles only,
  canonical prefix; **`docs/flows.json`** (new) — empty array, profiles has no
  `@flow_step` annotations (confirmed zero profiles-tagged flows in the
  monolith aggregate too).
- **Byte-identity** with the monolith aggregate's profiles slice (paths under
  `/profiles/api/` + their component closure) is **exact**: 13 paths, a
  10-component closure (`StapelError` + 9 profiles-owned schemas), zero diff.
  No cross-module `$ref` — profiles' schema does not reference any
  `stapel_auth`-owned component (the model layer already links to auth's User
  via a bare `user_id` UUID field, not a Django FK), so **no sibling co-mount
  was needed** for closure (contract-pipeline.md §9 Q2 does not apply to this
  module).
- **Gate:** `make contract` / `make contract-check`; `tests/test_contract.py`
  (drift + determinism + canonical-prefix + monolith-slice identity) is the
  CI-enforced gate.

## 0.3.11 — 2026-07-06

### Added — ru error catalog + bilingual error reference (i18n-shipping волна 2)

Reference-pattern application of the `stapel_core.i18n` catalog contour to the
`errors` domain (i18n-shipping.md §5), copied 1:1 from the stapel-auth pilot.

- `translations/errors.ru.json` — flat `{code: text}` ru catalog covering all
  51 keys, with `translations/.state.json` provenance sidecar. 49 keys seeded
  from the curated `stapel-translate` builtin fixtures (`origin:
  seed:stapel-builtin`, no tokens spent), 2 machine-translated (`origin:
  llm`, unreviewed). `translations/.errors.ru.llm-cache.json` is the
  committed, content-hash translation cache.
- `docs/errors.en.md` · `docs/errors.ru.md` — generated human-readable
  references; README + MODULE.md link both languages.
- `tests/test_error_i18n.py` — `check_translation_catalogs` gate + env-gated
  regen (`STAPEL_REGEN_ERROR_I18N=1`).

## 0.3.10 — 2026-07-06

### Added
- **`@on_action("user.registered")` handler** (`actions.py`) — re-hosts an
  OAuth provider avatar onto the CDN. When the event carries a usable
  `avatar_url` (only OAuth registrations populate it today) it calls
  `cdn.import_from_url` and stores the returned `<type>/<hash>` ref on
  `Profile.avatar` via `update_or_create`. Design:
  - **no-op** when `avatar_url` is absent/null/empty (the common
    email/phone/password case) or when `user_id` is missing;
  - **respect-user-choice + idempotency in one guard** — if the profile
    already has a non-empty avatar the handler no-ops *before* fetching, so a
    manually uploaded avatar is never clobbered and an at-least-once
    redelivery never re-imports (nor re-hits the provider);
  - **best-effort, swallow-not-retry** — any fetch/call/save failure is logged
    and swallowed; letting it propagate would make the outbox relay redeliver
    the whole `user.registered` event and re-run every other subscriber in a
    retry storm over a cosmetic, non-critical avatar of an attacker-influenced
    URL. The account simply exists without an avatar.
- `tests/test_user_registered_action.py` — no-op cases, happy path (mocked
  comm call), respect-user-choice, idempotency under redelivery, and the
  swallowed-failure modes.


## 0.3.9 — 2026-07-06

### Added
- **Declarative error registry + `docs/errors.json` codegen artifact.** All ten
  service error keys now declare a machine-readable `remediation` hint via
  `register_service_errors(..., remediation=...)`. Every profiles key is a
  bad-input error, so each declares `fix_input`. This makes the backend canon:
  it overrides the status+name heuristic for `error.404.profile_not_found`,
  which the heuristic would otherwise resolve to `retry` (its default for a 404
  `not_found`) — retrying the same lookup would just loop the failing request.
- `docs/errors.json` — the language-agnostic error-key registry (51 entries:
  core `COMMON_ERRORS` + cross-cutting keys + the ten service keys), emitted by
  `generate_error_keys` and consumed by the frontend (`stapel-react` profiles
  pair) as the errors-bundle source.
- `tests/test_error_keys.py` — byte-stable drift gate (regenerate-and-diff, same
  discipline as schema.json/flow docs) plus artifact-shape and
  declared-remediation assertions. Regenerate with
  `STAPEL_REGEN_ERROR_KEYS=1 pytest tests/test_error_keys.py`.

### Changed
- Test settings (`conftest.py`) install `stapel_core.django.apps.CommonDjangoConfig`
  so the `generate_error_keys` management command is discoverable for the drift
  gate. No `@flow_step` flows exist in this module (0 flows is valid).


## 0.3.8 — 2026-07-06

### Changed
- Pinned `stapel-core` to the `>=0.8,<0.9` window (library-standard §7.1: one
  minor window; floor `0.8.0` is published on PyPI — no pin into the void).
- CI: added the release-track job (library-standard §7.4) — installs the package
  the way an end user does (`pip install .`, dependencies resolved from PyPI
  strictly by the declared pins, no git-main core, no editable siblings), asserts
  `stapel-core` resolves inside the `0.8` window, and runs an import smoke.
  Advisory (continue-on-error) until the whole stapel graph is on PyPI; becomes
  the blocking precondition for a `vX.Y.Z` tag once it is.


## 0.3.7 — 2026-07-06

### Packaging
- Tests excluded from the built wheel/sdist (the `stapel_profiles.tests`
  subpackage is no longer listed in `[tool.setuptools] packages`). Added
  `[project.urls]`, completed the trove classifiers (MIT/OSI, Python 3.13,
  `Typing :: Typed`, OS Independent, `3 :: Only`, Development Status) and a
  `[tool.ruff]` lint section (single source shared with the git hooks/CI).


## 0.3.6 — 2026-07-05

### Fixed — OpenAPI schema warnings
- OpenAPI: `@extend_schema(request=None)` for Follow/Unfollow/Block/Unblock/Unsubscribe
  (bodyless POST endpoints — target is the URL/query param) so drf-spectacular no
  longer errors with "unable to guess serializer". `UnsubscribeView` responses now
  use `OpenApiTypes.OBJECT` instead of bare `dict`.
- Added return type hints on `ProfilePublicSerializer` method fields
  (`get_followers_count -> int`, `get_following_count -> int`,
  `get_relationship_status -> str | None`) so drf-spectacular resolves their types.
  Documentation-only; no runtime behaviour change.

## 0.3.5 — 2026-07-05

### Fixed — `profile.changed` emit is now truly best-effort under ATOMIC_REQUESTS
- `events.publish_profile_changed` now emits inside its own
  `transaction.atomic()` block. The prior "best-effort, swallow never fails the
  request" claim held only in autocommit mode: under `ATOMIC_REQUESTS=True` the
  helper ran inside the request transaction, and a failing emit marked it
  rollback-only (`stapel-core comm/actions.py`), so the swallow did not save the
  request — the next DB query raised `TransactionManagementError` and rolled the
  profile mutation back. The nested atomic isolates an emit failure to a
  savepoint (Django clears `needs_rollback`), so the mutation survives in **both**
  request modes; it also silences the emit-outside-atomic guard's WARNING spam.
  New regression tests cover both modes. No behaviour change on the success path.

## 0.3.4 — 2026-07-05

### Changed
- CI/pre-commit/pre-push now run `stapel_core.lint.emit_check` (outbox-atomicity
  gate, stapel-core 0.3.3+). Hooks guard-fall back to a skip when core is older.
- `events.publish_profile_changed`: annotated the `profile.changed` emit with an
  `emit-check: ok` pragma (EMIT002). It is a best-effort post-commit publisher —
  the helper holds no ORM write of its own, the caller saves+commits the profile
  independently, and the swallow is intentional so a broker/listener outage never
  fails the request. No behaviour change.

## 0.3.3 — 2026-07-05

### Fixed
- Migration drift under Django 6: `Profile.email_messages`, `email_system`,
  `push_messages` and `push_system` gained `help_text` after migration `0010`
  without a follow-up migration. `0014` regenerates the `help_text`-only
  `AlterField`s (no DB/schema change). `makemigrations --check` is now clean.

## 0.3.2 — 2026-07-05

### Fixed
- `user_id` in comm schemas typed uuid, was integer — rejected valid
  `user.deleted` events. `schemas/consumes/user.deleted.json` and
  `schemas/consumes/user.deletion_initiated.json` now type `user_id` as
  `{"type": "string", "format": "uuid"}`, matching the UUID-pk canonical
  user and the auth/gdpr producers.


## 0.3.1 — 2026-07-04

### Added
- `MODULE.md` — agent-facing extension-point map (part of the July 2026
  framework-wide documentation sweep). No functional changes.

## 0.3.0 — 2026-07-03

No functional changes — version alignment with the Stapel 0.3
release train; stapel-core dependency now `>=0.3.0,<0.4`.


## [0.2.0] - 2026-07-02

### Added
- `conf.py` with `profiles_settings = AppSettings("STAPEL_PROFILES", ...)` and the
  `PROFILES_AVATAR_CHECK` setting (`"comm"` default | `"http"` | `"off"`) controlling
  how avatar CDN references are verified.
- `stapel_core.signals.profile_updated` is now sent (kwargs: `profile`,
  `fields_changed`) at every profile mutation point, alongside the
  `profile.changed` comm event.
- `py.typed` marker (PEP 561).
- Tests for avatar validation via comm, `profile.changed` emission
  (schema-validated), and the `profile_updated` signal.

### Changed
- Avatar existence validation now goes through the comm layer by default:
  `stapel_core.comm.call("cdn.media_exists", {"ref": ...}, timeout=2.0)` instead of
  a direct HTTP call. Fails closed (`error.400.avatar_not_found`) when the function
  is unregistered or the provider fails. The legacy HTTP path is available via
  `PROFILES_AVATAR_CHECK = "http"`.
- `publish_profile_changed` now emits the `profile.changed` action via
  `stapel_core.comm.emit` instead of publishing directly to the Kafka bus.
- Renamed `schemas/emits/profile.updated.json` to `schemas/emits/profile.changed.json`
  and aligned the schema with the actually emitted payload (string UUID `user_id`,
  full profile field set, `additionalProperties: false`).

## [0.1.0] - 2026-07-02

### Added
- Initial release: `Profile`, `Language`, `UserRelationship` models, REST API
  (profile CRUD, follow/block relationships, languages, unsubscribe), GDPR
  provider, `user.deleted` action subscription, admin, fixtures and event schemas.
