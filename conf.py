"""Settings for stapel-profiles.

Resolution order per key (see stapel_core.conf.AppSettings):
settings.STAPEL_PROFILES dict -> flat Django setting of the same name ->
environment variable -> default.

Keys are intentionally prefixed (``PROFILES_...``) so the flat Django
setting / env var form is unambiguous:

    # settings.py — either form works
    PROFILES_AVATAR_CHECK = "off"
    STAPEL_PROFILES = {"PROFILES_AVATAR_CHECK": "off"}

PROFILES_AVATAR_CHECK — how validate_avatar verifies the CDN reference:
    "comm" (default) — stapel_core.comm.call("cdn.media_exists", ...)
    "off"            — skip the existence check (format still validated)

PROFILES_FIELDS — the profile field-constructor manifest (§66,
docs/pending/profile-fields.md §2/§3), NOT a capability axis (structural
config, not a binary toggle — excluded from capabilities.json accordingly):
    {}                                    (default) — hard core only
    {"identity": "display_name",
     "standard_fields": ["theme"],
     "custom_fields": [...ProfileFieldDef]}

    Consumed by `views._active_field_manifest()` (GET .../field-manifest/,
    the data-driven skin's source of truth) and by
    `field_defs.build_profile_model()` when a project assembles its own
    swapped-in extended Profile model.

PROFILES_BATCH_MAX_IDS — how many user ids one POST .../batch may carry
(default 100). Structural config, NOT a capability axis (a numeric ceiling,
not a behavior toggle — excluded from capabilities.json like PROFILES_FIELDS).
Over the ceiling the request is REFUSED with `error.400.too_many_ids`
carrying both numbers; the endpoint never silently truncates the list, which
would show up in the UI as "some people have no name" with nothing in the
response saying why. A host with bigger spaces raises the number; the honest
cost is one bigger query + one bigger response, not a silent partial answer.
"""
from stapel_core.conf import AppSettings

#: AppSettings-shaped literal dict (capability-config.md §2): a top-level
#: DEFAULTS lets the capabilities.json emitter introspect axis keys/kinds
#: without re-parsing the AppSettings() call.
DEFAULTS = {
    "PROFILES_AVATAR_CHECK": "comm",
    "PROFILES_FIELDS": {},
    "PROFILES_BATCH_MAX_IDS": 100,
    # ── Avatar URL boundary ──────────────────────────────────────────
    # An `avatar_source=url` avatar is a user-controlled string this
    # service hands to every consumer, so it has a boundary: only these
    # schemes are accepted on import and only these are ever emitted on
    # read. Active schemes (javascript:, data:) are not renderable
    # references, they are code; plain http downgrades the page and leaks
    # the referrer in clear text.
    "PROFILES_AVATAR_URL_ALLOWED_SCHEMES": ["https"],
    # Hosts external avatars may point at. CLOSED BY DEFAULT: [] names no
    # trusted host, so an `avatar_source=url` avatar is refused on import and
    # suppressed on read until this deployment says where such an avatar may
    # come from. An entry is an exact host ("cdn.example.com") or a
    # dot-prefixed suffix (".example.com"); listing them turns the avatar
    # from a cross-site tracking pixel into a reference to storage the host
    # trusts. The single entry ["*"] reopens "any host" — the pre-0.12.6
    # behaviour, restored as one explicit, greppable act rather than as the
    # silent consequence of never having configured anything.
    "PROFILES_AVATAR_URL_ALLOWED_HOSTS": [],
    # Referrer policy this service declares on its own responses, and the
    # policy its clients are asked to render avatars under (MODULE.md
    # "Client contract"). "" leaves the header alone.
    "PROFILES_REFERRER_POLICY": "no-referrer",
    # ── Public-profile visibility ────────────────────────────────────
    # The fields a public lookup (GET .../<user_id>, POST .../batch) may
    # expose. Default is the full historical set — narrowing it is the
    # host's privacy decision, and it applies to BOTH public endpoints so
    # they can never disagree.
    "PROFILES_PUBLIC_FIELDS": [
        "user_id",
        "display_name",
        "avatar_source",
        "avatar",
        "avatar_image",
        "location_id",
        "location_display_name_narrow",
        "location_display_name_broad",
        "followers_count",
        "following_count",
        "relationship_status",
    ],
    # What an UNAUTHENTICATED caller sees. NARROW BY DEFAULT: the two public
    # endpoints are AllowAny and answer for any user id, so this list is what
    # the open internet may walk the member directory for. Identity and
    # avatar are what a name-next-to-a-message needs; whereabouts
    # (location_*) and the social graph (followers/following counts) are not
    # needed to render a stranger's name and are exactly what makes a bulk
    # scrape worth running. relationship_status has no meaning without a
    # viewer. A host that wants the pre-0.12.6 answer sets this to None (or
    # ["*"]) — "anonymous callers see everything members see" is a decision
    # a deployment states, not one it inherits. A narrower list (or []) still
    # narrows further; it may never widen past PROFILES_PUBLIC_FIELDS.
    "PROFILES_PUBLIC_FIELDS_ANONYMOUS": [
        "user_id",
        "display_name",
        "avatar_source",
        "avatar",
        "avatar_image",
    ],
    # ── Enumeration limits ───────────────────────────────────────────
    # Public lookups are the enumeration surface of the whole user base:
    # DRF rate strings ("120/min"), None/"" disables one of them.
    "PROFILES_LOOKUP_RATE": "120/min",
    "PROFILES_BATCH_RATE": "30/min",
}

profiles_settings = AppSettings(
    "STAPEL_PROFILES",
    defaults=DEFAULTS,
)
