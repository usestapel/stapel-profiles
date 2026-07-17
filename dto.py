"""Data Transfer Objects for profiles API."""
from dataclasses import dataclass
from typing import Optional, List
from uuid import UUID


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

    Attributes:
        user_id: User UUID. Example: 550e8400-e29b-41d4-a716-446655440000
        display_name: Display name. Example: John Doe
        avatar: CDN avatar reference. Example: avatar/abc123
        location_id: Geo service location ID. Example: 42
        location_display_name_narrow: Short location. Example: LU - Mamer
        location_display_name_broad: Broad location. Example: LU - Differdange
        currency_code: ISO 4217 currency code. Example: USD
        measurement_units: Measurement system. Example: metric
        theme: UI theme. Example: system
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
    display_name: str
    avatar: Optional[str]
    location_id: Optional[int]
    location_display_name_narrow: str
    location_display_name_broad: str
    currency_code: str
    measurement_units: str
    theme: str
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
        display_name: Display name. Example: Jane Smith
        avatar: CDN avatar reference. Example: avatar/def456
        location_id: Geo service location ID. Example: 42
        location_display_name_narrow: Short location. Example: LU - Mamer
        location_display_name_broad: Broad location. Example: LU - Differdange
        followers_count: Number of followers. Example: 120
        following_count: Number of users followed. Example: 30
        rating: User rating. Example: 4.5
        relationship_status: Relationship to current user. Example: following
    """
    user_id: UUID
    display_name: str
    avatar: Optional[str]
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
        display_name: New display name. Example: John Doe
        avatar: CDN avatar reference. Example: avatar/abc123
        location_id: Geo service location ID. Example: 42
        currency_code: ISO 4217 currency code. Example: USD
        measurement_units: Measurement system (metric or imperial). Example: metric
        theme: UI theme (light, dark, system). Example: dark
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
    avatar: Optional[str] = None
    location_id: Optional[int] = None
    currency_code: Optional[str] = None
    measurement_units: Optional[str] = None
    theme: Optional[str] = None
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
