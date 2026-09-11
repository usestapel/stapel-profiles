"""Seller contacts — the numbers a person publishes, and who may read them.

A listing carries no phone field and never will. A number is a separate
resource with its own owner, its own proof (an SMS code), its own policy and
its own journal, and it is handed over by ONE endpoint
(``POST /profiles/api/v1/contacts/reveal``) that decides, per number, whether
this particular viewer may have it. Everything else in the fleet — listing
payloads, search hits, cards, the public profile — carries at most the single
bit ``contacts.phone``: "there is a number to ask for". Never the number.

Four rules hold the design together:

1. **Unproven is invisible.** A number with no ``verified_at`` exists, is
   listed to its owner, and is revealed to nobody. The proof is an SMS code
   through the OTP seam (``STAPEL_PROFILES["CONTACTS"]["OTP_PROVIDER"]``,
   stapel-auth's phone service when that module is installed) — this package
   owns no code delivery of its own.
2. **Anonymous is not a viewer.** A guest session is ``is_authenticated``
   (``AUTH_ANONYMOUS``) and nobody registered; handing it a seller's number
   would make the whole permission model cost one POST. It gets
   ``error.403.contacts_registration_required`` — the door, not a wall.
3. **Every hand-over is written down.** A :class:`~.models.ContactReveal`
   row per revealed number, with viewer, listing and IP, and an hourly
   ceiling per viewer spent BEFORE the row is written. A scraper is a viewer
   who reveals 500 numbers an hour, and the only way to know that is to have
   counted.
4. **The owner is not a viewer either.** Their own numbers are theirs: they
   come back whole, unbudgeted and unjournalled.
"""

_EXPORTS = {
    "Contact": ".models",
    "ContactKind": ".models",
    "ContactPolicy": ".models",
    "ContactReveal": ".models",
    "normalize_phone": ".phones",
    "InvalidPhoneNumber": ".phones",
    "contacts_setting": ".conf",
    "get_otp_provider": ".otp",
    "has_revealable_phone": ".policy",
    "revealable_for": ".policy",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name in _EXPORTS:
        import importlib

        value = getattr(importlib.import_module(_EXPORTS[name], __name__), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | set(__all__))
