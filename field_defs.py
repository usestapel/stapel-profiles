"""Standard-field registry for the profile constructor (§66,
docs/pending/profile-fields.md §2/§3).

`stapel_profiles.models.ProfileCore` only carries what every Stapel profile
needs regardless of domain (see models.py). Everything a specific product
might or might not need — identity shape, theme, currency, measurement
units, geohash — lives here as data (`ProfileFieldDef` instances), not as
hardcoded model fields. A project picks a subset (a manifest: identity
preset + standard field names + its own custom `ProfileFieldDef`s) and either:

- calls :func:`build_profile_model` itself, in its OWN app's ``models.py``,
  to get a concrete swappable ``Profile`` subclass (registered under
  ``STAPEL_SWAP["PROFILES_PROFILE_MODEL"]`` — see ``stapel_profiles.models``);
  or
- (later) lets the stapel-tools codegen step (§3 of the governing spec, not
  part of this pass — "не ждать §53/§52") do the same thing plus write the
  migration file into the project app automatically.

Owner directive (2026-07-17): avatar and the whole language block stay HARD
in ``ProfileCore`` (not in this registry) — only theme/currency/measurement
units/identity/geohash are constructor material.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Type

from django.db import models


class ProfileFieldKind(str, Enum):
    """Discriminator for a profile field's storage/presentation shape.

    Deliberately mirrors ``stapel_attributes.config_form.FIELD_KINDS`` naming
    style (not the same dict — profile fields are Django model fields, not
    admin-config-form fields) so a field's shop/classified projection into an
    attribute can pick a matching FIELD_KINDS entry mechanically
    (``stapel_attributes.profile_bridge``, §4 of the governing spec) instead
    of re-deriving the shape by hand.
    """

    TEXT = "text"
    BOOL = "bool"
    ENUM = "enum"
    MODEL_REF = "model_ref"  # points at a live catalog's natural key, e.g. Currency.code
    GEOHASH = "geohash"


class StapelProfileEnum(models.TextChoices):
    """Base for every enum a profile field (standard OR custom) can use.

    Subclass this instead of a bare ``models.TextChoices`` — it lets the
    field-def registry (and future profile-enum tooling: admin filters,
    attribute projections) recognise "this choices class backs a profile
    field" via ``issubclass(x, StapelProfileEnum)`` rather than duck-typing
    ``.choices``. A project's OWN enum for a custom field (e.g. ironmemo's
    occupation) subclasses this too.
    """


class Theme(StapelProfileEnum):
    """UI theme choices."""

    LIGHT = "light", "Light"
    DARK = "dark", "Dark"
    SYSTEM = "system", "System"


class MeasurementUnit(StapelProfileEnum):
    """Measurement unit system choices — relevant only when the project also
    uses convertible attributes (stapel-attributes int/float with a unit
    postfix); see docs/pending/profile-fields.md §1 for why this is opt-in."""

    METRIC = "metric", "Metric"
    IMPERIAL = "imperial", "Imperial"


@dataclass
class ProfileFieldDef:
    """One field the profile constructor can splice into a project's
    extended Profile model (+ presenter).

    A docstring on every ``ProfileFieldDef`` instance's ``doc`` attribute is
    MANDATORY (not optional — there is no default) — same discipline as
    DOC-FIELD for Django model fields. ``doc`` feeds both the generated model
    field's ``help_text`` and the presenter's ``PresenterField.help_text``,
    and is what the field-manifest endpoint (views.FieldManifestView) reports
    to the frontend skin as ``docstring``.
    """

    name: str
    kind: "ProfileFieldKind"
    doc: str
    enum: Optional[Type[StapelProfileEnum]] = None  # kind=ENUM only
    model_ref: Optional[str] = None  # kind=MODEL_REF only, dotted "app.Model"
    default: Any = None
    blank: bool = True
    params: Dict[str, Any] = field(default_factory=dict)  # e.g. {"max_length": 35}

    def to_model_field(self) -> models.Field:
        """Build the concrete Django model field for this def.

        ``MODEL_REF`` is a plain string field storing the referenced
        catalog's natural key (e.g. a currency ISO code) — NOT a real
        ``ForeignKey`` — so ``stapel_profiles`` never gains a hard dependency
        on the referenced package (``stapel-currencies`` etc. stay optional,
        keeping profiles domain-blind per the projections-and-composition
        convention).
        """
        if self.kind is ProfileFieldKind.TEXT:
            return models.CharField(
                max_length=self.params.get("max_length", 255),
                default=self.default if self.default is not None else "",
                blank=self.blank,
                help_text=self.doc,
            )
        if self.kind is ProfileFieldKind.BOOL:
            return models.BooleanField(default=bool(self.default) if self.default is not None else False, help_text=self.doc)
        if self.kind is ProfileFieldKind.ENUM:
            if self.enum is None:
                raise ValueError(f"ProfileFieldDef {self.name!r}: kind=ENUM requires enum=")
            return models.CharField(
                max_length=self.params.get("max_length", 20),
                choices=self.enum.choices,
                default=self.default if self.default is not None else self.enum.values[0],
                blank=self.blank,
                help_text=self.doc,
            )
        if self.kind is ProfileFieldKind.MODEL_REF:
            if not self.model_ref:
                raise ValueError(f"ProfileFieldDef {self.name!r}: kind=MODEL_REF requires model_ref=")
            return models.CharField(
                max_length=self.params.get("max_length", 20),
                default=self.default if self.default is not None else "",
                blank=self.blank,
                help_text=self.doc,
            )
        if self.kind is ProfileFieldKind.GEOHASH:
            return models.CharField(
                max_length=self.params.get("max_length", 12),
                default=self.default if self.default is not None else "",
                blank=self.blank,
                help_text=self.doc,
            )
        raise ValueError(f"ProfileFieldDef {self.name!r}: unknown kind {self.kind!r}")

    def to_presenter_field(self):
        """Build the matching ``stapel_core.django.api.presenters.PresenterField``
        for a project's generated/hand-written presenter."""
        from stapel_core.django.api.presenters import PresenterField

        py_type: Any = str
        if self.kind is ProfileFieldKind.BOOL:
            py_type = bool
        return PresenterField(type=py_type, source=self.name, help_text=self.doc)

    @property
    def enum_values(self) -> Optional[List[str]]:
        """Choice values, for ``kind in (ENUM,)`` — what the field-manifest
        endpoint reports as ``enum_values`` (None for every other kind)."""
        if self.kind is ProfileFieldKind.ENUM and self.enum is not None:
            return [v for v, _label in self.enum.choices]
        return None

    @property
    def attribute_kind(self) -> Optional[str]:
        """FIELD_KINDS-compatible kind name for a shop/classified attribute
        projection built from this field (``stapel_attributes.profile_bridge``,
        governing spec §4). ``None`` when ``stapel-attributes`` isn't
        installed, or this field kind has no attribute-projectable shape
        (e.g. ``geohash`` — proximity, not a discrete filter).
        """
        try:
            from stapel_attributes.profile_bridge import PROFILE_KIND_TO_FIELD_KIND
        except ImportError:
            return None
        return PROFILE_KIND_TO_FIELD_KIND.get(self.kind.value)


