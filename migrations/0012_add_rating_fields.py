from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('profiles', '0011_add_auto_detected_language'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='rating_average',
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=3, null=True,
                help_text='Average rating from received reviews (synced from catalog)',
            ),
        ),
        migrations.AddField(
            model_name='profile',
            name='rating_count',
            field=models.IntegerField(
                default=0,
                help_text='Number of received reviews (synced from catalog)',
            ),
        ),
    ]
