"""SPIKE S2: configuration step of shading (dummy settings)."""

from custom_components.roller_shutter_suite.flow.model import FeatureFlow, SettingField

FEATURE = FeatureFlow(
    feature_id="shading",
    enabled_by_default=False,
    fields=(
        # A shading position needs a cover that can be sent to a position.
        SettingField(
            "shading_position",
            "number",
            default=30,
            unit="%",
            requires="set_position",
        ),
        SettingField("use_forecast", "bool", default=False),
    ),
)
