"""Action subscriptions of the profiles module.

Handlers must be idempotent: delivery is at-least-once (outbox retries,
broker redelivery).

The erasure protocol is not written here. ``apps.ready()`` registers this
module as a data owner with :func:`stapel_core.gdpr.register_gdpr_owner`,
which subscribes ``gdpr.erasure.requested``, ``gdpr.owner.probe`` and the
deprecated ``user.deleted`` around
:func:`~stapel_profiles.erasure.erase_subject` — one implementation of the
protocol for the fleet, and the probe still answered from the subscriber
that erases.

The other half of an account's life cycle IS answered here: ``user.merged``
RE-PARENTS. Answering the deletion half and not this one is not neutral
about it — it is a silent, wrong answer, which is what
``stapel_core.lifecycle.E001`` reports.
"""
import logging

from django.core.exceptions import ValidationError

from stapel_core.comm import on_action

logger = logging.getLogger(__name__)


def _merge_profiles(from_user_id, into_user_id) -> dict[str, int]:
    """Fold one account's profile rows into the surviving account.

    Callers hold the transaction; this returns what it touched, which is
    what makes a redelivery's ``0`` visible instead of silent.
    """
    from .models import UserRelationship, get_profile_model

    Profile = get_profile_model()
    counts = {
        "profiles_archived": 0,
        "relationships_moved": 0,
        "relationships_dropped": 0,
    }

    counts["profiles_archived"] = int(
        Profile.objects.filter(
            user_id=from_user_id, merged_into__isnull=True
        ).update(merged_into=into_user_id)
    )

    # Both directions: a relationship is somebody's row about a person, and
    # the merged account appears on either side of it.
    for side, other in (("follower_id", "following_id"), ("following_id", "follower_id")):
        taken = set(
            UserRelationship.objects.filter(**{side: into_user_id}).values_list(
                other, flat=True
            )
        )
        for rel in UserRelationship.objects.filter(**{side: from_user_id}):
            counterpart = getattr(rel, other)
            if counterpart == into_user_id or counterpart in taken:
                # Moving this row would either point the survivor at itself
                # (`no_self_relationship`) or duplicate one it already holds
                # (`unique_relationship`). The survivor's own row wins; this
                # one carries nothing the survivor does not already have.
                rel.delete()
                counts["relationships_dropped"] += 1
            else:
                setattr(rel, side, into_user_id)
                rel.save(update_fields=[side])
                taken.add(counterpart)
                counts["relationships_moved"] += 1
    return counts


@on_action("user.merged")
def handle_user_merged(event):
    """Fold a merged account's profile rows onto the survivor.

    ``user.merged`` (stapel-auth 0.30.0) fires when a guest account is
    folded into an account that already exists: ``from_user_id`` stops
    existing and every row that named it belongs to ``into_user_id`` now.
    It is the opposite of :func:`handle_user_deleted` above — nothing is
    erased — and an app that answered only the deletion half would leave
    the guest's profile and every follow and block naming it pointing at an
    id that can no longer sign in (``stapel_core.lifecycle.E001``).

    **Merge policy — the survivor's profile wins, the merged one is
    archived.** A profile's primary key IS the user id, so two profiles
    cannot become one row and something has to lose. The survivor loses
    nothing: its row is not read, not written and not created here. The
    merged row is kept and flagged (``ProfileCore.merged_into``), never
    deleted — it is still a record of what that person wrote, and the
    public read already gates on the account existing in auth
    (``cards.existing_users``), which the merged one no longer does.

    Nothing is copied across. A guest's display name or avatar landing on
    an established account would be the same violation
    :func:`_prefill_display_name` exists to prevent: the owner of a name is
    the person it names, and signing in to a real account is a statement
    about which identity the person means to keep. A survivor with no
    profile row at all therefore stays without one — a merge is not a
    registration, and ``user.registered`` is what provisions rows.

    Relationships DO move: a follow or a block is a decision about another
    person, and losing it would silently un-block somebody. Rows that would
    collide with one the survivor already holds, or would point the
    survivor at itself, are dropped instead — the survivor's own row wins.

    Idempotent: the profile update filters on ``merged_into IS NULL`` and
    the relationship walk filters on the merged id, neither of which
    matches after the first run, so a redelivery reports zeroes.
    """
    import uuid

    from django.db import transaction

    payload = event.payload or {}
    from_user_id = payload.get("from_user_id")
    into_user_id = payload.get("into_user_id")
    if not from_user_id or not into_user_id:
        logger.error(
            "user.merged event without both account ids: %s",
            getattr(event, "event_id", "?"),
        )
        return

    try:
        # Normalised here, not in the queryset: the relationship walk
        # compares ids in Python, and a string never equals the UUID a
        # UUIDField hands back.
        merged_id = uuid.UUID(str(from_user_id))
        survivor_id = uuid.UUID(str(into_user_id))
        if merged_id == survivor_id:
            logger.error(
                "user.merged names one account twice (%s): %s",
                from_user_id, getattr(event, "event_id", "?"),
            )
            return
        with transaction.atomic():
            counts = _merge_profiles(merged_id, survivor_id)
    except (TypeError, ValueError, ValidationError):
        # ValidationError is in the list on purpose: a UUIDField rejects a
        # malformed key with ValidationError, which is NOT a ValueError,
        # and a handler that caught only the latter would raise into the
        # bus and be redelivered forever for a payload that can never work.
        logger.error(
            "user.merged with unusable ids (from=%r into=%r): %s",
            from_user_id, into_user_id, getattr(event, "event_id", "?"),
        )
        return
    logger.info(
        "profiles merged %s into %s: %s", from_user_id, into_user_id, counts,
    )


