# stapel: contract-phase
#
# §66 alpha-cut (docs/pending/profile-fields.md, owner GO 2026-07-17):
# deletion-driven, no compat shim (pre-1.0 alpha policy) — theme/
# currency_code/measurement_units/display_name leave the hard Profile model;
# a project picks them back up via field_defs.STANDARD_FIELDS /
# IDENTITY_PRESETS in its OWN app. avatar becomes source+ref (prep for §67).
# No prior "expand" release removed usage first (normal expand/contract does
# not apply pre-1.0 — memory convention: migrations are deletion-driven and
# ship directly in main); marked contract-phase deliberately, not because a
# code-side expand already merged.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0015_alter_profile_currency_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='avatar_source',
            field=models.CharField(
                choices=[('file', 'File'), ('url', 'URL'), ('gravatar', 'Gravatar'), ('cdn', 'CDN')],
                default='file',
                help_text='Where `avatar` points: uploaded file key, arbitrary URL, '
                          'Gravatar email-hash, or a CDN ref. Defaults to file/url — '
                          'cdn is opt-in, not the default.',
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name='profile',
            name='avatar',
            field=models.CharField(
                blank=True,
                help_text="Avatar reference matching avatar_source: CDN 'avatar/<hash>' "
                          'ref, a Gravatar email-hash, a plain URL, or an uploaded file key.',
                max_length=500,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name='profile',
            name='app_language',
            field=models.ForeignKey(
                blank=True,
                help_text='Primary app language (default: English)',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+',
                to='profiles.language',
            ),
        ),
        migrations.AlterField(
            model_name='profile',
            name='understands',
            field=models.ManyToManyField(
                blank=True,
                help_text='Languages the user understands',
                related_name='+',
                to='profiles.language',
            ),
        ),
        migrations.RemoveField(
            model_name='profile',
            name='display_name',
        ),
        migrations.RemoveField(
            model_name='profile',
            name='currency_code',
        ),
        migrations.RemoveField(
            model_name='profile',
            name='measurement_units',
        ),
        migrations.RemoveField(
            model_name='profile',
            name='theme',
        ),
    ]
