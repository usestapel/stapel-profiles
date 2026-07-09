"""Drop rating_average / rating_count — orphaned by the catalog/review removal."""

# stapel: contract-phase
# verified: rating_average/rating_count were added in 0012_add_rating_fields
# and dropped here in 0013, both within stapel-profiles' first commit/release
# (v0.2.0+); grep confirms no non-migration reference to either field
# anywhere in the current codebase, and no released version of this package
# ever shipped 0012 without 0013 alongside it.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0012_add_rating_fields'),
    ]

    operations = [
        migrations.RemoveField(model_name='profile', name='rating_average'),
        migrations.RemoveField(model_name='profile', name='rating_count'),
    ]