def _provision_profile(user_id) -> None:
    """Create the profile row the moment the account is born.

    **The defect this closes.** Until 0.15.0 a profile row was created
    lazily, by the OWNER's first ``GET .../me``. Everything that renders a
    person to SOMEBODY ELSE — a seller block on a listing, a name next to a
    chat message, the author of a review — reads
    ``GET .../<user_id>`` instead, and for a registered user who had simply
    never opened their own profile that read was a 404. On a live
    marketplace that showed up as no names anywhere: the account existed,
    the product just had nowhere to read it from.

    Registration is the event that says a person now exists in this product,
    so it is the event that provisions their row. The row is EMPTY — the
    honest state of a person who has typed nothing yet — but it exists, so
    the public read answers 200 with a renderable shape instead of an error
    every consumer has to special-case.

    Idempotent by construction (``get_or_create``): delivery is at-least-once
    and a redelivery must not disturb a row the human has since filled in.

    Known interaction with erasure: :func:`~stapel_profiles.erasure.
    erase_account` DELETES the row, so a broker replay of a very old
    ``user.registered`` would re-create an empty one. It carries no personal
    data beyond the id, and the account it names is gone from auth — so the
    public read gates on the user still existing (``views._existing_users``)
    and answers 404 for it either way. Deliberately not defended with a
    tombstone table: that would be new permanent storage about erased people
    to protect against a stale empty row.
    """
    from .models import get_profile_model

    Profile = get_profile_model()
    _, created = Profile.objects.get_or_create(user_id=user_id)
    if created:
        logger.info("provisioned profile row for user %s at registration", user_id)


