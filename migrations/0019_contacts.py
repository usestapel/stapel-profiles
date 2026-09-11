"""Seller contacts — two new tables, nothing touched (expand-only).

`profiles_contact` holds the numbers a person published, with their proof
(`verified_at`), their on/off switch and their per-number policy;
`profiles_contact_reveal` is the journal of every hand-over. No existing
column is altered or dropped, so this migration applies to a live database
ahead of the code that reads it, and rolls back by dropping two tables
nothing else references.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0018_profile_merged_into'),
    ]

    operations = [
        migrations.CreateModel(
            name='Contact',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('owner_key', models.UUIDField(db_index=True, help_text='User UUID this contact belongs to')),
                ('kind', models.CharField(choices=[('phone', 'Phone')], default='phone', max_length=16)),
                ('value', models.CharField(help_text='E.164 phone number', max_length=32)),
                ('label', models.CharField(blank=True, default='', help_text='Owner\'s own label, e.g. "Work"', max_length=64)),
                ('verified_at', models.DateTimeField(blank=True, null=True)),
                ('enabled', models.BooleanField(default=True)),
                ('policy', models.CharField(choices=[('members', 'Any registered member'), ('verified', 'Members with a verified email or phone'), ('nobody', 'Nobody')], default='members', max_length=16)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Contact',
                'verbose_name_plural': 'Contacts',
                'db_table': 'profiles_contact',
                'ordering': ['created_at', 'id'],
                'indexes': [models.Index(fields=['owner_key', 'kind'], name='profiles_contact_own_kind')],
                'constraints': [models.UniqueConstraint(fields=('owner_key', 'value'), name='profiles_contact_owner_value_uniq')],
            },
        ),
        migrations.CreateModel(
            name='ContactReveal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('viewer_key', models.UUIDField(db_index=True, help_text='User UUID of the viewer')),
                ('listing_id', models.CharField(blank=True, default='', max_length=64)),
                ('at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('ip', models.GenericIPAddressField(blank=True, null=True)),
                ('contact', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reveals', to='profiles.contact')),
            ],
            options={
                'verbose_name': 'Contact reveal',
                'verbose_name_plural': 'Contact reveals',
                'db_table': 'profiles_contact_reveal',
                'ordering': ['-at', '-id'],
                'indexes': [models.Index(fields=['contact', 'at'], name='profiles_reveal_cont_at'), models.Index(fields=['viewer_key', 'at'], name='profiles_reveal_view_at')],
            },
        ),
    ]
