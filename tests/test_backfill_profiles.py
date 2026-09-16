"""The backfill has to read the RIGHT user list, or it proves nothing.

Default mode enumerates `get_user_model()`, which is correct for a monolith.
In a split deployment that table is a SHADOW, populated only when a person has
presented a JWT to this service — so the users most likely to lack a profile
are missing from it too, and enumerating it reports a confident `missing: 0`
while the gap is wide open.

Measured on a live fleet 2026-09-16: 33 accounts in auth had no profile row and
only 2 of them existed in profiles' shadow table.
"""
import uuid
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

from stapel_profiles.models import Profile

pytestmark = pytest.mark.django_db


def _run(*args):
    out = StringIO()
    call_command("backfill_profiles", *args, stdout=out)
    return out.getvalue()


def test_dry_run_writes_nothing(django_user_model):
    django_user_model.objects.create(username="a", email="a@x.io")
    out = _run("--dry-run")
    assert "DRY RUN" in out
    assert Profile.objects.count() == 0


def test_it_creates_the_missing_row(django_user_model):
    u = django_user_model.objects.create(username="b", email="b@x.io")
    _run()
    assert Profile.objects.filter(user_id=u.id).exists()


def test_it_is_idempotent(django_user_model):
    u = django_user_model.objects.create(username="c", email="c@x.io")
    _run()
    _run()
    assert Profile.objects.filter(user_id=u.id).count() == 1


def test_it_never_touches_an_existing_row(django_user_model):
    u = django_user_model.objects.create(username="d", email="d@x.io")
    Profile.objects.create(user_id=u.id, display_name="Chosen By A Human")
    _run()
    assert Profile.objects.get(user_id=u.id).display_name == "Chosen By A Human"


def test_inactive_accounts_are_skipped_by_default(django_user_model):
    u = django_user_model.objects.create(username="e", email="e@x.io", is_active=False)
    _run()
    assert not Profile.objects.filter(user_id=u.id).exists()
    _run("--include-inactive")
    assert Profile.objects.filter(user_id=u.id).exists()


# ── The split-deployment half ────────────────────────────────────────────


def test_ids_from_a_file_are_used_instead_of_the_local_table(tmp_path):
    """The ids exist in auth and NOT in this service's shadow table."""
    absent = [str(uuid.uuid4()) for _ in range(3)]
    path = tmp_path / "ids.txt"
    path.write_text("\n".join(absent) + "\n")

    assert get_user_model().objects.count() == 0  # nothing local to enumerate
    out = _run("--user-ids-file", str(path))

    assert Profile.objects.count() == 3
    for uid in absent:
        assert Profile.objects.filter(user_id=uid).exists()
    assert "ids.txt" in out


def test_the_local_table_alone_would_have_found_nothing(tmp_path):
    """The exact failure this option exists for."""
    absent = [str(uuid.uuid4()) for _ in range(3)]
    path = tmp_path / "ids.txt"
    path.write_text("\n".join(absent) + "\n")

    out = _run("--dry-run")
    assert "missing: 0" in out, out

    out = _run("--user-ids-file", str(path), "--dry-run")
    assert "missing: 3" in out, out


def test_the_file_tolerates_blanks_comments_and_duplicates(tmp_path):
    uid = str(uuid.uuid4())
    path = tmp_path / "ids.txt"
    path.write_text(f"# a comment\n\n{uid}\n{uid}\n   \n")
    _run("--user-ids-file", str(path))
    assert Profile.objects.filter(user_id=uid).count() == 1
