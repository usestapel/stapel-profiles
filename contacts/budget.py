"""The hourly reveal ceiling — spent before the number is handed over.

A permission model that lets every member read every number is a directory of
every seller's phone, walkable at HTTP speed. The policies decide WHO; this
decides HOW MANY, per viewer per hour, and it is the reason a scraped account
shows up as a 429 in the log instead of as a quiet 200 half a million times.

Two properties matter more than precision:

* **charged before the answer.** The slot is taken before the rows are read
  and written, so a viewer cannot mine the endpoint by abandoning responses.
* **it says when.** The 429 carries ``retry_after`` in seconds, so the pair
  can say "in 7 minutes" instead of "later".

The window is a rolling hour kept in the cache — not a ledger. On a restarted
or evicted cache a viewer gets a fresh hour, which is the honest trade for
not writing a row per attempt; the DURABLE record of what was actually handed
over is :class:`~.models.ContactReveal`, and that is what an audit reads.
"""
import time

from django.core.cache import cache

from .conf import contacts_setting

#: Seconds the ceiling is measured over.
WINDOW = 3600

_KEY = "stapel_profiles:contacts:reveal:{viewer}"


def spend(viewer_key) -> int | None:
    """Take one reveal slot for *viewer_key*.

    Returns ``None`` when the reveal may proceed, or the seconds to wait when
    the hour's budget is spent.
    """
    limit = int(contacts_setting("REVEAL_PER_HOUR") or 0)
    if limit <= 0:
        # A deployment that states 0 has removed the ceiling. Stated, not
        # inherited: the shipped default is 30.
        return None

    key = _KEY.format(viewer=viewer_key)
    now = time.time()
    stamps = [t for t in (cache.get(key) or []) if now - t < WINDOW]
    if len(stamps) >= limit:
        # The oldest attempt still inside the window is the one whose expiry
        # frees a slot.
        return max(int(WINDOW - (now - stamps[0])) + 1, 1)
    stamps.append(now)
    cache.set(key, stamps, WINDOW)
    return None


def spent(viewer_key) -> int:
    """How many slots *viewer_key* has used inside the current window."""
    now = time.time()
    key = _KEY.format(viewer=viewer_key)
    return len([t for t in (cache.get(key) or []) if now - t < WINDOW])


__all__ = ["WINDOW", "spend", "spent"]
