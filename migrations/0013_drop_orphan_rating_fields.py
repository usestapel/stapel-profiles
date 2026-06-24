"""Drop rating_average / rating_count — orphaned by the catalog/review removal."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0012_add_rating_fields'),
    ]

    operations = [
        migrations.RemoveField(model_name='profile', name='rating_average'),
        migrations.RemoveField(model_name='profile', name='rating_count'),
    ]
