"""The ``STAPEL_PROFILES["CONTACTS"]`` block, read one key at a time.

``profiles_settings`` resolves ``CONTACTS`` the way it resolves every other
key — the host's value REPLACES the default, it is not merged into it. For a
scalar that is the right rule; for a dict of four independent knobs it is a
trap: a deployment that only wants a different hourly ceiling would silently
lose the OTP seam and the policy vocabulary along with the default. So the
per-key read merges over :data:`CONTACTS_DEFAULTS` here, and a host may state
exactly the keys it cares about.
"""

#: The dotted path used when nothing is configured. stapel-auth's phone OTP
#: service IS the fleet's send-code/confirm-code implementation — the codes
#: live in ``stapel_core.verification.codes``, the delivery in
#: ``stapel_core.notifications``, and the policy (TTL, attempts, cooldown,
#: mock mode, `USE_MOCK_SMS_OTP`) in that module. This module reuses it
#: through the seam and owns no second copy of any of it.
AUTH_OTP_PROVIDER = "stapel_auth.otp.services.PhoneVerificationService"

CONTACTS_DEFAULTS = {
    # Reveals one viewer may perform per hour. The ceiling is on the VIEWER,
    # not on the number: the thing worth stopping is one account walking the
    # catalogue, not many buyers calling one popular seller. 0 (or less)
    # removes the ceiling — a deployment's explicit choice, not a default.
    "REVEAL_PER_HOUR": 30,
    # The policy vocabulary THIS deployment offers, in the order a picker
    # should show it. The first entry is the default policy of a new contact.
    # A host narrows it (dropping "members" makes every published number
    # require a verified account); it may never invent a value — a policy
    # this module does not implement would read as "allowed" nowhere and be
    # enforced nowhere.
    "POLICIES": ["members", "verified", "nobody"],
    # Dotted path to the OTP provider — anything exposing
    # `send_verification_code(phone)` and `verify_code(phone, code)` with
    # stapel-auth's envelopes (see otp.py). Defaults to stapel-auth's phone
    # service; when that module is not installed the built-in
    # `CoreOneTimeCodeProvider` (the same core code store, this module's own
    # policy numbers) takes over, so a profiles-only deployment still has a
    # working verification flow. An explicitly configured path that cannot
    # be imported is an error, not a fallback.
    "OTP_PROVIDER": AUTH_OTP_PROVIDER,
}


def contacts_setting(name: str):
    """One key of the CONTACTS block, host value over default."""
    from stapel_profiles.conf import profiles_settings

    configured = profiles_settings.CONTACTS or {}
    if not isinstance(configured, dict):
        configured = {}
    if name in configured:
        return configured[name]
    return CONTACTS_DEFAULTS[name]


def allowed_policies() -> list[str]:
    """The policy values this deployment accepts, defaults first.

    Filtered against what the model actually implements: a host that adds a
    name to the list gets it ignored here rather than accepted at the write
    boundary and enforced by nothing at the read one.
    """
    from .models import ContactPolicy

    known = {p.value for p in ContactPolicy}
    configured = [str(p) for p in (contacts_setting("POLICIES") or [])]
    allowed = [p for p in configured if p in known]
    return allowed or list(CONTACTS_DEFAULTS["POLICIES"])


def default_policy() -> str:
    """The policy a contact gets when its owner states none."""
    return allowed_policies()[0]


__all__ = [
    "AUTH_OTP_PROVIDER",
    "CONTACTS_DEFAULTS",
    "allowed_policies",
    "contacts_setting",
    "default_policy",
]
