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
#: `avatar` is unmistakably a CDN ref (`avatar/<64-hex>`) but the request
#: EXPLICITLY tagged it something else. Not coerced: a caller that stated a
#: source stated a belief, and silently "correcting" a stated belief hides the
#: caller's bug. A caller that states nothing gets the source derived from the
#: ref instead (models.resolve_avatar_source) — nothing to correct there.
ERR_400_AVATAR_SOURCE_MISMATCH = 'error.400.avatar_source_mismatch'
#: POST .../batch over PROFILES_BATCH_MAX_IDS. Carries BOTH numbers so the
#: caller can chunk without guessing — the alternative (truncate to the limit
#: and answer 200) would hide the overflow as "those people have no profile".
ERR_400_TOO_MANY_IDS = 'error.400.too_many_ids'
#: An `avatar_source=url` avatar whose scheme this service will not accept.
#: The avatar is a string one user controls and every consumer renders, so
#: only inert, transport-safe schemes cross the boundary (an active scheme is
#: code, and plain http leaks the referrer and downgrades the page).
ERR_400_AVATAR_URL_SCHEME = 'error.400.avatar_url_scheme'
#: An external avatar host the deployment does not allow
#: (PROFILES_AVATAR_URL_ALLOWED_HOSTS) — the anti-tracking half of the same
#: boundary: an arbitrary host turns every profile view into a beacon.
ERR_400_AVATAR_URL_HOST = 'error.400.avatar_url_host'
#: `avatar_source=gravatar` carries an email HASH, not a path or a URL; the
#: value is interpolated into a gravatar URL, so anything else is refused.
ERR_400_AVATAR_GRAVATAR_HASH = 'error.400.avatar_gravatar_hash'

