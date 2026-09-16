"""Create the missing profile row for every account that has none.

WHY A DEPLOYMENT NEEDS THIS
---------------------------
A profile row is provisioned by an EVENT — ``user.created`` for the identity,
``user.registered`` for the signup milestone — so accounts that predate the
event, or that were born while a subscription was wrong, have no row at all.
There is no third mechanism that would ever notice: the lazy
``get_or_create`` in ``GET .../me`` only fires if that particular person opens
their own profile, and a public read of somebody who never did answers 404.

Two populations, both real, measured on a live fleet on 2026-09-15:

* accounts older than the emitter itself (this deployment's outbox began
  2026-07-03; eight accounts predated it);
* accounts born through a route that emitted only the event this module was
  not listening to — 24 of them, still accruing, until 0.20.5 subscribed to
  ``user.created`` as well.

The second is closed at the source. This command is for the first, and for
any deployment adopting stapel-profiles into a product that already has
users, which is the same shape.

WHAT IT DOES NOT DO
-------------------
It creates an EMPTY row and nothing else — the honest state of a person who
has typed nothing. It does not invent a display name, does not import an
avatar, and does not touch a row that already exists, so it can never
overwrite something a human set. That is what makes it safe to re-run.

It also does not resurrect erased people: ``--skip-inactive`` is the default
for exactly that reason, and an account that GDPR erasure removed from the
user table is not enumerated at all, because the enumeration reads the user
table.

USAGE
    python manage.py backfill_profiles --dry-run     # count, change nothing
    python manage.py backfill_profiles               # create the rows
    python manage.py backfill_profiles --include-inactive
"""
import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

logger = logging.getLogger(__name__)

#: Rows per transaction. Bounded so a backfill over a large user table does
#: not hold one transaction open for its whole run.
BATCH = 500


class Command(BaseCommand):
    help = "Create an empty profile row for every user that has none (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created and write nothing.",
        )
        parser.add_argument(
            "--include-inactive",
            action="store_true",
            help=(
                "Also provision deactivated accounts. Off by default: a "
                "deactivated account is not rendered anywhere, so a row for "
                "it buys nothing, and the population most likely to be "
                "inactive is the one somebody is in the middle of removing."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Stop after this many creations (0 = no limit).",
        )

    def handle(self, *args, **options):
        from stapel_profiles.models import get_profile_model

        Profile = get_profile_model()
        User = get_user_model()

        users = User.objects.all()
        if not options["include_inactive"]:
            users = users.filter(is_active=True)

        # Both sides as id sets rather than a subquery join: the two models
        # may live in different databases in a split deployment, where a JOIN
        # is not available and a NOT IN subquery would silently be wrong.
        have = set(Profile.objects.values_list("user_id", flat=True))
        missing = [uid for uid in users.values_list("id", flat=True) if uid not in have]

        limit = options["limit"]
        if limit:
            missing = missing[:limit]

        total_users = users.count()
        self.stdout.write(
            f"users considered: {total_users}  "
            f"profiles present: {len(have)}  "
            f"missing: {len(missing)}"
        )

        if not missing:
            self.stdout.write(self.style.SUCCESS("nothing to backfill"))
            return

        if options["dry_run"]:
            for uid in missing[:20]:
                self.stdout.write(f"  would create: {uid}")
            if len(missing) > 20:
                self.stdout.write(f"  … and {len(missing) - 20} more")
            self.stdout.write(
                self.style.WARNING(f"DRY RUN — {len(missing)} row(s) NOT created")
            )
            return

        created = 0
        for start in range(0, len(missing), BATCH):
            chunk = missing[start:start + BATCH]
            with transaction.atomic():
                for uid in chunk:
                    # get_or_create rather than bulk_create: another process
                    # (the event handler, or this person opening /me) may
                    # create the same row while this runs, and a backfill
                    # that dies on a race it caused is not idempotent.
                    _, was_created = Profile.objects.get_or_create(user_id=uid)
                    created += 1 if was_created else 0
            self.stdout.write(f"  … {min(start + BATCH, len(missing))}/{len(missing)}")

        logger.info("backfill_profiles created %s profile row(s)", created)
        self.stdout.write(
            self.style.SUCCESS(
                f"created {created} profile row(s); "
                f"{len(missing) - created} already existed (created concurrently)"
            )
        )
