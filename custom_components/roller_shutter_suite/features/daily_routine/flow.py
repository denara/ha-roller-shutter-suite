"""SPIKE S2: configuration step of the daily routine (dummy settings)."""

from custom_components.roller_shutter_suite.flow.model import (
    FeatureFlow,
    SettingField,
    Settings,
)


def _validate(values: Settings) -> dict[str, str]:
    """Show that a feature can validate across its fields."""
    if values["evening_position"] > values["morning_position"]:
        return {"evening_position": "evening_above_morning"}
    return {}


FEATURE = FeatureFlow(
    feature_id="daily_routine",
    enabled_by_default=True,
    fields=(
        SettingField("open_in_morning", "bool", default=True),
        # Zero is a valid position: fully closed.
        SettingField("morning_position", "number", default=100, unit="%"),
        SettingField("evening_position", "number", default=0, unit="%"),
        SettingField(
            "random_offset", "number", default=0, maximum=30, unit="min", expert=True
        ),
    ),
    validate=_validate,
)
