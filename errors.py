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

register_service_errors(PROFILES_ERRORS)


class ProfilesErrorKeysView(ErrorKeysView):
    def get_service_errors(self):
        return PROFILES_ERRORS
