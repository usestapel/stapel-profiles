# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
