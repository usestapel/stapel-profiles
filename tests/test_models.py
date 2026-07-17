"""
Tests for profiles models.
"""
import uuid
import pytest
from django.db import IntegrityError
from stapel_profiles.models import (
    Language, Profile, UserRelationship,
    MeasurementUnit, Theme, RelationshipStatus
)


@pytest.mark.django_db
class TestLanguageModel:
    """Tests for Language model."""

    def test_create_language(self):
        """Test creating a language."""
        lang = Language.objects.create(
            code='en',
            name='English'
        )
        assert lang.code == 'en'
        assert lang.name == 'English'
        assert str(lang) == 'English (en)'

    def test_language_ordering(self):
        """Test languages are ordered by name."""
        Language.objects.create(code='de', name='German')
        Language.objects.create(code='en', name='English')
        Language.objects.create(code='ru', name='Russian')

        langs = list(Language.objects.all())
        assert langs[0].code == 'en'
        assert langs[1].code == 'de'
        assert langs[2].code == 'ru'


@pytest.mark.django_db
class TestProfileModel:
    """Tests for Profile model."""

    def test_create_profile_defaults(self):
        """Test creating profile with defaults."""
        user_id = uuid.uuid4()
        profile = Profile.objects.create(user_id=user_id)

        assert profile.user_id == user_id
        assert profile.currency_code == 'USD'
        assert profile.measurement_units == MeasurementUnit.METRIC
        assert profile.theme == Theme.SYSTEM
        assert profile.app_language is None

    def test_create_profile_custom(self):
        """Test creating profile with custom values."""
        user_id = uuid.uuid4()
        lang = Language.objects.create(code='de', name='German')

        profile = Profile.objects.create(
            user_id=user_id,
            currency_code='USD',
            measurement_units=MeasurementUnit.IMPERIAL,
            theme=Theme.DARK,
            app_language=lang
        )

        assert profile.currency_code == 'USD'
        assert profile.measurement_units == MeasurementUnit.IMPERIAL
        assert profile.theme == Theme.DARK
        assert profile.app_language == lang

    def test_profile_understands_languages(self):
        """Test profile understands many languages."""
        user_id = uuid.uuid4()
        en = Language.objects.create(code='en', name='English')
        de = Language.objects.create(code='de', name='German')

        profile = Profile.objects.create(user_id=user_id)
        profile.understands.add(en, de)

        assert profile.understands.count() == 2
        assert en in profile.understands.all()
        assert de in profile.understands.all()

    def test_profile_str(self):
        """Test profile string representation."""
        user_id = uuid.uuid4()
        profile = Profile.objects.create(user_id=user_id)
        assert str(profile) == f'Profile({user_id})'


@pytest.mark.django_db
class TestUserRelationshipModel:
    """Tests for UserRelationship model."""

    def test_create_relationship(self):
        """Test creating a relationship."""
        follower_id = uuid.uuid4()
        following_id = uuid.uuid4()

        rel = UserRelationship.objects.create(
            follower_id=follower_id,
            following_id=following_id,
            status=RelationshipStatus.FOLLOWING
        )

        assert rel.follower_id == follower_id
        assert rel.following_id == following_id
        assert rel.status == RelationshipStatus.FOLLOWING

    def test_relationship_default_status(self):
        """Test relationship default status is neutral."""
        rel = UserRelationship.objects.create(
            follower_id=uuid.uuid4(),
            following_id=uuid.uuid4()
        )
        assert rel.status == RelationshipStatus.NEUTRAL

    def test_relationship_unique_constraint(self):
        """Test unique constraint on follower/following pair."""
        follower_id = uuid.uuid4()
        following_id = uuid.uuid4()

        UserRelationship.objects.create(
            follower_id=follower_id,
            following_id=following_id
        )

        with pytest.raises(IntegrityError):
            UserRelationship.objects.create(
                follower_id=follower_id,
                following_id=following_id
            )

    def test_no_self_relationship(self):
        """Test cannot create self-relationship."""
        user_id = uuid.uuid4()

        with pytest.raises(IntegrityError):
            UserRelationship.objects.create(
                follower_id=user_id,
                following_id=user_id
            )

    def test_relationship_str(self):
        """Test relationship string representation."""
        follower_id = uuid.uuid4()
        following_id = uuid.uuid4()

        rel = UserRelationship.objects.create(
            follower_id=follower_id,
            following_id=following_id,
            status=RelationshipStatus.FOLLOWING
        )
        assert str(rel) == f'{follower_id} -> {following_id} (following)'
