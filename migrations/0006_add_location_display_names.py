from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0005_add_location_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='location_display_name_narrow',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Cached narrow location display name from geo service',
                max_length=255,
            ),
        ),
        migrations.AddField(
            model_name='profile',
            name='location_display_name_broad',
            field=models.CharField(
                blank=True,
                default='',
                help_text='Cached broad location display name from geo service',
                max_length=255,
            ),
        ),
    ]
