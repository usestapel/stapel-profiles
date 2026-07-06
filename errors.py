"""Custom error keys for the profiles service."""

from stapel_core.django.api.errors import ErrorKeysView, register_service_errors

ERR_404_PROFILE_NOT_FOUND = 'error.404.profile_not_found'
ERR_400_CANNOT_FOLLOW_SELF = 'error.400.cannot_follow_self'
ERR_400_CANNOT_BLOCK_SELF = 'error.400.cannot_block_self'
ERR_400_DISPLAY_NAME_TOO_SHORT = 'error.400.display_name_too_short'
ERR_400_DISPLAY_NAME_FORBIDDEN_CHARS = 'error.400.display_name_forbidden_chars'
ERR_400_DISPLAY_NAME_EMOJI = 'error.400.display_name_emoji'
ERR_400_DISPLAY_NAME_INVISIBLE_CHARS = 'error.400.display_name_invisible_chars'
ERR_400_INVALID_CURRENCY = 'error.400.invalid_currency'
ERR_400_INVALID_AVATAR_FORMAT = 'error.400.invalid_avatar_format'
ERR_400_AVATAR_NOT_FOUND = 'error.400.avatar_not_found'

PROFILES_ERRORS = {
    ERR_404_PROFILE_NOT_FOUND: 'Profile not found',
    ERR_400_CANNOT_FOLLOW_SELF: 'Cannot follow yourself',
    ERR_400_CANNOT_BLOCK_SELF: 'Cannot block yourself',
    ERR_400_DISPLAY_NAME_TOO_SHORT: 'Display name must be at least 2 characters',
    ERR_400_DISPLAY_NAME_FORBIDDEN_CHARS: 'Display name contains forbidden characters',
    ERR_400_DISPLAY_NAME_EMOJI: 'Display name cannot contain emoji',
    ERR_400_DISPLAY_NAME_INVISIBLE_CHARS: 'Display name contains invisible characters',
    ERR_400_INVALID_CURRENCY: 'Invalid currency code',
    ERR_400_INVALID_AVATAR_FORMAT: 'Invalid avatar reference format. Expected: avatar/<hash>',
    ERR_400_AVATAR_NOT_FOUND: 'Avatar not found on CDN',
}

# Machine-readable recovery hints (remediation) — the canonical "what to do"
# for each key, emitted into the errors.json codegen artifact and consumed by the
# frontend/LLM (frontend-core-architecture §2.5). Vocabulary: retry |
# wait_and_retry | reauthenticate | verify | fix_input | contact_support | bug.
# Declared here (backend = canon) rather than left to the status+name heuristic.
# Every profiles key is caused by a bad request argument (a self-referential
# follow/block, a display name that violates a rule, an unknown currency, a
# malformed or dangling avatar reference, a profile handle/id that matches no
# profile), so the honest recovery is "correct the input" — `fix_input`. This
# overrides the heuristic for `error.404.profile_not_found`, which the heuristic
# would resolve to `retry` (its default for a 404 `not_found`); retrying the same
# lookup would just loop the same failing request.
PROFILES_REMEDIATION = {
    ERR_404_PROFILE_NOT_FOUND: 'fix_input',
    ERR_400_CANNOT_FOLLOW_SELF: 'fix_input',
    ERR_400_CANNOT_BLOCK_SELF: 'fix_input',
    ERR_400_DISPLAY_NAME_TOO_SHORT: 'fix_input',
    ERR_400_DISPLAY_NAME_FORBIDDEN_CHARS: 'fix_input',
    ERR_400_DISPLAY_NAME_EMOJI: 'fix_input',
    ERR_400_DISPLAY_NAME_INVISIBLE_CHARS: 'fix_input',
    ERR_400_INVALID_CURRENCY: 'fix_input',
    ERR_400_INVALID_AVATAR_FORMAT: 'fix_input',
    ERR_400_AVATAR_NOT_FOUND: 'fix_input',
}

register_service_errors(PROFILES_ERRORS, remediation=PROFILES_REMEDIATION)


class ProfilesErrorKeysView(ErrorKeysView):
    def get_service_errors(self):
        return PROFILES_ERRORS
