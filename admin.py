"""
Admin configuration for profiles app.
"""
from django.contrib import admin
from .models import Language, Profile, UserRelationship


@admin.register(Language)
class LanguageAdmin(admin.ModelAdmin):
    """Admin for Language model."""
    list_display = ['code', 'name', 'flag', 'is_active']
    list_filter = ['is_active']
    search_fields = ['code', 'name']
    ordering = ['name']


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    """Admin for Profile model."""
    list_display = [
        'user_id', 'currency_code', 'measurement_units',
        'theme', 'app_language', 'created_at'
    ]
    list_filter = ['currency_code', 'measurement_units', 'theme', 'app_language']
    search_fields = ['user_id']
    filter_horizontal = ['understands']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']


@admin.register(UserRelationship)
class UserRelationshipAdmin(admin.ModelAdmin):
    """Admin for UserRelationship model."""
    list_display = ['follower_id', 'following_id', 'status', 'created_at']
    list_filter = ['status']
    search_fields = ['follower_id', 'following_id']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']
