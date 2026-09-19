"""SPIKE S2: the steps every level shares, generated from the feature registry.

Progressive configuration: the step ``features`` asks for the feature switches,
then only the steps of features that are effectively enabled follow. The step
methods ``async_step_feature_<id>`` are attached to the flow classes by
``install_feature_steps``; Home Assistant finds a step by the name of its method.
"""

from abc import abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, cast

from homeassistant.data_entry_flow import FlowHandler

from custom_components.roller_shutter_suite.features import FEATURES

from .inheritance import build_placeholders, build_schema, parse_input
from .model import FeatureFlow, LevelContext, SettingField, SettingValue, resolve

STEP_FEATURES = "features"


class FeatureStepsMixin:
    """Feature switches and feature steps for a config flow or subentry flow."""

    _level: LevelContext
    _pending: list[FeatureFlow]

    @abstractmethod
    async def _async_finish(self) -> Any:
        """Save ``self._level.own`` and end the flow."""

    def _start_feature_steps(self, context: LevelContext) -> None:
        self._level = context
        self._pending = []

    async def _async_generated_step(
        self,
        step_id: str,
        fields: tuple[SettingField, ...],
        validate: Callable[[dict[str, SettingValue]], dict[str, str]] | None,
        user_input: dict[str, Any] | None,
    ) -> dict[str, str] | None:
        """Handle input of a generated step; return errors, or None when done."""
        if user_input is None:
            return {}
        context = self._level
        own = parse_input(fields, context, user_input)
        if validate is not None:
            effective = {
                setting.key: resolve(setting, own, context.parents)
                for setting in fields
            }
            if errors := validate(effective):
                return errors
        for setting in fields:
            context.own.pop(setting.key, None)
        context.own.update(own)
        return None

    def _show_generated_step(
        self, step_id: str, fields: tuple[SettingField, ...], errors: dict[str, str]
    ) -> Any:
        # The mixin is always combined with one of Home Assistant's flow handlers.
        flow = cast("FlowHandler[Any, Any, Any]", self)
        return flow.async_show_form(
            step_id=step_id,
            data_schema=build_schema(fields, self._level),
            description_placeholders=build_placeholders(fields, self._level),
            errors=errors,
        )

    async def async_step_features(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Ask which features this level switches on, off, or inherits."""
        switches = tuple(feature.switch for feature in FEATURES)
        errors = await self._async_generated_step(
            STEP_FEATURES, switches, None, user_input
        )
        if errors is not None:
            return self._show_generated_step(STEP_FEATURES, switches, errors)

        context = self._level
        self._pending = [
            feature
            for feature in FEATURES
            if resolve(feature.switch, context.own, context.parents)
        ]
        return await self._async_next_feature()

    async def _async_next_feature(self) -> Any:
        if not self._pending:
            return await self._async_finish()
        step: Callable[[], Awaitable[Any]] = getattr(
            self, f"async_step_{self._pending[0].step_id}"
        )
        return await step()

    async def _async_feature_step(
        self, feature: FeatureFlow, user_input: dict[str, Any] | None
    ) -> Any:
        errors = await self._async_generated_step(
            feature.step_id, feature.fields, feature.validate, user_input
        )
        if errors is not None:
            return self._show_generated_step(feature.step_id, feature.fields, errors)
        self._pending = [item for item in self._pending if item is not feature]
        return await self._async_next_feature()


def install_feature_steps[FlowT: type[FeatureStepsMixin]](flow_class: FlowT) -> FlowT:
    """Attach one step method per registered feature to a flow class."""

    def make_step(feature: FeatureFlow) -> Callable[..., Awaitable[Any]]:
        async def step(
            self: FeatureStepsMixin, user_input: dict[str, Any] | None = None
        ) -> Any:
            return await self._async_feature_step(feature, user_input)

        step.__name__ = f"async_step_{feature.step_id}"
        return step

    for feature in FEATURES:
        setattr(flow_class, f"async_step_{feature.step_id}", make_step(feature))
    return flow_class
