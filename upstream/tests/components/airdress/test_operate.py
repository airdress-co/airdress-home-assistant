"""Test what Airdress runs and reads, and everything it refuses."""

import asyncio
from typing import Any

import probatio
import pytest

from homeassistant.components.airdress.const import (
    CONF_OBSERVE,
    CONF_OPERATE,
    CONF_SENSITIVE,
    CONF_USER_ID,
    DOMAIN,
    EVENT_OPERATE,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er

from .conftest import FakeChannel

from tests.common import MockConfigEntry, async_capture_events, async_mock_service


async def _share(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    operate: list[str],
    observe: list[str] | None = None,
    sensitive: list[str] | None = None,
) -> None:
    hass.config_entries.async_update_entry(
        entry,
        options={
            CONF_OPERATE: operate,
            CONF_OBSERVE: observe or [],
            CONF_SENSITIVE: sensitive or [],
        },
    )
    await hass.async_block_till_done()


async def _call(
    hass: HomeAssistant,
    channel: FakeChannel,
    action: str,
    targets: list[Any],
    data: Any = None,
    function: str = "wake-on-arrival",
) -> dict[str, Any]:
    call_id = f"c{channel.frames.seq}"
    await channel.feed(
        hass,
        channel.frames(
            "call",
            callId=call_id,
            action=action,
            targets=targets,
            data=data,
            function=function,
        ),
    )
    (result,) = [r for r in channel.sent_of("result") if r["callId"] == call_id]
    return result


async def test_a_shared_button_is_pressed_as_the_airdress_user(
    hass: HomeAssistant, init_integration: MockConfigEntry, channel: FakeChannel
) -> None:
    """The action runs with the system user's context, after a logbook event."""
    hass.states.async_set("button.office_pc", "unknown")
    presses = async_mock_service(hass, "button", "press")
    fired = async_capture_events(hass, EVENT_OPERATE)
    await _share(hass, init_integration, ["button.office_pc"])

    result = await _call(hass, channel, "button.press", ["button.office_pc"])
    assert result["outcome"] == "ok"
    (press,) = presses
    assert press.data == {"entity_id": ["button.office_pc"]}
    assert press.context.user_id == init_integration.data[CONF_USER_ID]
    (event,) = fired
    assert event.data == {
        "function": "wake-on-arrival",
        "action": "button.press",
        "entity_id": ["button.office_pc"],
    }
    assert event.context is press.context


async def test_action_data_is_passed_on(
    hass: HomeAssistant, init_integration: MockConfigEntry, channel: FakeChannel
) -> None:
    """Service data other than targets reaches the action."""
    hass.states.async_set("light.desk", "off")
    calls = async_mock_service(hass, "light", "turn_on")
    await _share(hass, init_integration, ["light.desk"])
    result = await _call(
        hass, channel, "light.turn_on", ["light.desk"], {"brightness": 9}
    )
    assert result["outcome"] == "ok"
    assert calls[0].data == {"brightness": 9, "entity_id": ["light.desk"]}


@pytest.mark.parametrize(
    ("action", "targets", "data", "outcome"),
    [
        ("button.press", ["button.kitchen"], None, "not_exposed"),
        ("button.press", ["button.office_pc", "button.kitchen"], None, "not_exposed"),
        ("button.press", ["button.gone"], None, "not_found"),
        ("switch.turn_on", ["button.office_pc"], None, "rejected"),
        ("button.press", ["office_pc"], None, "rejected"),
        ("button", ["button.office_pc"], None, "rejected"),
        ("Button.Press", ["button.office_pc"], None, "rejected"),
        ("button.press", ["button.office_pc"], {"entity_id": "lock.front"}, "rejected"),
        ("button.press", ["button.office_pc"], {"area_id": "home"}, "rejected"),
        ("button.missing", ["button.office_pc"], None, "rejected"),
        ("button.press", [], None, "rejected"),
        ("button.press", ["button.office_pc"], [1], "rejected"),
    ],
)
async def test_refused_calls_never_run(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    channel: FakeChannel,
    action: str,
    targets: list[str],
    data: Any,
    outcome: str,
) -> None:
    """Exposure, existence and shape are checked here, whatever the operator sent."""
    hass.states.async_set("button.office_pc", "unknown")
    hass.states.async_set("button.kitchen", "unknown")
    presses = async_mock_service(hass, "button", "press")
    fired = async_capture_events(hass, EVENT_OPERATE)
    await _share(hass, init_integration, ["button.office_pc", "button.gone"])
    result = await _call(hass, channel, action, targets, data)
    assert result["outcome"] == outcome
    assert presses == [] and fired == []


@pytest.mark.parametrize(
    ("entity", "attributes", "allowed", "outcome"),
    [
        ("lock.front", {}, [], "sensitive_refused"),
        ("lock.front", {}, ["lock.front"], "ok"),
        ("alarm_control_panel.house", {}, [], "sensitive_refused"),
        ("cover.garage", {"device_class": "garage"}, [], "sensitive_refused"),
        ("cover.front", {"device_class": "door"}, [], "sensitive_refused"),
        ("cover.drive", {"device_class": "gate"}, [], "sensitive_refused"),
        ("cover.skylight", {"device_class": "window"}, [], "sensitive_refused"),
        ("cover.unclassified", {}, [], "sensitive_refused"),
        ("cover.garage", {"device_class": "garage"}, ["cover.garage"], "ok"),
        ("cover.living_room", {"device_class": "blind"}, [], "ok"),
    ],
)
async def test_sensitive_entities_need_this_side_opt_in(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    channel: FakeChannel,
    entity: str,
    attributes: dict[str, str],
    allowed: list[str],
    outcome: str,
) -> None:
    """A lock, an alarm panel or an entry-point cover runs only if allowed here."""
    domain = entity.split(".", maxsplit=1)[0]
    service = {"lock": "unlock", "alarm_control_panel": "alarm_disarm"}.get(
        domain, "open_cover"
    )
    hass.states.async_set(entity, "closed", attributes)
    calls = async_mock_service(hass, domain, service)
    await _share(hass, init_integration, [entity], sensitive=allowed)
    result = await _call(hass, channel, f"{domain}.{service}", [entity])
    assert result["outcome"] == outcome
    assert len(calls) == (1 if outcome == "ok" else 0)


async def test_a_user_device_class_override_counts(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    channel: FakeChannel,
    entity_registry: er.EntityRegistry,
) -> None:
    """A cover the user reclassified as a garage door is sensitive."""
    reg = entity_registry.async_get_or_create("cover", "test", "blind-1")
    entity_registry.async_update_entity(reg.entity_id, device_class="garage")
    hass.states.async_set(reg.entity_id, "closed", {"device_class": "blind"})
    calls = async_mock_service(hass, "cover", "open_cover")
    await _share(hass, init_integration, [reg.entity_id])
    result = await _call(hass, channel, "cover.open_cover", [reg.entity_id])
    assert result["outcome"] == "sensitive_refused"
    assert calls == []
    shared = channel.sent_of("shared")[-1]
    assert shared["operate"] == [{"entity": reg.entity_id, "deviceClass": "garage"}]


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (
            ServiceValidationError(
                translation_domain=DOMAIN, translation_key="cannot_connect"
            ),
            "rejected",
        ),
        (probatio.Invalid("bad"), "rejected"),
        (
            HomeAssistantError(
                translation_domain=DOMAIN, translation_key="cannot_connect"
            ),
            "failed",
        ),
    ],
)
async def test_an_action_that_fails_is_reported(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    channel: FakeChannel,
    error: Exception,
    outcome: str,
) -> None:
    """The action's own failure is the call's outcome."""
    hass.states.async_set("button.office_pc", "unknown")

    async def press(call: ServiceCall) -> None:
        raise error

    hass.services.async_register("button", "press", press)
    await _share(hass, init_integration, ["button.office_pc"])
    result = await _call(hass, channel, "button.press", ["button.office_pc"])
    assert result["outcome"] == outcome


