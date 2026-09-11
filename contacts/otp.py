"""The OTP seam — this module sends no SMS and stores no code.

Proving a phone is one of the oldest things stapel-auth does: the codes live
in ``stapel_core.verification.codes.OneTimeCodeStore`` (hashed, TTL-scoped,
attempt-counted), the delivery goes through ``stapel_core.notifications``,
and the policy — how long a code lives, how many guesses it survives, how
often one may be asked for, and whether the deployment is running mock codes
(``USE_MOCK_SMS_OTP``) — lives in ``stapel_auth.otp.services``. Copying any
of that here would give the fleet two phone-verification policies that drift,
and a deployment two places to turn mock mode off in.

So the seam is a dotted path, defaulting to stapel-auth's phone service
(:data:`~.conf.AUTH_OTP_PROVIDER`), and the provider contract is exactly that
service's existing shape:

``send_verification_code(phone) ->``
    the store's receipt on success (any truthy object; ``ttl`` is read off it
    when present), ``{"error": "rate_limit"|"blocked", "retry_after": int}``
    when a limit refuses the send, or ``None`` when nothing could be sent.

``verify_code(phone, code) ->``
    ``{"success": True}``, or ``{"error": "invalid_code",
    "attempts_remaining": int}`` / ``{"error": "expired"}`` /
    ``{"error": "blocked", "retry_after": int}`` /
    ``{"error": "unavailable"|"server_error"}``.

:class:`CoreOneTimeCodeProvider` is the fallback for a deployment that runs
profiles WITHOUT stapel-auth. It is not a copy of that service's policy — it
is the thinnest possible use of the same core primitive, with this module's
own numbers, so "no auth module installed" degrades to a working flow instead
of to a 500.
"""
import logging
import secrets

from django.utils.module_loading import import_string

from .conf import AUTH_OTP_PROVIDER, contacts_setting

logger = logging.getLogger(__name__)

#: This module's own code family in the core store. Separate purpose from
#: auth's ``otp_phone``, so a code issued to log in can never confirm a
#: contact and vice versa.
CODE_PURPOSE = "profiles_contact_phone"


class CoreOneTimeCodeProvider:
    """Fallback provider over ``stapel_core.verification.codes``.

    Used when ``OTP_PROVIDER`` is left at its default and stapel-auth is not
    installed. Same store, same guarantees (hashed entry, one lifetime for
    the code and its attempt budget, spent on first match); the policy
    numbers below are this module's, chosen to be unsurprising rather than
    configurable — a deployment that wants to tune them installs stapel-auth,
    whose settings are the fleet's answer for exactly this.
    """

    #: Seconds a code lives.
    ttl = 600
    #: Wrong guesses before the block.
    max_attempts = 5
    #: Seconds the block lasts.
    block_duration = 600
    #: Least seconds between two sends to the same number.
    resend_cooldown = 60
    #: Sends per hour per number.
    hourly_limit = 5
    #: Digits.
    code_length = 6

    @property
    def store(self):
        from stapel_core.verification.codes import OneTimeCodeStore

        return OneTimeCodeStore(CODE_PURPOSE)

    def send_verification_code(self, phone, device_id=None):
        from stapel_core.verification.codes import StoreUnavailable

        store = self.store
        try:
            wait = store.send_wait(
                phone,
                cooldown=self.resend_cooldown,
                hourly_limit=self.hourly_limit,
                device_id=device_id,
            )
            if wait:
                return {"error": "rate_limit", "retry_after": wait}
            blocked = store.blocked_for(phone)
            if blocked:
                return {"error": "blocked", "retry_after": blocked}

            lo = 10 ** (self.code_length - 1)
            code = str(secrets.randbelow(9 * lo) + lo)
            issued = store.issue(
                phone,
                code,
                ttl=self.ttl,
                max_attempts=self.max_attempts,
                device_id=device_id,
            )
            if not self._deliver(phone, code):
                # Nothing was sent, so nothing may be waiting to be typed in:
                # leaving the entry would burn the user's one code on an SMS
                # that never arrived.
                store.discard(phone)
                return None
            return issued
        except StoreUnavailable:
            # No store, no code. Refusing to send beats sending one that
            # nothing can later verify.
            logger.error("contact OTP store unavailable; no code issued")
            return None
        except Exception:
            logger.exception("contact OTP send failed")
            return None

    def _deliver(self, phone, code) -> bool:
        from django.utils.translation import get_language

        from stapel_core.notifications import request_notification

        return bool(
            request_notification(
                notification_type="otp_code",
                phone=phone,
                variables={"code": code, "expiry_minutes": self.ttl // 60},
                source_service="profiles",
                language=get_language(),
            )
        )

    def verify_code(self, phone, code):
        from stapel_core.verification.codes import CodeOutcome

        try:
            check = self.store.check(
                phone, code, block_seconds=self.block_duration
            )
        except Exception:
            logger.exception("contact OTP check failed")
            return {"error": "server_error"}

        if check.outcome is CodeOutcome.OK:
            return {"success": True}
        if check.outcome is CodeOutcome.NOT_FOUND:
            # Aged out, already spent, or the cache restarted. Three ways of
            # "start over" — none of them is "you mistyped".
            return {"error": "expired"}
        if check.outcome is CodeOutcome.BLOCKED:
            return {
                "error": "blocked",
                "retry_after": check.retry_after or self.block_duration,
            }
        if check.outcome is CodeOutcome.UNAVAILABLE:
            return {"error": "unavailable"}
        return {
            "error": "invalid_code",
            "attempts_remaining": max(check.attempts_remaining or 0, 0),
        }


def get_otp_provider():
    """Instantiate the configured provider.

    A path the deployment STATED must import: falling back from it would hide
    a typo behind a working-looking flow, and the fallback's policy is not
    the one that deployment asked for. Only the shipped default falls back,
    and only on ImportError — "stapel-auth is not installed here" is a
    deployment shape, not a mistake.
    """
    path = str(contacts_setting("OTP_PROVIDER") or "")
    if not path:
        return CoreOneTimeCodeProvider()
    try:
        return import_string(path)()
    except ImportError:
        if path != AUTH_OTP_PROVIDER:
            raise
        logger.info(
            "stapel-auth is not installed; contact phone verification uses "
            "the built-in core code store"
        )
        return CoreOneTimeCodeProvider()


__all__ = ["CODE_PURPOSE", "CoreOneTimeCodeProvider", "get_otp_provider"]