def _prefill_display_name(user_id, hint) -> None:
    """Pre-fill a new profile's display name from the registration hint.

    ``user.registered`` may carry a ``display_name`` — the name whoever
    created the account typed for this person (an org admin provisioning a
    login via ``auth.provision_user``, an admin inviting by email, an OAuth
    provider's profile name). It is a **pre-fill, not an assignment**: the
    owner of a name is the person it names, never the person who invited
    them, so the onboarding form must be free to show it and let the human
    overwrite it.

    That semantics is one guard: **never write over a name the human could
    have set themselves.** "The stored name is empty" alone is NOT that
    guard — delivery is at-least-once, so consider a user who deliberately
    CLEARS their name and then gets the registration event redelivered:
    with an emptiness-only test the admin's hint would resurrect itself over
    the user's deletion. So the pre-fill also stops at the onboarding
    boundary (``initial_setup_passed``): once the human has been through
    setup, the name is theirs — empty included — and a late/redelivered hint
    is a no-op. Concretely we write only when:

    * no profile row exists yet (the common case — the hint arrives before
      the user's first ``GET /me``), or
    * the row exists with an empty ``display_name`` AND onboarding is not
      done (``GET /me`` creates an empty row on first render; the hint must
      still land there).

    The hint is untrusted input from another service, so it is held to this
    module's own name canon (:func:`validators.validate_display_name` plus
    the model's ``max_length``) before it is written. A hint that fails is
    *declined and logged*, never truncated or sanitized into something the
    admin did not type: a mangled name is worse than an empty field the
    user fills in during onboarding.

    Best-effort, like the avatar import below: the account exists either
    way, and a name that failed to pre-fill is a blank onboarding field, not
    a failed registration.
    """
    if not hint or not isinstance(hint, str):
        # No hint (the common case — plain email/OTP registration) or a
        # non-string payload value: nothing to pre-fill, not an error.
        return

    from django.core.exceptions import FieldDoesNotExist

    from .models import get_profile_model

    Profile = get_profile_model()
    try:
        field = Profile._meta.get_field("display_name")
    except FieldDoesNotExist:
        # A host-swapped profile model without a display name (§66 field
        # constructor): there is nothing to pre-fill.
        return

    name = hint.strip()
    if not name:
        # Whitespace-only hint. Not an error, but not a name either — leave
        # the (already provisioned) row's empty display_name alone.
        return

    max_length = getattr(field, "max_length", None)
    if max_length and len(name) > max_length:
        logger.warning(
            "display_name hint for user %s declined: %d chars > max_length %d",
            user_id,
            len(name),
            max_length,
        )
        return

    from stapel_core.django.api.errors import StapelValidationError

    from .validators import validate_display_name

    try:
        validate_display_name(name)
    except StapelValidationError as exc:
        logger.warning(
            "display_name hint for user %s declined by the name canon (%s)",
            user_id,
            getattr(exc, "error_key", exc),
        )
        return

    existing = Profile.objects.filter(user_id=user_id).first()
    if existing is not None and (
        existing.display_name or getattr(existing, "initial_setup_passed", False)
    ):
        # The human already owns this field — a set name, or an empty one
        # they kept through onboarding. Never clobber, never resurrect.
        return

    Profile.objects.update_or_create(
        user_id=user_id, defaults={"display_name": name}
    )
    logger.info("pre-filled display name for user %s from the registration hint", user_id)


@on_action("user.created")
def handle_user_created(event):
    """Provision the profile row for an identity, however that identity was born.

    ``user.registered`` was the only provisioning trigger until 0.20.5, and
    that was the wrong half of the pair. Auth emits TWO different facts, and
    the distinction is deliberate (``stapel_auth.events.UserProjectionPayload``
    says so in as many words — "NOT a second ``user.registered``"):

    * ``user.registered`` is a **milestone**: a person completed a signup
      FLOW. It is emitted from the registration helper and carries
      dead-reckoning hints auth does not even store — ``avatar_url``,
      ``display_name``, ``language``.
    * ``user.created`` is the **identity row itself**, emitted from a
      ``post_save`` observer on the user model, so it fires for every account
      that comes into existence by ANY route: ``auth.provision_user`` (an org
      admin creating a login), an admin action, a login grant, a shadow row
      materialised from a JWT.

    A profile is keyed on the IDENTITY, not on the flow. Subscribing only to
    the milestone therefore stranded every account born the other way, and on
    a live fleet it did exactly that: measured 2026-09-15, 33 of 265 accounts
    (12.5%) had no profile row, 24 of them with a ``user.created`` event and
    no ``user.registered`` — 16 of those had signed up that same month, so it
    was ongoing rather than historical. The symptom is the one
    :func:`_provision_profile` already describes: a public read of that person
    answers 404 and the product has no name to render anywhere.

    Subscribing to BOTH is not belt-and-braces and does not make the pair
    redundant. This handler creates the row; ``user.registered`` keeps doing
    what only it can — seeding the hints that only the milestone carries.
    ``get_or_create`` makes the overlap a no-op in whichever order the two
    events arrive, which matters because they are separate outbox rows with
    no ordering guarantee between them.
    """
    payload = event.payload or {}
    user_id = payload.get("user_id")
    if not user_id:
        logger.warning("user.created without user_id: %r", payload)
        return
    _provision_profile(user_id)


