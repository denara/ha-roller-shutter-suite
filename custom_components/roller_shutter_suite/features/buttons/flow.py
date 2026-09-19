"""SPIKE S2: configuration step of wall buttons (dummy settings)."""

from custom_components.roller_shutter_suite.flow.model import FeatureFlow, SettingField

FEATURE = FeatureFlow(
    feature_id="buttons",
    enabled_by_default=False,
    fields=(
        # Hold-to-move stops on release, so the cover has to support stop.
        SettingField("hold_to_move", "bool", default=True, requires="stop"),
        SettingField("double_press_position", "number", default=50, unit="%"),
    ),
)