#: Built-in standard fields — a project's manifest picks a subset by name.
STANDARD_FIELDS: Dict[str, ProfileFieldDef] = {
    # `theme` moved back to the hard core (models.ProfileCore, owner directive
    # 2026-07-22) — every product wants a light/dark toggle; no longer a
    # registry opt-in. currency/measurement stay here (genuinely opt-in).
    "currency_code": ProfileFieldDef(
        name="currency_code", kind=ProfileFieldKind.MODEL_REF,
        model_ref="stapel_currencies.Currency",
        doc=(
            "Preferred display currency — references the live stapel-currencies "
            "catalog (rates/list are DB-backed, not a fixed enum; see "
            "stapel_currencies.models.Currency) by its ISO code, not a real FK."
        ),
        default="USD",
    ),
    "measurement_units": ProfileFieldDef(
        name="measurement_units", kind=ProfileFieldKind.ENUM, enum=MeasurementUnit,
        doc="Preferred measurement system — only meaningful alongside convertible attributes.",
        default=MeasurementUnit.METRIC,
    ),
    "geohash": ProfileFieldDef(
        name="geohash", kind=ProfileFieldKind.GEOHASH,
        doc=(
            "Raw geohash of the user's last known point (stapel_geo.geohash.encode), "
            "for point-level proximity search — independent of location_id's "
            "city-level display cache."
        ),
        blank=True,
    ),
}

