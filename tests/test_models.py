"""
Tests for profiles models.
"""
import uuid
import pytest
from django.db import IntegrityError
from stapel_profiles.models import (
    AvatarSource, Language, Profile, UserRelationship, RelationshipStatus
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
    """Tests for Profile model (hard core §66 — theme/currency_code/
    measurement_units/display_name moved to field_defs.py, covered in
    test_field_defs.py / test_swap_profile.py instead)."""

    def test_create_profile_defaults(self):
        """Test creating profile with defaults."""
        user_id = uuid.uuid4()
        profile = Profile.objects.create(user_id=user_id)

        assert profile.user_id == user_id
        assert profile.avatar_source == AvatarSource.FILE
        assert profile.avatar is None
        assert profile.app_language is None

    def test_create_profile_custom(self):
        """Test creating profile with custom values."""
        user_id = uuid.uuid4()
        lang = Language.objects.create(code='de', name='German')

        profile = Profile.objects.create(
            user_id=user_id,
            avatar_source=AvatarSource.URL,
            avatar="https://example.com/me.png",
            app_language=lang,
        )

        assert profile.avatar_source == AvatarSource.URL
        assert profile.avatar == "https://example.com/me.png"
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


@pytest.mark.django_db
class TestAvatarPairInvariant:
    """`avatar` + `avatar_source` are one value in two columns.

    Regression cover for the meettoday sandbox outage: both profiles that ever
    had an avatar (2 of 2) stored a real stapel-cdn ref tagged `file`, because
    the writer sent only the ref and let the model default pick the tag.
    Serializing such a row routed the ref to the PIL provider, which opened the
    cdn variant DIRECTORY as a file and raised — a cosmetic avatar 500'd
    `/profiles/api/v1/me`, and through it the whole product for two people.
    """

    CDN_REF = "avatar/" + "b" * 64

    def test_untagged_cdn_ref_is_stored_as_cdn(self):
        profile = Profile.objects.create(user_id=uuid.uuid4(), avatar=self.CDN_REF)

        profile.refresh_from_db()
        assert profile.avatar_source == AvatarSource.CDN

    def test_mis_tagged_cdn_ref_cannot_survive_a_save(self):
        profile = Profile.objects.create(user_id=uuid.uuid4())
        profile.avatar = self.CDN_REF
        profile.avatar_source = AvatarSource.FILE

        profile.save()

        profile.refresh_from_db()
        assert profile.avatar_source == AvatarSource.CDN

    def test_repair_survives_a_partial_save(self):
        """`update_or_create` and every partial write pass `update_fields`;
        without widening it the repaired tag would be computed and dropped."""
        profile = Profile.objects.create(user_id=uuid.uuid4())
        profile.avatar = self.CDN_REF

        profile.save(update_fields=["avatar"])

        profile.refresh_from_db()
        assert profile.avatar == self.CDN_REF
        assert profile.avatar_source == AvatarSource.CDN

    def test_update_or_create_stores_the_pair(self):
        user_id = uuid.uuid4()
        Profile.objects.create(user_id=user_id)

        Profile.objects.update_or_create(
            user_id=user_id, defaults={"avatar": self.CDN_REF}
        )

        assert Profile.objects.get(user_id=user_id).avatar_source == AvatarSource.CDN

    def test_free_form_refs_keep_their_declared_source(self):
        """Derivation moves ONLY an unmistakable cdn ref. An upload key, a URL
        and a gravatar hash are free-form and stay exactly as declared."""
        for source, value in (
            (AvatarSource.FILE, "uploads/ada.png"),
            (AvatarSource.URL, "https://example.com/me.png"),
            (AvatarSource.GRAVATAR, "d" * 32),
            # right shape, wrong type segment — not an avatar cdn ref
            (AvatarSource.FILE, "product/" + "b" * 64),
        ):
            profile = Profile.objects.create(
                user_id=uuid.uuid4(), avatar=value, avatar_source=source
            )
            profile.refresh_from_db()
            assert profile.avatar_source == source, value

    def test_clean_rejects_the_mismatch_for_validating_callers(self):
        from django.core.exceptions import ValidationError

        profile = Profile(
            user_id=uuid.uuid4(),
            avatar=self.CDN_REF,
            avatar_source=AvatarSource.FILE,
        )
        with pytest.raises(ValidationError):
            profile.clean()
