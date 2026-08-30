# stapel-profiles — MODULE.md

Agent-facing map of this module: what it provides, its fork-free extension
points, and anti-patterns. Use it to classify a desired change as an
**app-layer override via an extension point** vs an **upstream contribution**
(see `docs/stdlib-contribution-pipeline.md` and system-design §8.6 in the
Stapel monorepo). Stapel modules never import each other; all cross-module
interaction goes through `stapel_core` (comm actions/functions, signals,
registries). Everything below is customizable **without forking**.

- Package: `stapel-profiles` (importable as `stapel_profiles`), Django app label `profiles`.
- Runtime dependency: `stapel_core` only. No imports from other `stapel-*` modules.

## What this module provides

| Surface | Contents |
|---|---|
| Models | `Profile` (PK `user_id: UUID`, links to auth by id — no FK across modules), `Language` (PK `code`), `UserRelationship` (follow/block, unique per pair, no self-relation — **also the block store the fleet's `profiles.relationships` check reads**; there is no second model for blocks). Choices: `MeasurementUnit`, `Theme`, `RelationshipStatus`. |
| HTTP API (`urls.py`) | `me` (GET/PATCH), `me/followers`, `me/following`, `me/blocked`, `<uuid:user_id>` (public profile — a registered user with no row yet is answered with an empty-but-renderable profile; `404` means the id names nobody), `batch` (POST, many public profiles at once — same three-way reading, `missing` = ids that name nobody, never a 404), `<uuid:user_id>/{follow,unfollow,block,unblock,relationship}`, `languages` (read-only viewset), `notifications/unsubscribe` (RFC 8058 one-click, HMAC token). |
| Events | Emits `profile.changed` and the GDPR receipt/probe answer; consumes `user.registered` (**provisions the profile row** — 0.15.0 — plus the display-name pre-fill and the OAuth avatar import), `gdpr.erasure.requested`, `gdpr.owner.probe`, `user.merged` (**the survivor's profile wins, the merged one is archived** — 0.17.0) and (deprecated) `user.deleted` — see below. |
| GDPR | `ProfilesGDPRProvider` (section `profile`): export of profile + relationships, hard delete. Auto-registered in `apps.ProfilesConfig.ready()` via `stapel_core.gdpr.gdpr_registry`. |
| Validation | `validate_display_name` (control chars, emoji, invisible chars, min length); avatar reference validation against the CDN contract `avatar/<hash>` with existence check (mode-selectable, see settings). |
| Error keys | `errors.PROFILES_ERRORS` — `error.404.profile_not_found`, `error.400.cannot_follow_self`, `error.400.cannot_block_self`, `error.400.display_name_*`, `error.400.invalid_avatar_format`, `error.400.avatar_not_found`, `error.400.too_many_ids`. Registered via `stapel_core` `register_service_errors`. |
| Management commands | `sync_languages` (seed/refresh `Language` from bundled fixture, preserving flags), `publish_all_profiles` (backfill `profile.changed` for all rows). |
| Public API (`__all__`) | `profiles_settings`, `publish_profile_changed`, `validate_display_name`, `ProfilesGDPRProvider`, `blocked_pairs`, `is_blocked` — lazily exported (PEP 562); importing `stapel_profiles` does not require configured Django. Anything not in `__all__` is internal and may change without notice. |

## Extension points (fork-free)

### Settings (`conf.py`)

`profiles_settings = AppSettings("STAPEL_PROFILES", defaults=...)` from
`stapel_core.conf`. Resolution order per key:
`settings.STAPEL_PROFILES` dict → flat Django setting of the same name →
environment variable → default.

| Key | Default | Values | Effect |
|---|---|---|---|
| `PROFILES_AVATAR_CHECK` | `"comm"` | `"comm"` \| `"off"` | How `validate_avatar` verifies the CDN reference: `"comm"` = name-addressed function call `stapel_core.comm.call("cdn.media_exists", {"ref": ...})`; `"off"` = skip existence check (format still validated). Fail-closed: an unverifiable reference is rejected. |
| `PROFILES_BATCH_MAX_IDS` | `100` | positive int | How many ids one `POST batch` may carry. Over the ceiling the request is **refused** with `error.400.too_many_ids` carrying `requested` + `limit` — never silently truncated, which would surface in the UI as "some people have no name" with nothing saying why. A numeric ceiling, not a behaviour toggle, so it is not a capability axis. |
| `PROFILES_AVATAR_URL_ALLOWED_SCHEMES` | `["https"]` | list of schemes | Schemes an `avatar_source=url` avatar may use, on import **and** on read. An active scheme (`javascript:`, `data:`) is code, not a picture reference; plain `http` downgrades the page and leaks the referrer. Refusal: `error.400.avatar_url_scheme`. |
| `PROFILES_AVATAR_URL_ALLOWED_HOSTS` | `[]` (**none**) | exact hosts / `.suffix` entries / `["*"]` | Hosts external avatars may point at. **Closed by default:** an empty list trusts no host, so an `avatar_source=url` avatar is refused on import and suppressed on read. Without an allowlist every profile view fetches from a host the profile's owner chose — a cross-site beacon carrying the viewer's IP and user agent. `["*"]` reopens "any host" as one explicit, greppable act. Refusal: `error.400.avatar_url_host`. |
| `PROFILES_REFERRER_POLICY` | `"no-referrer"` | header value \| `""` | `Referrer-Policy` this service declares on its profile responses (`""` = leave it to the host's middleware). The client half of the contract is below. |
| `PROFILES_PUBLIC_FIELDS` | the full public set | list of field names | What a public lookup (`GET .../<user_id>`, `POST .../batch`) exposes to an authenticated caller. Both endpoints serialize through the same class, so they cannot disagree about a person's privacy. |
| `PROFILES_PUBLIC_FIELDS_ANONYMOUS` | identity + avatar only | list \| `None` \| `["*"]` | What an UNAUTHENTICATED caller sees. **Narrow by default:** `user_id`, `display_name`, `avatar_source`, `avatar`, `avatar_image` — no `location_*`, no follower/following counts, no `relationship_status` (which has no meaning without a viewer). Both public endpoints are `AllowAny`, so this is the answer the open internet gets. `None` or `["*"]` restores "anonymous callers see what members see". It may only ever narrow `PROFILES_PUBLIC_FIELDS` — a field hidden from members cannot reappear for the internet. |
| `PROFILES_PAIRS_MAX` | `500` | positive int | How many pairs one `profiles.relationships` call may carry. Over the ceiling the call **raises** — refused, never truncated. A short answer would report the dropped pairs as *unblocked*, and this is the one read here where being wrong has a direction: an uncheckable block must fail closed at the caller (503), not open. A numeric ceiling, not a behaviour toggle, so it is not a capability axis. |
| `PROFILES_CARD_MEDIA_FUNCTION` | `"cdn.describe_many"` | function name \| `""` | The name-addressed CDN read that fills a public card's avatar with render metadata. The default is the fleet's ONE answer about a picture — the same call chat attachments and classified listing cards make. `""` disables the enrichment: cards then carry the ref with null numbers and `meta_reason: "cdn_unavailable"` — a degraded card, never a failed one. |
| `PROFILES_LOOKUP_RATE` | `"120/min"` | DRF rate string \| `None` | Per-caller ceiling on single public lookups (`ProfileLookupThrottle`), keyed by user when authenticated and by IP otherwise. `None` disables it — a deployment's explicit choice. |
| `PROFILES_BATCH_RATE` | `"30/min"` | DRF rate string \| `None` | Per-caller ceiling on batch resolution. Deliberately tighter than the lookup budget: one batch request answers for up to `PROFILES_BATCH_MAX_IDS` people. |

Every one of these switches is **closed by default**, and every one of them
announces itself when a deployment opens it: `checks.py` registers
`manage.py check` warnings `profiles.W001` (avatar existence check off),
`W002` (`["*"]` avatar host allowlist), `W003` (anonymous callers given the
member field set) and `W004` (a public-lookup throttle disabled). A switch
nobody can see is a switch nobody revisits.

This module currently declares **no `import_strings` keys** (no dotted-path
settings that swap in app-layer classes). `stapel_core.conf.AppSettings`
supports them, so a new pluggable seam (e.g. a custom avatar checker backend)
is a natural **upstream contribution**: add the key + default to `conf.py`
with `import_strings=(...)`.

### Client contract — profile media (security audit PROFILE-01)

An avatar is a value ONE user controls and EVERY consumer renders, so the
boundary has two halves and the backend can only hold one of them:

* **this service** accepts only safe schemes/hosts on import, and never
  emits a stored reference that today's policy would refuse (a legacy row
  degrades to "no avatar" rather than being handed out) — so a client never
  receives an active-scheme URL from here;
* **a client** must still refuse to navigate or execute anything but an
  image load for these fields, and should render profile media under a
  restrictive referrer policy (`no-referrer` / `strict-origin`), so the page
  a viewer is on never travels to whatever host an avatar points at. The
  service declares its own policy on profile responses via
  `PROFILES_REFERRER_POLICY`.

### Client contract — an empty name is an answer

`display_name` is `""` for a person who has not typed one, and this service
will not invent one for them. There is no `fallback_label` field, no
`"User 1234"`, and no email local-part promoted to a public name — these
endpoints are `AllowAny` and answer for any user id, so a manufactured label
would publish, to the open internet, something the person never chose.

The client renders the fallback: initials, an avatar-only tile, "Seller",
whatever that surface calls a nameless person. The two states it must tell
apart are on the wire already:

* `200` with `display_name: ""` — a real person who has filled nothing in.
  Render them with your fallback. Since 0.15.0 this is the answer for a user
  who registered and never opened their own profile; before it, this case
  was a `404` and it is why a live marketplace showed no names anywhere.
* `404 error.404.profile_not_found` (or an id in `missing` from
  `POST .../batch`) — the id names nobody. Render nothing, and treat it as
  data that has gone stale rather than as a request that failed.

### Swappable models

**None.** `Profile`, `Language`, and `UserRelationship` are concrete models;
there is no `swappable` Meta or `STAPEL_PROFILES_*_MODEL` setting. The
supported fork-free way to extend the profile is an **app-layer relation**:

```python
# yourapp/models.py — owned by the project, not by stapel-profiles
class ProfileExtras(models.Model):
    profile = models.OneToOneField(
        "profiles.Profile", on_delete=models.CASCADE,
        primary_key=True, related_name="+",
    )
    bio = models.TextField(blank=True, default="")
```

(or key your model by the same `user_id` UUID with no DB-level FK, matching
how this module links to auth). Expose the extra fields through the serializer
seams below. Making a model swappable is an upstream contribution.

### Serializer seams (`stapel_core.django.api.views.StapelAPIView`)

Every profile/relationship view derives `StapelAPIView` — the canonical
`SerializerSeamMixin` + `APIView` from stapel-core (0.45.0). The local copy
of the mixin that used to live in `views.py` is **deleted**: twenty-four
identical copies across the fleet were a missing core primitive, not a
pattern. The seam is unchanged for a host — two class attributes and two hooks — subclass the view, set the attribute (or
override `get_request_serializer_class()` / `get_response_serializer_class()`),
and remount the URL in your project's `urls.py`. No method bodies need copying.

| View | `request_serializer_class` | `response_serializer_class` |
|---|---|---|
| `MyProfileView` | `ProfileCreateUpdateSerializer` | `ProfileSerializer` |
| `ProfileDetailView` | — | `ProfilePublicSerializer` |
| `FollowView` / `UnfollowView` / `BlockView` / `UnblockView` | — | `RelationshipActionResponseSerializer` |
| `RelationshipStatusView` | — | `RelationshipResponseSerializer` |
| `MyFollowersView` | — | `FollowersResponseSerializer` |
| `MyFollowingView` | — | `FollowingResponseSerializer` |
| `MyBlockedView` | — | `ProfilePublicSerializer` |

```python
class MyProfileViewV2(MyProfileView):
    response_serializer_class = ProjectProfileSerializer  # e.g. adds ProfileExtras fields
```

Note: if you subclass `ProfileCreateUpdateSerializer`, keep calling
`super().update()` / `super().create()` — they publish `profile.changed`
and send the `profile_updated` signal; skipping them breaks downstream sync.
`UnsubscribeView` intentionally has no seams (token-driven, fixed contract).

### Events & functions (comm surface)

Transport is deployment configuration (`STAPEL_COMM`): in-process in a
monolith, bus in microservices — same code either way. Payload contracts live
in `schemas/`.

| Direction | Name | Where | Contract / notes |
|---|---|---|---|
| Emits | `profile.changed` | `events.publish_profile_changed(instance)` — called on every create/update via `ProfileCreateUpdateSerializer` and on unsubscribe; keyed by `user_id` | `schemas/emits/profile.changed.json`. App layer can subscribe with `@on_action("profile.changed")` to react to profile mutations — this is the primary hook for syncing derived data. |
| Consumes | `user.registered` | `actions.handle_user_registered` (`@on_action`, registered in `apps.ready()`) | **Provisions the profile row** (`_provision_profile`, `get_or_create` — 0.15.0). Registration is what says a person exists in this product, so it is what creates their row; the row is empty but it EXISTS, which is what makes the public read answerable for someone who has never opened their own profile. Also pre-fills `display_name` from the payload hint (a pre-fill, never an assignment — see `_prefill_display_name`) and imports `avatar_url` through `cdn.import_from_url`; both are enrichments and neither is required for the row. Idempotent under at-least-once redelivery; every part is best-effort/swallow-not-retry. Contract: `schemas/consumes/user.registered.json`. |
| Consumes | `gdpr.erasure.requested` | `actions.handle_erasure_requested` | Erases the named subject and receipts with counts — see **Erasure** below. Contract: `schemas/consumes/gdpr.erasure.requested.json`. |
| Consumes | `gdpr.owner.probe` | `actions.handle_owner_probe` | Answers `gdpr.owner.alive` from the same module as the eraser — see **Erasure** below. Contract: `schemas/consumes/gdpr.owner.probe.json`. |
| Consumes | `user.deleted` | `actions.handle_user_deleted` (`@on_action`, registered in `apps.ready()`) | Deprecated upstream (stapel-gdpr removes it in 0.6.0). Same `erasure.erase_account` as the erasure path, and it receipts too when the payload carries a `correlation_id`. Handlers are idempotent; delivery is at-least-once. Contract: `schemas/consumes/user.deleted.json`. |
| Consumes | `user.merged` | `actions.handle_user_merged` (`@on_action`, registered in `apps.ready()`) | The other half of an account's life cycle (stapel-auth 0.30.0): a guest folded into an existing account. **Merge policy — the survivor's profile WINS, the merged one is ARCHIVED** (`ProfileCore.merged_into`, migration `0018`), never deleted. Nothing is copied onto the survivor and no row is created for it: a merge is not a registration, and a guest's name landing on an established account is the violation `_prefill_display_name` exists to prevent. Follows and blocks DO move (a block that silently vanishes is worse than a stale one); rows that would duplicate one the survivor already holds, or point it at itself, are dropped. Idempotent (a redelivery reports zeroes). Answering only `user.deleted` is `stapel_core.lifecycle.E001`. Contract: `schemas/consumes/user.merged.json`. |
| Emits | `gdpr.section.erased` | `actions._receipt`, in the erasing transaction | This module's erasure receipt, with counts — see **Erasure** below. Contract: `schemas/emits/gdpr.section.erased.json`. |
| Emits | `gdpr.owner.alive` | `actions.handle_owner_probe` | Probe answer — see **Erasure** below. Contract: `schemas/emits/gdpr.owner.alive.json`. |
| Calls (function) | `cdn.media_exists` | `serializers.ProfileCreateUpdateSerializer.validate_avatar` when `PROFILES_AVATAR_CHECK="comm"` | Name-addressed `stapel_core.comm.call` — the CDN module (or the project) registers the provider; profiles never imports it. |
| Provides (function) | `profiles.set_display_name` | `functions.set_display_name`, registered in `apps.ready()` | Payload `{user_id, display_name}` → `{ok, display_name, reason}`. The **named write** of the canonical name, performed by profiles on another module's authority (a workspace owner correcting a member on the roster): the caller's edge authorized it, this provider enforces the canon, the swap-aware model and the `profile.changed` emission. Refusals are structural — `reason` is the trailing name of a `error.400.display_name_*` key, or `no_display_name_field`. Contract: `schemas/functions/profiles.set_display_name.json`. |
| Provides (function) | `profiles.validate_display_name` | `functions.validate_display_name_fn` | Payload `{display_name}` → `{ok, reason}`. The canon alone, no write — for a caller that stores a *displayed* name of its own (e.g. an invitation's name hint) and must not grow a second, weaker regex. Contract: `schemas/functions/profiles.validate_display_name.json`. |
| Provides (function) | `profiles.display_names` | `functions.display_names` | Payload `{user_ids: [...]}` → `{display_names: {user_id: name}}`. The comm form of `POST /batch` narrowed to one field; ids without a non-empty name are absent, never placeholders. Contract: `schemas/functions/profiles.display_names.json`. |
| Provides (function) | `profiles.language` | `functions.language` | Payload `{user_id}` → `{app_language, auto_detected_language}` — the language the user **chose** and the one merely **observed** from an Accept-Language header, each `null` when absent (a user with no profile row answers `null`/`null`). Ask this at send time instead of mirroring the field: a mirror cannot distinguish "chose nothing" from "the sync never ran", and stapel-notifications' mirror of exactly this field stood empty for its whole lifetime. Contract: `schemas/functions/profiles.language.json`. |

| Provides (function) | `profiles.relationships` | `functions.relationships`, registered in `apps.ready()` | Payload `{pairs: [[a, b], ...]}` → `{blocked: [[a, b], ...]}`. **The fleet's server-side block check** — which of these pairs have a block between them, in EITHER direction, echoed in the orientation they were asked. Batch, because the caller checks a page of conversations; one query serves the page. Refusals are NOT structural here (unlike the display-name providers): over `PROFILES_PAIRS_MAX`, or on an id that cannot name a user, it **raises**, and the caller turns that into a 503. An outage is not consent. See **Blocks** below. Contract: `schemas/functions/profiles.relationships.json`. |
| Provides (function) | `profiles.public_cards` | `functions.public_cards` | Payload `{user_ids: [...]}` → `{profiles: {user_id: card}, missing: [...]}` where a card is exactly `{user_id, display_name, avatar, member_since, seller_type}`. The PUBLIC projection and never more — gated by the same `PROFILES_PUBLIC_FIELDS` policy the public HTTP lookups obey. `avatar` is `null` or the fleet's one image object (`ref` + `cdn.describe_many` render metadata + `meta_status`/`meta_reason`); `member_since` is a **date**, not a timestamp. Same three-way reading as `POST /batch`: a card from a row, a card for a registered person who has typed nothing, `missing` for an id that names nobody. Contract: `schemas/functions/profiles.public_cards.json`. |
| Calls (function) | `cdn.describe_many` | `cards._describe`, for the avatars on a card page | One call per page, name-addressed, guarded: a failure degrades the avatar (ref kept, numbers null, `meta_reason` naming the gap) and never fails the card. |

Declared-but-unconsumed: `schemas/consumes/user.deletion_initiated.json`
exists but no handler subscribes to it yet (grace-period handling is a
candidate upstream contribution).

### Blocks — what is stored, what is answered, and who is never told

A block is **asymmetric as an intent** and **symmetric as an effect**, and
each fact lives where it belongs.

**Stored: the intent.** One `UserRelationship` row,
`follower_id = blocker`, `following_id = blocked`, `status = "blocked"`.
There is **no new model** — this concept already existed here and a second
table would have been two answers to one question. The direction is needed
by the write side (my unblock may only remove *my* block), by the owner's
own screen (`GET me/blocked` is a list of people *I* chose) and by GDPR (the
row names two people, and the receipt counts each direction separately).

**Answered: the effect.** `profiles.relationships` answers one boolean per
pair with **no direction in it**. A block that stopped only one arrow would
be a block in name only: if A blocks B, B must not receive A's messages
either, or B's inbox stays a channel A can still use — and A's own act would
have handed B a reason to notice.

**Non-disclosure is structural, not a rule callers must remember.** There is
no field in the answer that *could* name a blocker, so no consumer can
render one and no consumer needs a policy about who may be told what. The
property is pinned end to end in `tests/test_relationships.py`:

* the answer is byte-identical whichever party placed the block, and
  whichever orientation the pair is asked in;
* the answer's key set is exactly `{"blocked"}` — no status, no timestamp,
  no author;
* a blocked person's own reads do not change: their `GET .../<blocker_id>`
  response is byte-identical before and after the block (not a 403, not a
  404, not a changed count), `GET .../<blocker_id>/relationship` still says
  `neutral` (it reports the CALLER's own edge), and `GET me/blocked` stays
  empty;
* their GDPR export says nothing about the block placed on them (see
  **Erasure**).

The one place direction stays readable is the blocker's own authenticated
surface — their own data. There is deliberately **no accessor for the
incoming direction**: "who blocked me" is the one question this module must
never answer to the person asking it about themselves.

**A block deletes nothing.** Not the counterparty's follow row, not their
profile, and — since those live in other modules — no message, thread,
listing or review. Blocking writes one row; unblocking deletes exactly one
row, the caller's own. A product that wants a blocked conversation to
disappear from a list filters its own view with this check; it does not ask
this module to erase the past (stapel-classified's rule, and the one
stapel-chat builds against).

**The write side stays on the authenticated HTTP edge** (`POST
.../<user_id>/block`, `.../unblock`, `GET me/blocked`, one implementation in
`relationships.py`) and is deliberately **not** published as a comm
Function. `profiles.set_display_name` exists because another module can hold
legitimate *authority* over a name (a workspace owner correcting a member on
the roster). A block has no such authority anywhere: it is the subject's own
act about their own safety, and nothing in the fleet may place one on
somebody's behalf. Siblings get the read.

**Consumers.** stapel-classified 0.2.1 already calls this name
(`BLOCK_FUNCTION = "profiles.relationships"`, `BLOCK_ENFORCEMENT`
`auto`/`required`/`off`); with this release its `auto` mode stops degrading
and its default may flip to `required`. stapel-chat enforces at send against
the same contract.

### Erasure

This module is a stapel-gdpr **data owner**. Declare it in the host's
settings:

```python
STAPEL_GDPR = {"DATA_OWNERS": {"profile": ["account"]}}
```

The name `profile` is fixed (`erasure.GDPR_OWNER`) and is the same name
`ProfilesGDPRProvider.section` has always carried, so a host that already
declares this owner changes nothing.

**One subject: `account`.** A profile is not partitioned by workspace and
does not outlive the person it describes, so there is no second subject to
claim — and claiming one this module cannot erase would be worse than
claiming none, because the orchestrator would then wait for a receipt that
means nothing.

`erasure.erase_account(user_id)` is idempotent and returns the `counts` its
receipt carries: the profile row, and the user's relationships in **both**
directions — somebody else's follow row naming this person is just as much
their data. That is what makes a **block erasable from either end**: a block
references two people, and whichever of them erases, the row goes and the
receipt counts it (`relationships_outgoing` for the blocker's erasure,
`relationships_incoming` for the blocked party's). Both are pinned in
`tests/test_relationships.py::TestErasure`, alongside the `gdpr.owner.alive`
probe answer — this module ships the erasure and the probe *with* the
feature, not after it.

**Erasure yes, disclosure no.** The subject's GDPR **export** carries the
blocks *they* placed and says nothing about a block placed *on* them. The
incoming row is their personal data and is erased with them; disclosing it
in an access answer would identify the person who took a protective measure
and defeat the measure itself — the rights-of-others limit on access, and
the same non-disclosure property the whole block design rests on. Pinned by
`test_the_gdpr_export_does_not_disclose_an_incoming_block`. The avatar is a reference string; whatever it points at lives in
the CDN and is erased by that module's own receipt for the same request.

**The receipt and the probe are one subscriber.** `actions.py` handles
`gdpr.erasure.requested` and `gdpr.owner.probe` side by side, deliberately:
`gdpr.owner.alive` is only evidence that the erasure path is *consumed*
because it is answered by the code that erases. Split them and `gdpr.W006` /
`GET /gdpr/api/v1/owners/health` would report a running container instead.
Deployment note: a service with this app installed and declared in
`DATA_OWNERS` must run a `consume_actions` process, or nothing answers
either event.

### Signals

Django signals are defined centrally in `stapel_core.signals`; this module
defines none of its own.

| Signal | Direction | Sender / kwargs | Fired from |
|---|---|---|---|
| `stapel_core.signals.profile_updated` | sends | `sender=Profile`, `profile=<Profile>`, `fields_changed=[...]` | `ProfileCreateUpdateSerializer.create()` / `.update()`, `UnsubscribeView.post()` |

App-layer receivers (`@receiver(profile_updated)`) run synchronously in the
same process/transaction — use them for in-process reactions; use
`profile.changed` for cross-module/cross-service reactions.

### Other pluggable registries

| Seam | Mechanism |
|---|---|
| GDPR | `ProfilesGDPRProvider` is registered on the shared `stapel_core.gdpr.gdpr_registry`. Projects add their own providers for app-layer profile extensions (e.g. `ProfileExtras`) alongside it — do not modify this one. |
| URL mounting | `stapel_profiles.urls` is `include()`-ed by the project; prefix, versioning, and per-view remounts (for seam subclasses) are entirely app-layer. |
| Admin | `admin.py` registrations can be replaced app-side via `admin.site.unregister` + your own `ModelAdmin`. |

**Error localization** (i18n-shipping.md §5): `docs/errors.json` is this
module's existing en canon (the `generate_error_keys` codegen artifact — every
`error.<status>.<name>` key this service can raise, gated by
`tests/test_error_keys.py`). ru ships as a flat `translations/errors.ru.json`
catalog with a `translations/.state.json` provenance sidecar, and
human-readable references [Errors (EN)](docs/errors.en.md) ·
[Ошибки (RU)](docs/errors.ru.md). Semantics of the i18n seams (library-standard
§3.3 — MODULE.md states the merge semantics of each key): the **error
registry** is `dict.update`/**last-wins** (a host `errors.py` autodiscovered
after ours overrides an en text — and its raise-time render — without a
fork); the **locale catalogs** are discovered over INSTALLED_APPS and merged
**later-wins** (a host app's `translations/errors.<lang>.json` overrides our
texts, and an override MUST keep the canon's `{param}` slots — gated). ru
provenance is honest: 49 keys seeded from the curated `stapel-translate`
builtin fixtures (`origin: seed:stapel-builtin`, no tokens spent), 2
profiles-only keys machine-translated (`origin: llm`, unreviewed — the gate's
W-counter, cleared by `translate_catalogs --approve`). Gate + regenerate:
`tests/test_error_i18n.py` (`check_translation_catalogs` — E on
missing/stale/params/byte-instability); regenerate with
`STAPEL_REGEN_ERROR_I18N=1 pytest tests/test_error_i18n.py::test_regen` and
commit `translations/errors.ru.json`, `translations/.state.json`,
`docs/errors.{en,ru}.md`.

### Contract emission — the `schema` + `flows` + `errors` triad

This module emits its **own** machine-readable API contract, per-module, so
the frontend codegen reads a committed, version-pinned artifact instead of
checking out the monolith aggregate at floating `main`
(contract-pipeline.md §2, verdict **A**). Copied from stapel-auth's reference
implementation (contract-pipeline.md §2-3, ETALON). The triad lives in
`docs/`:

```
docs/schema.json   drf-spectacular OpenAPI, this module only, canonical /profiles/api/ prefix
docs/flows.json    generate_flow_docs machine artifact — [] (no @flow_step here)
docs/errors.json   generate_error_keys registry (unchanged by this addition)
```

`docs/schema.json` is **byte-identical to the monolith aggregate's profiles
slice** (paths under `/profiles/api/` + the transitive `$ref` component
closure): 13 paths, a 10-component closure. No cross-module `$ref` — the
model layer links to auth's `User` via a bare `user_id` UUID field, not a
Django FK, so the schema is self-contained and **no sibling module had to be
co-mounted** for closure (contract-pipeline.md §9 Q2 does not apply here).
`tests/test_contract.py::test_matches_monolith_profiles_slice` asserts it in
the workspace (skipped in module CI, where the monolith isn't checked out).

**Harness** (`_codegen_settings.py` / `codegen_urls.py` / `_codegen.py`,
`make contract` / `make contract-check`): same shape as stapel-auth's, with
one addition specific to profiles — `_codegen.py` explicitly calls
`stapel_core.django.openapi.swagger._register_jwt_auth_extension()` before
emitting. The monolith registers this drf-spectacular extension (the
`JWTCookieAuth` security scheme) as a side effect of its own dev-only Swagger
URLs (`codegen/generate.sh` sets `DJANGO_ENV=local`); that registration is
*global* process state, not tied to any one module's urls.py. stapel-auth's
harness gets it for free only because its co-mounted sibling
(`stapel_gdpr.urls`) happens to call `get_app_swagger_urls()` unconditionally
— profiles has no such sibling, so without the explicit call, protected
endpoints would emit without their monolith `security: [{"JWTCookieAuth":
[]}]` entry.

Regenerate after any serializer/view/url/error change:

    make contract        # or: python -m stapel_profiles._codegen --out docs

then commit `docs/{schema,flows,errors}.json`.

### Admin categories — `@access` declarations (admin-suite AS-5)

Every model in `models.py` carries (or implicitly defaults to) a
`stapel_core.access.access` category — one declaration, consumed by admin
visibility, default staff rights, and the audit report (admin-suite §0).
Undecorated = `business` (visible, staff-manageable) and is the correct,
zero-effort default for domain tables.

All three models here are `business` and stay undecorated — none fit `ops`
(outbox/dedup/audit-log/TTL-junk machinery) or `secret` (token/key/credential
carriers):

- `Profile` — the module's core domain table (preferences, settings,
  onboarding state, cached location display names). It is the doc's own
  canonical `business` example. It holds no secrets: `avatar` is a CDN
  reference (`avatar/<hash>`, no bytes), not a credential.
- `Language` — reference/config data (codes, flags, active flag), analogous
  to `Category` in the admin-suite table — not a journal or credential store.
- `UserRelationship` — user-facing follow/block state, and since 0.16.0 the
  store behind the fleet's server-side block check. It is durable domain
  data staff may need to inspect for abuse/dispute handling, not a
  delivery/audit log or TTL-expiring record, so it does not fit `ops`.
  (Staff visibility is unchanged by the check: non-disclosure is a property
  of what this module answers to *users and siblings*, not of what an
  administrator handling an abuse report may read.)

No decorator changes were made and `admin.py` (`LanguageAdmin`,
`ProfileAdmin`, `UserRelationshipAdmin`) is untouched — there is no
ops/secret model here to route through `StapelModelAdmin`.

## Anti-patterns

| Don't | Do instead |
|---|---|
| Fork the package to add fields to `Profile` | Add an app-layer model related to `profiles.Profile` (or keyed by `user_id`), expose via a response-serializer subclass through the seams |
| Copy a view's method body to change its payload | Subclass the view, override `request_serializer_class` / `response_serializer_class`, remount the URL |
| Edit models/migrations inside site-packages, or add migrations to the installed app | Schema changes to this module's models are upstream contributions; project-specific data lives in project-owned models |
| Import another `stapel-*` module (e.g. the CDN or auth app) from profiles code or your overrides of it | Use name-addressed comm: `emit`/`call`/`@on_action`; identity is `user_id: UUID`, never a cross-module FK |
| Hardcode a direct HTTP call to the CDN service for avatar checks | Configure `PROFILES_AVATAR_CHECK` (`"comm"` / `"off"`) |
| Mutate `Profile` rows programmatically without notifying downstream | Go through `ProfileCreateUpdateSerializer`, or call `publish_profile_changed(profile)` and send `profile_updated` yourself |
| Subscribe to broker topics / transport primitives directly | `@on_action("profile.changed")` — transport is `STAPEL_COMM` deployment config, not code |
| Override `validate_avatar` to accept unverified references ("fail open") | Use `PROFILES_AVATAR_CHECK="off"` explicitly if you truly don't run a CDN; the check is fail-closed by design |
| Enforce a block by hiding a button, or by querying `UserRelationship` / mirroring block state in your own table | Call `profiles.relationships` (comm) or `stapel_profiles.blocked_pairs` (in-process). A client-side block is not a block, and a mirror cannot tell "not blocked" from "the sync never ran" |
| Tell the blocked party anything — an error code, a different response shape, a missing button that used to be there, a "you have been blocked" screen | Answer them exactly as before. The refusal a user sees must be the one they would see if the other person had simply gone away |
| Delete a thread, message or listing when somebody blocks | A block is not a deletion: it stops future contact and touches no history. Filter your own view with the check |
| Depend on internals not in `__all__` (DTOs, private helpers) from app code and expect stability | Treat `__all__` + the seams above as the contract; if you need something else stable, that's an upstream request |

## App-layer override vs upstream contribution — rule of thumb

**App-layer override** (project-owned code, no fork) when the change fits an
existing seam:

- new/extra profile data → related model + serializer-seam subclass;
- different API payload/validation for *your* project → view/serializer subclass, remounted URL;
- reacting to profile changes → `@on_action("profile.changed")` or `profile_updated` receiver;
- avatar-check behavior → `PROFILES_AVATAR_CHECK`;
- routing, admin, permissions policy → project `urls.py` / admin re-registration / DRF settings.

**Upstream contribution** (fix in `stapel-profiles` itself, via the
contribution pipeline — `contrib_open`, review origin, PyPI release) when:

- it's a bug in this module (any behavior contradicting this file or the schemas);
- the change is generic and there is **no seam**: new setting or `import_strings` hook, making a model swappable, a seam on `UnsubscribeView`, new emitted events or consumed actions (e.g. `user.deletion_initiated`), schema changes to `Profile`/`UserRelationship`;
- other Stapel modules or most projects would need the same change.

If upstream declines it as client-specific, it drops back to the app layer as
an override via the seams above — nothing is left in a forked copy.