#: Identity is a MUTUALLY EXCLUSIVE preset (pick one, not a per-field toggle):
#: a project's manifest names ONE key, not a subset.
#:
#: `display_name` is NO LONGER a preset here — it is back in the hard core
#: (models.ProfileCore, owner directive 2026-07-22): every profile has a
#: `display_name` by default. `first_last_name` remains for a project that
#: wants SEPARATE first/last fields alongside (or instead of showing) the core
#: display_name.
IDENTITY_PRESETS: Dict[str, list] = {
    "first_last_name": [
        ProfileFieldDef(name="first_name", kind=ProfileFieldKind.TEXT,
                         doc="User's first name.", default="", params={"max_length": 35}),
        ProfileFieldDef(name="last_name", kind=ProfileFieldKind.TEXT,
                         doc="User's last name.", default="", params={"max_length": 35}),
    ],
}


def assemble_profile_fields(
    identity: Optional[str] = None,
    standard_fields: Iterable[str] = (),
    custom_fields: Sequence[ProfileFieldDef] = (),
) -> Dict[str, models.Field]:
    """Resolve a manifest selection into ``{field_name: Django model Field}``.

    Raises ``ValueError`` on an unknown identity preset / standard field name
    — fail loudly at assembly time (project boot), not with a confusing
    Django system-check error later.
    """
    fields: Dict[str, models.Field] = {}

    if identity is not None:
        if identity not in IDENTITY_PRESETS:
            raise ValueError(
                f"Unknown identity preset {identity!r}; choose one of "
                f"{sorted(IDENTITY_PRESETS)}"
            )
        for field_def in IDENTITY_PRESETS[identity]:
            fields[field_def.name] = field_def.to_model_field()

    for key in standard_fields:
        if key not in STANDARD_FIELDS:
            raise ValueError(
                f"Unknown standard field {key!r}; choose from {sorted(STANDARD_FIELDS)}"
            )
        fields[key] = STANDARD_FIELDS[key].to_model_field()

    for field_def in custom_fields:
        fields[field_def.name] = field_def.to_model_field()

    return fields


def build_profile_model(
    manifest: Dict[str, Any],
    *,
    app_label: str,
    model_name: str = "Profile",
    module: Optional[str] = None,
    base=None,
    verbose_name: str = "Profile",
    verbose_name_plural: str = "Profiles",
):
    """Assemble a concrete, swappable ``Profile`` subclass from a manifest.

    A project calls this once in its OWN app's ``models.py`` (so the
    resulting migration lives in the project app, not in ``stapel_profiles``
    — see docs/pending/profile-fields.md §3 for why)::

        # myproject/profile_ext/models.py
        from django.conf import settings
        from stapel_profiles.field_defs import build_profile_model

        Profile = build_profile_model(
            settings.STAPEL_PROFILES.get("FIELDS", {}), app_label="profile_ext",
        )

        # myproject/settings.py
        STAPEL_SWAP = {
            "PROFILES_PROFILE_MODEL": "myproject.profile_ext.models.Profile",
        }

    ``manifest`` is ``{"identity": Optional[str], "standard_fields":
    Sequence[str], "custom_fields": Sequence[ProfileFieldDef]}`` — every key
    optional (an empty manifest is equivalent to the shipped default
    ``stapel_profiles.models.Profile``, just materialized in the project's
    own app/migration state instead).
    """
    from stapel_profiles.models import ProfileCore

    base = base or ProfileCore
    extra_fields = assemble_profile_fields(
        identity=manifest.get("identity"),
        standard_fields=manifest.get("standard_fields", ()),
        custom_fields=manifest.get("custom_fields", ()),
    )

    attrs: Dict[str, Any] = dict(extra_fields)
    attrs["__module__"] = module or base.__module__
    attrs["__qualname__"] = model_name

    meta_attrs = {"app_label": app_label, "verbose_name": verbose_name, "verbose_name_plural": verbose_name_plural}
    attrs["Meta"] = type("Meta", (), meta_attrs)
    attrs["__str__"] = lambda self: f"{model_name}({self.user_id})"

    return type(model_name, (base,), attrs)


__all__ = [
    "ProfileFieldKind",
    "StapelProfileEnum",
    "Theme",
    "MeasurementUnit",
    "ProfileFieldDef",
    "STANDARD_FIELDS",
    "IDENTITY_PRESETS",
    "assemble_profile_fields",
    "build_profile_model",
]
