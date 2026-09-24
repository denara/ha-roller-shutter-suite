"""Only the actuator adapter moves a cover (G1).

The test reads every module of the integration and fails on anything outside
``actuator.py`` that can move a cover: a service call through the service
registry, a cover action by its name or its constant, a helper that runs an
action from a configuration, or a movement method of a cover entity. It is
shown to find what it looks for, in the adapter and in a planted example.
"""

import ast
from pathlib import Path

import pytest

INTEGRATION = Path(__file__).parents[2] / "custom_components" / "roller_shutter_suite"
ADAPTER = INTEGRATION / "actuator.py"
MODULES_AT_LEAST = 40

_COVER_ACTIONS = frozenset(
    {
        "open_cover",
        "close_cover",
        "set_cover_position",
        "stop_cover",
        "open_cover_tilt",
        "close_cover_tilt",
        "set_cover_tilt_position",
        "stop_cover_tilt",
        "toggle_cover_tilt",
    }
)
_RUNNERS = frozenset(
    {"async_call_from_config", "async_call_action_from_config", "async_run"}
)
_SERVICE_CALLS = frozenset({"async_call", "call"})


def _is_cover_constant(name: str) -> bool:
    return name.startswith("SERVICE_") and "COVER" in name


def _is_entity_movement(name: str) -> bool:
    bare = name.removeprefix("async_").removeprefix("handle_")
    return bare in _COVER_ACTIONS or bare == "toggle"


def findings(source: str) -> list[str]:
    """Return what in the source could move a cover, with the line."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Attribute):
            if (
                node.attr in _SERVICE_CALLS
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "services"
            ):
                found.append(f"line {line}: services.{node.attr}")
            if node.attr in _RUNNERS or _is_cover_constant(node.attr):
                found.append(f"line {line}: {node.attr}")
            if _is_entity_movement(node.attr):
                found.append(f"line {line}: {node.attr}")
        elif isinstance(node, ast.Name) and (
            node.id in _RUNNERS or _is_cover_constant(node.id)
        ):
            found.append(f"line {line}: {node.id}")
        elif isinstance(node, ast.alias) and (
            node.name in _RUNNERS or _is_cover_constant(node.name)
        ):
            found.append(f"line {line}: import of {node.name}")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in _COVER_ACTIONS
        ):
            found.append(f"line {line}: {node.value!r}")
    return found


def _modules() -> list[Path]:
    return sorted(INTEGRATION.rglob("*.py"))


def test_no_module_but_the_adapter_can_move_a_cover() -> None:
    """Every other module of the integration is free of cover actions."""
    modules = [path for path in _modules() if path != ADAPTER]
    assert len(modules) > MODULES_AT_LEAST  # the scan really looked

    offending = {
        path.relative_to(INTEGRATION).as_posix(): found
        for path in modules
        if (found := findings(path.read_text(encoding="utf-8")))
    }

    assert offending == {}


def test_the_scan_finds_the_calls_of_the_adapter() -> None:
    """Not vacuous: the one place that moves covers is found."""
    found = " ".join(findings(ADAPTER.read_text(encoding="utf-8")))

    assert "services.async_call" in found
    assert "SERVICE_SET_COVER_POSITION" in found
    assert "SERVICE_OPEN_COVER" in found
    assert "SERVICE_CLOSE_COVER" in found


@pytest.mark.parametrize(
    "planted",
    [
        'await hass.services.async_call("cover", "open_cover", {})',
        "hass.services.call(domain, service)",
        "from homeassistant.const import SERVICE_STOP_COVER",
        "service = const.SERVICE_SET_COVER_TILT_POSITION",
        "await script.async_run(variables)",
        "await entity.async_set_cover_position(position=3)",
        "await entity.async_handle_close_cover()",
        'SERVICE = "set_cover_position"',
    ],
)
def test_the_scan_finds_a_planted_movement(planted: str) -> None:
    """Each way to move a cover is recognized."""
    assert findings(f"async def example():\n    {planted}\n")
