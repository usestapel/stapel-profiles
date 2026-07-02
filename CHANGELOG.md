# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