# ── Contacts (contacts/) ─────────────────────────────────────────────────
#: The reveal door. A caller with no account — the unsigned internet OR a
#: guest session, which is `is_authenticated` and nobody — asked for a
#: seller's number. NOT the generic 403: the storefront's answer to this is
#: to open full registration, and it can only know that from a key that says
#: "register", not one that says "forbidden". One key for both callers on
#: purpose — the remedy is the same, and splitting it into a 401 for the
#: signed-out and a 403 for the guest would give the frontend two doors to
#: the same room.
ERR_403_CONTACTS_REGISTRATION_REQUIRED = 'error.403.contacts_registration_required'
#: The viewer's hourly reveal budget is spent (`CONTACTS.REVEAL_PER_HOUR`).
#: Carries `retry_after` in seconds so the client can say "in 7 minutes"
#: instead of "later". Its own key, not the shared `error.429.rate_limit`:
#: this is the anti-scraping ceiling on ONE endpoint, and a client that
#: cannot tell it from a generic throttle cannot phrase it.
ERR_429_CONTACTS_REVEAL_BUDGET = 'error.429.contacts_reveal_budget'
#: The submitted string is not a storable phone number — not in
#: international form, or an implausible length for its country.
ERR_400_CONTACTS_INVALID_PHONE = 'error.400.contacts_invalid_phone'
#: A policy value this deployment does not offer. Carries the list it does,
#: so the caller can correct itself instead of guessing.
ERR_400_CONTACTS_INVALID_POLICY = 'error.400.contacts_invalid_policy'
#: This person already holds that number. Refused rather than silently
#: returning the existing row: "added" and "you already had it" are
#: different answers, and the second one is why the policy the caller just
#: sent was not applied.
ERR_409_CONTACTS_DUPLICATE = 'error.409.contacts_duplicate'
#: No such contact OF THE CALLER'S. Somebody else's contact answers with
#: this too — a 403 would confirm the row exists, which is precisely the
#: enumeration this module refuses everywhere else.
ERR_404_CONTACT_NOT_FOUND = 'error.404.contact_not_found'
#: Wrong code. Carries `attempts_remaining` — the count lives with the code
#: in the core store, so it is the truth rather than a client's guess.
ERR_400_CONTACTS_INVALID_CODE = 'error.400.contacts_invalid_code'
#: Nothing is waiting: the code aged out, was already spent, or the store
#: restarted. Deliberately NOT `invalid_code` — three ways of "ask for a new
#: one", none of which is "you mistyped".
ERR_400_CONTACTS_CODE_EXPIRED = 'error.400.contacts_code_expired'
#: The OTP provider refused: too many sends, or the attempt budget is spent
#: and the penalty has not elapsed. Carries `retry_after` in seconds.
ERR_429_CONTACTS_CODE_RATE = 'error.429.contacts_code_rate'
#: The code could not be issued or could not be checked — the store or the
#: SMS path is down. 503, not 400: "we could not ask" is not "you are
#: wrong", and rendering the second as the first tells a user their correct
#: code was rejected.
ERR_503_CONTACTS_CODE_UNAVAILABLE = 'error.503.contacts_code_unavailable'

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
    ERR_400_AVATAR_SOURCE_MISMATCH: (
        'Avatar reference is a CDN reference but avatar_source says '
        'otherwise — send avatar_source="cdn" with it, or omit avatar_source '
        'and it will be derived from the reference'
    ),
    ERR_400_TOO_MANY_IDS: 'Too many ids: {requested} requested, at most {limit} per batch request',
    ERR_400_AVATAR_URL_SCHEME: 'Avatar URL must use one of: {schemes}',
    ERR_400_AVATAR_URL_HOST: 'Avatar URL host is not allowed here',
    ERR_400_AVATAR_GRAVATAR_HASH: 'Gravatar avatar must be an email hash (32 or 64 hex characters)',
    ERR_403_CONTACTS_REGISTRATION_REQUIRED: 'Register an account to see a seller\'s phone number',
    ERR_429_CONTACTS_REVEAL_BUDGET: 'Too many phone lookups. Try again in {retry_after} seconds.',
    ERR_400_CONTACTS_INVALID_PHONE: 'Enter the phone number in international form, starting with +',
    ERR_400_CONTACTS_INVALID_POLICY: 'Unknown visibility policy. Allowed here: {policies}',
    ERR_409_CONTACTS_DUPLICATE: 'You have already added this number',
    ERR_404_CONTACT_NOT_FOUND: 'Contact not found',
    ERR_400_CONTACTS_INVALID_CODE: 'Wrong code. {attempts_remaining} attempt(s) left.',
    ERR_400_CONTACTS_CODE_EXPIRED: 'That code is no longer valid. Ask for a new one.',
    ERR_429_CONTACTS_CODE_RATE: 'Too many attempts. Try again in {retry_after} seconds.',
    ERR_503_CONTACTS_CODE_UNAVAILABLE: 'The code could not be sent right now. Try again shortly.',
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
    ERR_400_AVATAR_SOURCE_MISMATCH: 'fix_input',
    ERR_400_TOO_MANY_IDS: 'fix_input',
    ERR_400_AVATAR_URL_SCHEME: 'fix_input',
    ERR_400_AVATAR_URL_HOST: 'fix_input',
    ERR_400_AVATAR_GRAVATAR_HASH: 'fix_input',
    # The contacts keys are the module's first ones whose honest recovery is
    # NOT "correct the input": the door needs an account, the two ceilings
    # need time, and the unavailable one needs a retry the caller did nothing
    # to deserve.
    ERR_403_CONTACTS_REGISTRATION_REQUIRED: 'reauthenticate',
    ERR_429_CONTACTS_REVEAL_BUDGET: 'wait_and_retry',
    ERR_400_CONTACTS_INVALID_PHONE: 'fix_input',
    ERR_400_CONTACTS_INVALID_POLICY: 'fix_input',
    ERR_409_CONTACTS_DUPLICATE: 'fix_input',
    ERR_404_CONTACT_NOT_FOUND: 'fix_input',
    ERR_400_CONTACTS_INVALID_CODE: 'fix_input',
    ERR_400_CONTACTS_CODE_EXPIRED: 'retry',
    ERR_429_CONTACTS_CODE_RATE: 'wait_and_retry',
    ERR_503_CONTACTS_CODE_UNAVAILABLE: 'retry',
}

register_service_errors(PROFILES_ERRORS, remediation=PROFILES_REMEDIATION)


class ProfilesErrorKeysView(ErrorKeysView):
    def get_service_errors(self):
        return PROFILES_ERRORS
