"""
Validators for profile fields.
"""

import re

from stapel_core.django.api.errors import StapelValidationError

# Matches control chars, HTML-dangerous chars
_DISPLAY_NAME_FORBIDDEN = re.compile(
    r"[\x00-\x1f"  # Control characters U+0000–U+001F
    r"\x7f"  # DEL
    r'<>"\';\\/]'  # HTML-dangerous characters
)
# Emoji: Emoji_Presentation + Extended_Pictographic (broad coverage)
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f1e0-\U0001f1ff"  # flags
    "\U00002702-\U000027b0"  # dingbats
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa00-\U0001fa6f"  # chess symbols
    "\U0001fa70-\U0001faff"  # symbols extended-A
    "\U00002600-\U000026ff"  # misc symbols
    "\U0000200d"  # ZWJ
    # Scattered emoji in U+2000–U+3300. Listed individually: a blanket
    # U+203C–U+3299 range would also reject CJK punctuation and kana.
    "\U0000203c\U00002049"  # double bang, interrobang
    "\U00002122\U00002139"  # trade mark, information
    "\U00002194-\U000021aa"  # arrows
    "\U0000231a\U0000231b\U00002328"  # watch, hourglass, keyboard
    "\U000023e9-\U000023fa"  # av control symbols
    "\U000024c2"  # circled M
    "\U000025aa-\U000025fe"  # geometric shapes
    "\U00002934\U00002935"  # arrow-curving
    "\U00002b05-\U00002b07"  # heavy arrows
    "\U00002b1b\U00002b1c\U00002b50\U00002b55"  # squares, star, circle
    "\U00003030\U0000303d\U00003297\U00003299"  # wavy dash, part alt, ㊗ ㊙
    "]"
)


def validate_display_name(value: str) -> str:
    """
    Validate display_name. Raises StapelValidationError if invalid.
    """
    from .errors import (
        ERR_400_DISPLAY_NAME_EMOJI,
        ERR_400_DISPLAY_NAME_FORBIDDEN_CHARS,
        ERR_400_DISPLAY_NAME_INVISIBLE_CHARS,
        ERR_400_DISPLAY_NAME_TOO_SHORT,
    )

    if not value:
        return value

    if len(value) < 2:
        raise StapelValidationError(ERR_400_DISPLAY_NAME_TOO_SHORT)

    if _DISPLAY_NAME_FORBIDDEN.search(value):
        raise StapelValidationError(ERR_400_DISPLAY_NAME_FORBIDDEN_CHARS)

    if _EMOJI_PATTERN.search(value):
        raise StapelValidationError(ERR_400_DISPLAY_NAME_EMOJI)

    import unicodedata

    for ch in value:
        cat = unicodedata.category(ch)
        if cat.startswith("C") and cat != "Co":
            raise StapelValidationError(ERR_400_DISPLAY_NAME_INVISIBLE_CHARS)

    return value
