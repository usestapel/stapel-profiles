"""E.164 normalisation — one number, one spelling, one row.

``+7 999 123-45-67``, ``+79991234567`` and ``+7 (999) 1234567`` are the same
number, and without a normal form the uniqueness constraint on
``(owner_key, value)`` would be decorative: the same person could store the
same phone three times, each with its own policy, and a reveal would hand out
three copies of it.

**Why "possible" and not "valid".** ``phonenumbers.is_valid_number()`` checks
the number against libphonenumber's allocation metadata for that country —
which ships with the library and goes stale between releases. A freshly
allocated range answers *False* there, and rejecting it would tell a real
person with a working phone that their number does not exist. This module
does not need that check to be safe: what actually proves a number here is
the SMS code (``verified_at``), and nothing is ever revealed without one. So
the boundary enforces the two things it can be certain about — the number is
in international form, and it has a plausible length for its country — and
lets the OTP settle the rest.
"""
import phonenumbers
from phonenumbers import NumberParseException


class InvalidPhoneNumber(ValueError):
    """The submitted string is not a phone number this module can store."""


def normalize_phone(value: str) -> str:
    """Return *value* as E.164, or raise :class:`InvalidPhoneNumber`.

    The input must carry its country code (a leading ``+``). A bare national
    number is refused rather than guessed at: this module has no idea which
    country the caller meant, and a wrong guess would silently store — and
    later dial out to — a number in the wrong country.
    """
    raw = (value or "").strip()
    if not raw.startswith("+"):
        raise InvalidPhoneNumber(
            "phone number must be in international form, starting with '+'"
        )
    try:
        parsed = phonenumbers.parse(raw, None)
    except NumberParseException as exc:
        raise InvalidPhoneNumber(str(exc)) from exc
    if not phonenumbers.is_possible_number(parsed):
        raise InvalidPhoneNumber("phone number has an implausible length")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


__all__ = ["InvalidPhoneNumber", "normalize_phone"]
