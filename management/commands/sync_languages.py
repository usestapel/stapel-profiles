"""
Management command to sync languages from fixture without overwriting flags.
"""
import json
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from stapel_profiles.models import Language


class Command(BaseCommand):
    help = 'Sync languages from fixture, preserving existing flag values'

    def handle(self, *args, **options):
        fixtures_dir = Path(__file__).resolve().parent.parent.parent / 'fixtures'
        fixture_path = fixtures_dir / 'languages.json'
        flags_source_dir = fixtures_dir / 'flags'

        if not fixture_path.exists():
            self.stderr.write(self.style.ERROR(f'Fixture not found: {fixture_path}'))
            return

        # Copy flag files to media directory
        if flags_source_dir.exists():
            media_flags_dir = Path(settings.MEDIA_ROOT) / 'flags'
            media_flags_dir.mkdir(parents=True, exist_ok=True)

            copied_flags = 0
            for flag_file in flags_source_dir.glob('*.svg'):
                dest = media_flags_dir / flag_file.name
                if not dest.exists():
                    shutil.copy2(flag_file, dest)
                    copied_flags += 1

            if copied_flags:
                self.stdout.write(f'  Copied {copied_flags} flag files to media')

        with open(fixture_path) as f:
            languages_data = json.load(f)

        created_count = 0
        updated_count = 0
        skipped_count = 0

        for item in languages_data:
            code = item['pk']
            fields = item['fields']

            try:
                language = Language.objects.get(code=code)
                # Update only empty fields
                updated_fields = []
                if not language.name and fields.get('name'):
                    language.name = fields['name']
                    updated_fields.append('name')
                if not language.flag and fields.get('flag'):
                    language.flag = fields['flag']
                    updated_fields.append('flag')

                if updated_fields:
                    language.save()
                    updated_count += 1
                    self.stdout.write(f'  Updated {code}: {", ".join(updated_fields)}')
                else:
                    skipped_count += 1
            except Language.DoesNotExist:
                Language.objects.create(
                    code=code,
                    name=fields['name'],
                    flag=fields.get('flag', ''),
                )
                created_count += 1
                self.stdout.write(f'  Created: {code} ({fields["name"]})')

        self.stdout.write(
            self.style.SUCCESS(
                f'Sync complete: {created_count} created, {updated_count} updated, {skipped_count} unchanged'
            )
        )