async def test_a_slow_action_times_out(
    hass: HomeAssistant, init_integration: MockConfigEntry, channel: FakeChannel
) -> None:
    """An action that does not finish in time is answered as failed."""
    hass.states.async_set("button.office_pc", "unknown")

    async def press(call: ServiceCall) -> None:
        await asyncio.sleep(60)

    hass.services.async_register("button", "press", press)
    await _share(hass, init_integration, ["button.office_pc"])
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("homeassistant.components.airdress.hub.CALL_TIMEOUT", 0.01)
        await channel.feed(
            hass,
            channel.frames(
                "call",
                callId="slow",
                action="button.press",
                targets=["button.office_pc"],
            ),
        )
        for _ in range(100):
            if channel.sent_of("result"):
                break
            await asyncio.sleep(0.01)
    (result,) = channel.sent_of("result")
    assert result["outcome"] == "failed"


async def test_reads_follow_the_observe_level(
    hass: HomeAssistant, init_integration: MockConfigEntry, channel: FakeChannel
) -> None:
    """Observed and operated entities can be read; nothing else."""
    hass.states.async_set("sensor.washer", "running")
    hass.states.async_set("button.office_pc", "unknown")
    hass.states.async_set("sensor.secret", "42")
    await _share(
        hass,
        init_integration,
        ["button.office_pc"],
        observe=["sensor.washer", "sensor.gone"],
    )
    for entity in ("sensor.washer", "button.office_pc", "sensor.secret", "sensor.gone"):
        await channel.feed(
            hass, channel.frames("read", readId=f"r-{entity}", entity=entity)
        )
    results = {r["readId"]: r for r in channel.sent_of("read_result")}
    assert results["r-sensor.washer"]["outcome"] == "ok"
    assert results["r-sensor.washer"]["state"] == "running"
    assert results["r-button.office_pc"]["outcome"] == "ok"
    assert results["r-sensor.secret"]["outcome"] == "not_exposed"
    assert results["r-sensor.secret"]["state"] is None
    assert results["r-sensor.gone"]["outcome"] == "not_found"
