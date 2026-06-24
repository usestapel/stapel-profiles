"""
Validators for profile fields.
"""
import re
from stapel_core.django.errors import IronValidationError


# Matches control chars, HTML-dangerous chars
_DISPLAY_NAME_FORBIDDEN = re.compile(
    r'[\x00-\x1f'           # Control characters U+0000–U+001F
    r'\x7f'                  # DEL
    r'<>"\';\\/]'            # HTML-dangerous characters
)
# Emoji: Emoji_Presentation + Extended_Pictographic (broad coverage)
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols extended-A
    "\U00002600-\U000026FF"  # misc symbols
    "\U0000200D"             # ZWJ
    "\U00002B50"             # star
    "\U0000203C-\U00003299"  # misc
    "]"
)


def validate_display_name(value: str) -> str:
    """
    Validate display_name. Raises IronValidationError if invalid.
    """
    from .errors import (
        ERR_400_DISPLAY_NAME_TOO_SHORT,
        ERR_400_DISPLAY_NAME_FORBIDDEN_CHARS,
        ERR_400_DISPLAY_NAME_EMOJI,
        ERR_400_DISPLAY_NAME_INVISIBLE_CHARS,
    )

    if not value:
        return value

    if len(value) < 2:
        raise IronValidationError(ERR_400_DISPLAY_NAME_TOO_SHORT)

    if _DISPLAY_NAME_FORBIDDEN.search(value):
        raise IronValidationError(ERR_400_DISPLAY_NAME_FORBIDDEN_CHARS)

    if _EMOJI_PATTERN.search(value):
        raise IronValidationError(ERR_400_DISPLAY_NAME_EMOJI)

    import unicodedata
    for ch in value:
        cat = unicodedata.category(ch)
        if cat.startswith('C') and cat != 'Co':
            raise IronValidationError(ERR_400_DISPLAY_NAME_INVISIBLE_CHARS)

    return value
