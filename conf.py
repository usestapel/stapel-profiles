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

CONTACTS — the seller-contacts block (`contacts/`), the module's one NESTED
key. Read key by key through `contacts.conf.contacts_setting()`, host value
over default, so a deployment may state one knob without losing the other
two:

    STAPEL_PROFILES = {"CONTACTS": {"REVEAL_PER_HOUR": 10}}

`REVEAL_PER_HOUR` (30) — reveals one viewer may perform per hour; 0 removes
the ceiling. `POLICIES` (["members", "verified", "nobody"]) — the policy
vocabulary this deployment offers, first entry the default for a new
contact. `OTP_PROVIDER` — dotted path to the phone-verification seam,
stapel-auth's service by default, with a built-in core-code-store fallback
when that module is not installed.
"""
from stapel_core.conf import AppSettings

from .contacts.conf import CONTACTS_DEFAULTS

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
        "seller_type",
        # Tenure, not PII: WHEN THE PROFILE ROW WAS CREATED. It identifies
        # nobody, it moves for nobody (a sign-in does not touch it), and it
        # is the one thing a buyer looks for before dealing with a stranger
        # — "on the site since March 2024". Listed here like every other
        # field, so a host that considers a join date too much still takes
        # it out of this list and it is gone from both public endpoints.
        "created_at",
        # `{"phone": bool}` — whether this person has a phone worth asking
        # for. A BIT, never a number: the number is obtained only through
        # POST .../contacts/reveal, which applies the per-number policy,
        # spends the viewer's hourly budget and writes a journal row. Listed
        # here like every other field, so a host that does not want the
        # storefront drawing a "Show phone" button takes it out and both
        # public endpoints stop carrying it.
        "contacts",
    ],
    # What a caller WITHOUT AN ACCOUNT sees — the unsigned internet and a
    # guest session alike (0.18.0: a guest is `is_authenticated` and nobody
    # registered, so it reads this list, not the member one). NARROW BY
    # DEFAULT: the two public
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
    # `seller_type` rides along with identity/avatar rather than with
    # whereabouts or the social graph: it is a self-declared trading
    # capacity a buyer is entitled to see before contacting, in most
    # jurisdictions — the same call `cards._card` already made for the
    # comm-layer projection (profiles.public_cards).
    # `created_at` rides along for the same reason it is not withheld from
    # the internet: a join date is tenure, not PII — it names nobody and
    # locates nobody, and it is exactly what a signed-out buyer reads on a
    # seller page to tell a three-year account from a three-day one. Hiding
    # it from guests would leave the storefront's "on the site since ..."
    # blank for every visitor who has not registered, which is most of them.
    "PROFILES_PUBLIC_FIELDS_ANONYMOUS": [
        "user_id",
        "display_name",
        "avatar_source",
        "avatar",
        "avatar_image",
        "seller_type",
        "created_at",
        # Rides along for the same reason `created_at` does: the visitor who
        # has not registered yet is exactly the one the "Show phone" button
        # exists to send to registration, and a button that only appears
        # after signing in cannot be what makes anyone sign in. It discloses
        # a bit, not a number, and the reveal endpoint answers that same
        # visitor with the registration door.
        "contacts",
    ],
    # ── The block check (profiles.relationships) ─────────────────────
    # How many pairs one call may carry. Structural config, not a
    # capability axis (a numeric ceiling, not a behaviour toggle). Over the
    # ceiling the call is REFUSED, never truncated: a short answer would
    # report the dropped pairs as unblocked, and this is the one read in the
    # module where being wrong has a direction — an uncheckable block must
    # fail closed at the caller (503), not open.
    "PROFILES_PAIRS_MAX": 500,
    # ── The public card (profiles.public_cards) ──────────────────────
    # The name-addressed CDN function that fills a card avatar's render
    # metadata. The default is the fleet's one answer about a picture — the
    # same call chat attachments and classified listing cards make, so one
    # image has one shape everywhere. "" disables the enrichment: cards then
    # carry the ref with null numbers and meta_reason="cdn_unavailable",
    # which is a degraded card, never a failed one.
    "PROFILES_CARD_MEDIA_FUNCTION": "cdn.describe_many",
    # ── Enumeration limits ───────────────────────────────────────────
    # Public lookups are the enumeration surface of the whole user base:
    # DRF rate strings ("120/min"), None/"" disables one of them.
    "PROFILES_LOOKUP_RATE": "120/min",
    "PROFILES_BATCH_RATE": "30/min",
    # ── Seller contacts (contacts/) ──────────────────────────────────
    # A NESTED block, not four more flat PROFILES_* keys: these four knobs
    # only mean anything together (a policy vocabulary, a ceiling on the
    # endpoint that applies it, and the seam that proves a number), and a
    # deployment turning contacts on reads one block instead of hunting
    # four names. Structural config, NOT a capability axis — same reading
    # as PROFILES_FIELDS.
    #
    # The host's value REPLACES this default rather than merging into it
    # (AppSettings' rule for every key), which for a dict of independent
    # knobs is a trap: stating only REVEAL_PER_HOUR would silently drop the
    # OTP seam. So `contacts.conf.contacts_setting()` reads it key by key,
    # host over default, and a host may state exactly what it cares about.
    # See contacts/conf.py (CONTACTS_DEFAULTS) for what each one does.
    # One source, referenced rather than restated: a second copy of these
    # three values here would be the thing that drifts from the code that
    # reads them.
    "CONTACTS": dict(CONTACTS_DEFAULTS),
}

profiles_settings = AppSettings(
    "STAPEL_PROFILES",
    defaults=DEFAULTS,
)
