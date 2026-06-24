from django.apps import AppConfig


class ProfilesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "stapel_profiles"
    label = 'profiles'
    verbose_name = "Iron Profiles"

    def ready(self):
        from stapel_core.gdpr import gdpr_registry
        from .gdpr import ProfilesGDPRProvider
        gdpr_registry.register(ProfilesGDPRProvider())
