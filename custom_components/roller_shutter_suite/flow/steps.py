"""The steps every level shares, generated from the catalog of the features.

Progressive configuration (F4): the step ``features`` asks for the feature
switches, then only the steps of the features that are effectively switched on
follow, each with its expert values in a collapsed section. A feature can have
several pages. A feature without a switch in the registry is always on, and
without any switch the step ``features`` is skipped.

Home Assistant finds a step by the name of a method (``async_step_<id>``).
:func:`install_feature_steps` attaches one such method per page of every
feature to a flow class, so a feature block adds its package and one line in
``features/__init__.py`` and edits no flow class. The methods look their page
up in the catalog when they run, so the fields of a step follow the catalog.

Nothing is saved before the last step: the flow collects the own values in
its context and saves once, which keeps a reconfigure at one reload.
"""

from abc import abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, cast

from homeassistant.data_entry_flow import FlowHandler

from custom_components.roller_shutter_suite.features import FEATURES, get_catalog

from .inheritance import (
    build_placeholders,
    build_schema,
    inherited_settings,
    read_step_input,
    resolve_level,
    visible_fields,
)
from .model import Catalog, FieldForm, LevelContext, StepForm

STEP_FEATURES = "features"


def _switches(catalog: Catalog) -> tuple[FieldForm, ...]:
    """Return the feature switches as fields: inheritable booleans like any other."""
    return tuple(
        FieldForm(key=feature.switch)
        for feature in catalog.features
        if feature.switch is not None
    )


class FeatureStepsMixin:
    """Feature switches and feature steps for a config flow or a subentry flow."""

    _context: LevelContext
    _pending: list[str]

    @abstractmethod
    async def _async_finish(self) -> Any:
        """Save ``self._context.own`` and end the flow."""

    async def _async_start_feature_steps(self, context: LevelContext) -> Any:
        """Begin the generated steps for the level the flow edits."""
        self._context = context
        self._pending = []
        if _switches(get_catalog()):
            return await self.async_step_features()
        return await self._async_after_switches()

    async def _async_generated_step(
        self,
        step_id: str,
        fields: tuple[FieldForm, ...],
        user_input: dict[str, Any] | None,
    ) -> Any | None:
        """Show a generated step or take its input; ``None`` when the step is done."""
        catalog = get_catalog()
        context = self._context
        inherited = inherited_settings(catalog, context)
        errors: dict[str, str] = {}
        placeholders = build_placeholders(catalog, fields, context, inherited)
        if user_input is not None:
            result = read_step_input(catalog, fields, context, inherited, user_input)
            if not result.errors:
                context.own = result.own
                return None
            errors = result.errors
            placeholders |= result.placeholders
        # The mixin is always combined with one of Home Assistant's flow handlers.
        flow = cast("FlowHandler[Any, Any, Any]", self)
        return flow.async_show_form(
            step_id=step_id,
            data_schema=build_schema(catalog, fields, context, inherited),
            description_placeholders=placeholders,
            errors=errors,
        )

    async def async_step_features(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        """Ask which features this level switches on, off, or inherits."""
        form = await self._async_generated_step(
            STEP_FEATURES, _switches(get_catalog()), user_input
        )
        if form is not None:
            return form
        return await self._async_after_switches()

    async def _async_after_switches(self) -> Any:
        """Queue the steps of the features that are effectively switched on."""
        catalog = get_catalog()
        context = self._context
        effective = resolve_level(catalog, context, context.own)
        self._pending = [
            feature.step_id(step)
            for feature in catalog.features
            if feature.switch is None or effective.values[feature.switch].effective
            for step in feature.steps
            if visible_fields(catalog, step.fields, context)
        ]
        return await self._async_next_feature()

    async def _async_next_feature(self) -> Any:
        if not self._pending:
            return await self._async_finish()
        step: Callable[[], Awaitable[Any]] = getattr(
            self, f"async_step_{self._pending[0]}"
        )
        return await step()

    async def _async_feature_step(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> Any:
        step = cast("StepForm", get_catalog().step(step_id))
        form = await self._async_generated_step(step_id, step.fields, user_input)
        if form is not None:
            return form
        self._pending = [item for item in self._pending if item != step_id]
        return await self._async_next_feature()


def install_feature_steps[FlowT: type[FeatureStepsMixin]](flow_class: FlowT) -> FlowT:
    """Attach one step method per page of every registered feature to a flow class."""

    def make_step(step_id: str) -> Callable[..., Awaitable[Any]]:
        async def step(
            self: FeatureStepsMixin, user_input: dict[str, Any] | None = None
        ) -> Any:
            return await self._async_feature_step(step_id, user_input)

        step.__name__ = f"async_step_{step_id}"
        return step

    for feature in FEATURES:
        for page in feature.steps:
            step_id = feature.step_id(page)
            setattr(flow_class, f"async_step_{step_id}", make_step(step_id))
    return flow_class
