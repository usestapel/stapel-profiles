"""Data Transfer Objects for profiles API."""
from dataclasses import dataclass
from typing import Optional, List
from uuid import UUID

from stapel_core.media.dto import StapelImageDTO


@dataclass
class LanguageResponse:
    """Language info.

    Attributes:
        code: ISO 639-1 language code. Example: en
        name: Human-readable language name. Example: English
        flag: URL to flag image. Example: /flags/en.svg
    """
    code: str
    name: str
    flag: Optional[str]


@dataclass
class ProfileResponse:
    """Full user profile (for /me endpoint).

    §66 alpha-cut: only the hard core (docs/pending/profile-fields.md) is
    listed here — display_name/currency_code/measurement_units/theme moved
    to the standard-field registry (`field_defs.py`); a project that swapped
    in an extended Profile model exposes those through its own DTO/presenter,
    not this one.

    Attributes:
        user_id: User UUID. Example: 550e8400-e29b-41d4-a716-446655440000
        avatar_source: Where avatar points (file, url, gravatar, cdn). Example: file
        avatar: Avatar reference matching avatar_source. Example: avatar/abc123
        location_id: Geo service location ID. Example: 42
        location_display_name_narrow: Short location. Example: LU - Mamer
        location_display_name_broad: Broad location. Example: LU - Differdange
        app_language: Selected app language.
        understands: List of language codes the user understands. Example: ["en", "fr"]
        use_device_language: Use device language for UI. Example: true
        auto_detected_language: Last detected language from Accept-Language header. Example: de
        auto_translate_content: Auto-translate ad content. Example: false
        email_messages: Receive message notifications via email. Example: true
        email_system: Receive system notifications via email. Example: true
        push_messages: Receive message notifications via push. Example: true
        push_system: Receive system notifications via push. Example: true
        essential_cookies_accepted: Essential cookies consent. Example: true
        initial_setup_passed: Whether onboarding is complete. Example: true
        followers_count: Number of followers. Example: 42
        following_count: Number of users followed. Example: 15
        rating: User rating. Example: 4.8
        created_at: ISO 8601 creation time. Example: 2025-01-15T12:00:00Z
        updated_at: ISO 8601 last update time. Example: 2025-01-20T14:30:00Z
    """
    user_id: UUID
    #: Hard-core again (owner 2026-07-22): every profile carries a display name
    #: and a theme preference by default.
    display_name: str
    theme: str
    avatar_source: str
    avatar: Optional[str]
    #: Renderable descriptor denormalized from avatar+avatar_source (the raw
    #: `avatar` ref above stays for the upload round-trip). A frontend `<Image>`
    #: renders THIS — never the bare ref (THE DESIGN RULE, owner 2026-07-20).
    avatar_image: Optional[StapelImageDTO]
    location_id: Optional[int]
    location_display_name_narrow: str
    location_display_name_broad: str
    app_language: Optional[LanguageResponse]
    understands: List[str]
    use_device_language: bool
    auto_detected_language: str
    auto_translate_content: bool
    email_messages: bool
    email_system: bool
    push_messages: bool
    push_system: bool
    essential_cookies_accepted: bool
    initial_setup_passed: bool
    followers_count: int
    following_count: int
    rating: float
    created_at: str
    updated_at: str


@dataclass
class ProfilePublicResponse:
    """Public profile for viewing other users.

    Attributes:
        user_id: User UUID. Example: 550e8400-e29b-41d4-a716-446655440000
        avatar_source: Where avatar points (file, url, gravatar, cdn). Example: file
        avatar: Avatar reference matching avatar_source. Example: avatar/def456
        location_id: Geo service location ID. Example: 42
        location_display_name_narrow: Short location. Example: LU - Mamer
        location_display_name_broad: Broad location. Example: LU - Differdange
        followers_count: Number of followers. Example: 120
        following_count: Number of users followed. Example: 30
        rating: User rating. Example: 4.5
        relationship_status: Relationship to current user. Example: following
    """
    user_id: UUID
    #: Hard-core again (owner 2026-07-22) — shown on other users' profiles too.
    display_name: str
    avatar_source: str
    avatar: Optional[str]
    #: Renderable descriptor denormalized from avatar+avatar_source (§ /me).
    avatar_image: Optional[StapelImageDTO]
    location_id: Optional[int]
    location_display_name_narrow: str
    location_display_name_broad: str
    followers_count: int
    following_count: int
    rating: float
    relationship_status: Optional[str]