@on_action("user.registered")
def handle_user_registered(event):
    """Provision the profile row, pre-fill the name, import a provider avatar.

    Contract (``schemas/emits/user.registered.json`` in auth):
    ``{user_id, auth_type, email, avatar_url, language, display_name}``
    where ``avatar_url`` and ``display_name`` are ``str | null``.

    Provisioning comes FIRST and unconditionally — see
    :func:`_provision_profile` for why a registered user must have a row
    before they ever open the product. The two enrichments below (name
    hint, provider avatar) then fill that row in when the payload carries
    something to fill it with; neither is required for the row to exist.

    ``display_name`` is the pre-fill hint — see
    :func:`_prefill_display_name` for the "a person owns their own name"
    guard. It is handled FIRST and independently of the avatar: the avatar
    import is a network call that may fail, and a cosmetic avatar failure
    must not cost the account its name.

    ``avatar_url``: currently only OAuth registrations populate it. A
    payload without a usable ``avatar_url`` is a no-op: most registrations
    (email/phone/password OTP) carry no avatar and that is normal, not an
    error.

    Why re-host instead of storing the provider URL directly: even though
    ``avatar_source`` can now be ``url`` (§66), a raw external URL cannot be
    trusted long-term — provider hotlinks rot, and rendering one would leak
    every viewer's IP to Google/Facebook. So we pull the image once, through
    the SSRF-hardened ``cdn.import_from_url`` fetcher, and keep the CDN ref
    (``avatar_source="cdn"``).

    Idempotency + respect-user-choice (one guard serves both): if the profile
    already has a non-empty avatar we no-op *before* fetching. Delivery is
    at-least-once, so a redelivered event must not re-import; and a manually
    uploaded avatar is the user's choice and must never be clobbered by a
    late provider import. This also avoids re-hitting the provider on every
    redelivery.

    Best-effort, swallow-not-retry: any failure of the fetch/call/save is
    logged and swallowed. Letting it propagate would raise
    ``ActionDeliveryError`` and make the outbox relay redeliver the *whole*
    ``user.registered`` event — re-running every other subscriber (workspace
    creation, ...) in a retry storm — just because a cosmetic, non-critical
    avatar fetch of an attacker-influenced URL failed. The account exists
    without an avatar; that is an acceptable terminal state.
    """
    payload = event.payload
    user_id = payload.get("user_id")
    if not user_id:
        logger.error("user.registered event without user_id: %s", event.event_id)
        return

    try:
        _provision_profile(user_id)
    except Exception:
        # Same swallow-not-retry contract as the two enrichments below. A
        # user whose row failed to provision is back to the pre-0.15.0
        # lazy-creation behaviour (their first GET /me makes it), not a
        # failed registration — and re-running every other subscriber of
        # this event to retry it would be a far worse trade.
        logger.warning(
            "failed to provision profile row for user %s", user_id, exc_info=True
        )

    try:
        _prefill_display_name(user_id, payload.get("display_name"))
    except Exception:
        # Same swallow-not-retry contract as the avatar import below: an
        # unfilled name must not make the outbox replay the whole
        # registration event through every other subscriber.
        logger.warning(
            "failed to pre-fill display name for user %s", user_id, exc_info=True
        )

    avatar_url = payload.get("avatar_url")
    if not avatar_url:
        # No provider avatar (the common case) — nothing to do.
        return

    from .models import get_profile_model

    Profile = get_profile_model()

    existing = Profile.objects.filter(user_id=user_id).first()
    if existing is not None and existing.avatar:
        # Already has an avatar (user-set or previously imported) — idempotent
        # no-op; never overwrite a deliberate choice, never re-fetch.
        return

    try:
        from stapel_core.comm import call

        result = call(
            "cdn.import_from_url",
            {"url": avatar_url, "image_type": "avatar", "caller": str(user_id)},
        )
        ref = result.get("ref") if isinstance(result, dict) else None
        if not ref:
            logger.warning(
                "cdn.import_from_url returned no ref for user %s (payload=%r)",
                user_id,
                result,
            )
            return
        from .models import AvatarSource

        Profile.objects.update_or_create(
            user_id=user_id,
            defaults={"avatar": ref, "avatar_source": AvatarSource.CDN},
        )
        logger.info("imported provider avatar %s for user %s", ref, user_id)
    except Exception:
        # Best-effort: registration is done; the avatar is optional cosmetic.
        logger.warning(
            "failed to import provider avatar for user %s — leaving profile "
            "without an avatar",
            user_id,
            exc_info=True,
        )
