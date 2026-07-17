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
| Models | `Profile` (PK `user_id: UUID`, links to auth by id — no FK across modules), `Language` (PK `code`), `UserRelationship` (follow/block, unique per pair, no self-relation). Choices: `MeasurementUnit`, `Theme`, `RelationshipStatus`. |
| HTTP API (`urls.py`) | `me` (GET/PATCH), `me/followers`, `me/following`, `me/blocked`, `<uuid:user_id>` (public profile), `<uuid:user_id>/{follow,unfollow,block,unblock,relationship}`, `languages` (read-only viewset), `notifications/unsubscribe` (RFC 8058 one-click, HMAC token). |
| Events | Emits `profile.changed`; consumes `user.deleted` (see below). |
| GDPR | `ProfilesGDPRProvider` (section `profile`): export of profile + relationships, hard delete. Auto-registered in `apps.ProfilesConfig.ready()` via `stapel_core.gdpr.gdpr_registry`. |
| Validation | `validate_display_name` (control chars, emoji, invisible chars, min length); avatar reference validation against the CDN contract `avatar/<hash>` with existence check (mode-selectable, see settings). |
| Error keys | `errors.PROFILES_ERRORS` — `error.404.profile_not_found`, `error.400.cannot_follow_self`, `error.400.cannot_block_self`, `error.400.display_name_*`, `error.400.invalid_avatar_format`, `error.400.avatar_not_found`. Registered via `stapel_core` `register_service_errors`. |
| Management commands | `sync_languages` (seed/refresh `Language` from bundled fixture, preserving flags), `publish_all_profiles` (backfill `profile.changed` for all rows). |
| Public API (`__all__`) | `profiles_settings`, `publish_profile_changed`, `validate_display_name`, `ProfilesGDPRProvider` — lazily exported (PEP 562); importing `stapel_profiles` does not require configured Django. Anything not in `__all__` is internal and may change without notice. |

## Extension points (fork-free)

### Settings (`conf.py`)

`profiles_settings = AppSettings("STAPEL_PROFILES", defaults=...)` from
`stapel_core.conf`. Resolution order per key:
`settings.STAPEL_PROFILES` dict → flat Django setting of the same name →
environment variable → default.

| Key | Default | Values | Effect |
|---|---|---|---|
| `PROFILES_AVATAR_CHECK` | `"comm"` | `"comm"` \| `"off"` | How `validate_avatar` verifies the CDN reference: `"comm"` = name-addressed function call `stapel_core.comm.call("cdn.media_exists", {"ref": ...})`; `"off"` = skip existence check (format still validated). Fail-closed: an unverifiable reference is rejected. |

This module currently declares **no `import_strings` keys** (no dotted-path
settings that swap in app-layer classes). `stapel_core.conf.AppSettings`
supports them, so a new pluggable seam (e.g. a custom avatar checker backend)
is a natural **upstream contribution**: add the key + default to `conf.py`
with `import_strings=(...)`.

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

### Serializer seams (`views.SerializerSeamsMixin`)

Every profile/relationship view mixes in `SerializerSeamsMixin` with two
class attributes and two hooks — subclass the view, set the attribute (or
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
| Consumes | `user.deleted` | `actions.handle_user_deleted` (`@on_action`, registered in `apps.ready()`) | Erases profile PII via `ProfilesGDPRProvider().delete()` (GDPR Art. 17). Handlers are idempotent; delivery is at-least-once. Contract: `schemas/consumes/user.deleted.json`. |
| Calls (function) | `cdn.media_exists` | `serializers.ProfileCreateUpdateSerializer.validate_avatar` when `PROFILES_AVATAR_CHECK="comm"` | Name-addressed `stapel_core.comm.call` — the CDN module (or the project) registers the provider; profiles never imports it. |
| Provides (function) | — | — | This module registers no comm functions. |

Declared-but-unconsumed: `schemas/consumes/user.deletion_initiated.json`
exists but no handler subscribes to it yet (grace-period handling is a
candidate upstream contribution).

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
- `UserRelationship` — user-facing follow/block state. It is durable domain
  data staff may need to inspect for abuse/dispute handling, not a
  delivery/audit log or TTL-expiring record, so it does not fit `ops`.

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
