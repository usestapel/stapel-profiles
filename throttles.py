"""Enumeration limits for the public profile surface (audit PROFILE-01).

`GET /profiles/api/v1/<user_id>` and `POST /profiles/api/v1/batch` answer
for ANY user id, to any caller (`AllowAny` — deliberately, see the views).
That combination is a directory of the whole user base: with the batch
endpoint, 100 ids per request, a scripted caller walks it as fast as the
network allows and nothing in the service notices.

Batching caps bound one request; these throttles bound the sequence. Rates
are settings (`PROFILES_LOOKUP_RATE`, `PROFILES_BATCH_RATE`, DRF rate
strings like ``"120/min"``); ``None`` or ``""`` disables one of them, which
is a deployment's explicit choice — the shipped default is on.

Identity is the authenticated user when there is one and the client IP
otherwise, so one member's traffic never spends another's budget and an
anonymous crawler cannot hide behind an authenticated tenant.
"""
from rest_framework.throttling import SimpleRateThrottle


class _ProfilesRateThrottle(SimpleRateThrottle):
    #: Name of the STAPEL_PROFILES key carrying this throttle's rate.
    rate_setting = ""

    def get_rate(self):
        from .conf import profiles_settings

        return getattr(profiles_settings, self.rate_setting, None) or None

    def get_cache_key(self, request, view):
        if self.rate is None:
            return None
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            ident = f"user:{user.pk}"
        else:
            ident = f"ip:{self.get_ident(request)}"
        return f"throttle_{self.scope}_{ident}"


class ProfileLookupThrottle(_ProfilesRateThrottle):
    """Per-caller ceiling on single public profile lookups."""

    scope = "profiles_lookup"
    rate_setting = "PROFILES_LOOKUP_RATE"


class ProfileBatchThrottle(_ProfilesRateThrottle):
    """Per-caller ceiling on batch resolution — the amplified surface.

    Deliberately separate from (and tighter than) the single-lookup budget:
    one batch request answers for up to PROFILES_BATCH_MAX_IDS people, so
    the same number of requests is a much bigger read.
    """

    scope = "profiles_batch"
    rate_setting = "PROFILES_BATCH_RATE"


__all__ = ["ProfileLookupThrottle", "ProfileBatchThrottle"]
