# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