@dataclass
class ProfileUpdateRequest:
    """Update profile fields (PATCH, all optional).

    Attributes:
        display_name: User's display name. Example: Ada Lovelace
        theme: UI theme preference (light/dark/system). Example: dark
        avatar_source: Where avatar points (file, url, gravatar, cdn). Example: file
        avatar: Avatar reference matching avatar_source. Example: avatar/abc123
        location_id: Geo service location ID. Example: 42
        app_language: ISO 639-1 language code. Example: en
        understands: List of understood language codes. Example: ["en", "fr"]
        use_device_language: Use device language for UI. Example: true
        auto_translate_content: Auto-translate ad content. Example: false
        email_messages: Toggle message email notifications. Example: true
        email_system: Toggle system email notifications. Example: true
        push_messages: Toggle message push notifications. Example: true
        push_system: Toggle system push notifications. Example: true
        essential_cookies_accepted: Essential cookies consent. Example: true
        initial_setup_passed: Mark onboarding as complete. Example: true
    """
    display_name: Optional[str] = None
    theme: Optional[str] = None
    avatar_source: Optional[str] = None
    avatar: Optional[str] = None
    location_id: Optional[int] = None
    app_language: Optional[str] = None
    understands: Optional[List[str]] = None
    use_device_language: Optional[bool] = None
    auto_translate_content: Optional[bool] = None
    email_messages: Optional[bool] = None
    email_system: Optional[bool] = None
    push_messages: Optional[bool] = None
    push_system: Optional[bool] = None
    essential_cookies_accepted: Optional[bool] = None
    initial_setup_passed: Optional[bool] = None


@dataclass
class ProfileBatchRequest:
    """Look up many public profiles in one request.

    Sent as a POST body rather than a `?ids=` query string on purpose: a
    people grid resolves 50-100 ids at once, which is 1.9-3.7 kB of UUIDs —
    past the conservative 2 kB URL ceiling old proxies/WAFs still enforce,
    and close to nginx's default 8 kB request-line+header budget once a JWT
    cookie rides along. A 414 there would read to the user as "the profile
    service is down", which is exactly the failure mode this endpoint exists
    to remove. A body also keeps the roster of who is being looked at out of
    access logs and Referer headers.

    POST is the transport, not the semantics: this is a read, it changes
    nothing and is safe to repeat. HTTP caching is given up in the trade —
    acceptable, because the caller batches precisely because it keeps its
    own per-id cache and only asks for the ids missing from it.

    Attributes:
        user_ids: User UUIDs to look up. Duplicates are collapsed; found profiles come back in the order first requested. Example: ["550e8400-e29b-41d4-a716-446655440000"]
    """
    user_ids: List[UUID]


@dataclass
class ProfileBatchResponse:
    """Answer of the batch lookup: the profiles that exist + the ids with none.

    The split is the whole point of the endpoint. "This user has no profile
    row" is a NORMAL state — nobody has opened settings yet — not a failure,
    so it must not arrive as a 404 per id: that is what turned a 16-tile
    contact grid into 16 red console lines. Reading the answer:

    * id in ``profiles`` — there is a profile, here it is;
    * id in ``missing`` — asked, none exists: render the placeholder, cache
      the negative, do not retry, nothing is broken;
    * id in neither — it was not part of THIS request.

    ``profiles`` and ``missing`` together always cover exactly the
    deduplicated ids that were sent, so "absent" never has to be guessed at.
    Nothing is invented for a missing id: an id in ``missing`` carries no
    payload at all, because a filled-in placeholder would be this service
    asserting a display name for a person who never chose one.

    The status is 200 in every one of those cases, including "all missing".

    Attributes:
        profiles: Profiles that exist, in the order their ids were first requested.
        missing: Requested ids with no profile row — a normal state, not an error. Example: ["550e8400-e29b-41d4-a716-446655440000"]
    """
    profiles: List[ProfilePublicResponse]
    missing: List[UUID]


@dataclass
class ProfileFieldManifestEntry:
    """One active profile field, as the frontend skin needs it to render
    itself without hardcoding field names (docs/pending/profile-fields.md,
    "Дополнение владельца" §1 — data-driven skin, tier 1 of the two-tier
    front-pair answer). GET /profiles/api/v1/field-manifest/ returns a list
    of these for whatever the project's STAPEL_PROFILES["FIELDS"] manifest
    (identity preset + standard_fields + custom_fields) actually selected.

    Attributes:
        name: Field name. Example: theme
        kind: Storage/presentation kind (text, bool, enum, model_ref, geohash). Example: enum
        docstring: Human-readable field description, feeds help text. Example: UI theme preference.
        required: Whether the field is required (not blank). Example: false
        order: Manifest declaration order — identity first, then standard_fields in listed order, then custom_fields. Example: 0
        enum_values: Choice values, only present when kind is enum. Example: ["light", "dark", "system"]
    """
    name: str
    kind: str
    docstring: str
    required: bool
    order: int
    enum_values: Optional[List[str]] = None


@dataclass
class RelationshipResponse:
    """User relationship status.

    Attributes:
        user_id: Target user UUID. Example: 550e8400-e29b-41d4-a716-446655440000
        status: Relationship status. Example: following
    """
    user_id: UUID
    status: str


@dataclass
class RelationshipActionResponse:
    """Result of a relationship action.

    Attributes:
        success: Whether the action succeeded. Example: true
        status: New relationship status. Example: following
    """
    success: bool
    status: str


@dataclass
class FollowersResponse:
    """User's followers list.

    Attributes:
        followers: List of follower user UUIDs. Example: ["550e8400-e29b-41d4-a716-446655440000"]
        count: Total follower count. Example: 42
    """
    followers: List[UUID]
    count: int


@dataclass
class FollowingResponse:
    """Users followed by this user.

    Attributes:
        following: List of followed user UUIDs. Example: ["550e8400-e29b-41d4-a716-446655440000"]
        count: Total following count. Example: 15
    """
    following: List[UUID]
    count: int
