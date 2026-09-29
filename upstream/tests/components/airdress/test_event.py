"""Test the events the operator's functions emit."""

from datetime import timedelta

from homeassistant.components.event import ATTR_EVENT_TYPE, ATTR_EVENT_TYPES
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import MACHINE_ID, FakeChannel

from tests.common import MockConfigEntry, async_fire_time_changed

ENTITY = "event.home_test_a_airdr_es_arrived"


async def _declare(hass: HomeAssistant, channel: FakeChannel, *events: dict) -> None:
    await channel.feed(
        hass, channel.frames("features", events=list(events), notify={"enabled": True})
    )


async def test_declared_events_become_entities_and_emits_trigger_them(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    channel: FakeChannel,
    entity_registry: er.EntityRegistry,
) -> None:
    """A declared event is an entity; a function's emit triggers it."""
    await _declare(
        hass,
        channel,
        {"name": "arrived", "types": ["home", "work"]},
        {"name": "Not A Name", "types": ["home"]},
    )
    state = hass.states.get(ENTITY)
    assert state is not None
    assert state.state == STATE_UNKNOWN
    assert state.attributes[ATTR_EVENT_TYPES] == ["home", "work"]
    reg = entity_registry.async_get(ENTITY)
    assert reg is not None and reg.unique_id == f"{MACHINE_ID}-event-arrived"

    await channel.feed(
        hass,
        channel.frames(
            "emit",
            emitId="e1",
            event="arrived",
            eventType="home",
            data={"who": "jefe"},
            function="wake-on-arrival",
        ),
    )
    state = hass.states.get(ENTITY)
    assert state is not None and state.state != STATE_UNKNOWN
    assert state.attributes[ATTR_EVENT_TYPE] == "home"
    assert state.attributes["who"] == "jefe"
    assert state.attributes["function"] == "wake-on-arrival"


async def test_undeclared_emits_are_dropped(
    hass: HomeAssistant, init_integration: MockConfigEntry, channel: FakeChannel
) -> None:
    """An emit of an unknown event or type changes nothing."""
    await _declare(hass, channel, {"name": "arrived", "types": ["home"]})
    await channel.feed(
        hass,
        channel.frames("emit", emitId="e1", event="left", eventType="home"),
        channel.frames("emit", emitId="e2", event="arrived", eventType="work"),
    )
    state = hass.states.get(ENTITY)
    assert state is not None and state.state == STATE_UNKNOWN


async def test_redeclared_and_withdrawn_events(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    channel: FakeChannel,
    entity_registry: er.EntityRegistry,
) -> None:
    """New types update the entity; an event no longer declared is removed."""
    await _declare(hass, channel, {"name": "arrived", "types": ["home"]})
    await _declare(hass, channel, {"name": "arrived", "types": ["home", "gym"]})
    state = hass.states.get(ENTITY)
    assert state is not None and state.attributes[ATTR_EVENT_TYPES] == ["home", "gym"]
    await _declare(hass, channel, {"name": "left", "types": ["home"]})
    assert entity_registry.async_get(ENTITY) is None
    assert hass.states.get("event.home_test_a_airdr_es_left") is not None


async def test_events_are_unavailable_while_disconnected_and_restored(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    channel: FakeChannel,
    entity_registry: er.EntityRegistry,
) -> None:
    """The entities follow the channel, and exist again after a reload."""
    await _declare(hass, channel, {"name": "arrived", "types": ["home"]})
    # Another entity of this entry, which is not one of its events.
    entity_registry.async_get_or_create(
        "event", "airdress", "not-an-event", config_entry=init_integration
    )
    channel.abort()
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state is not None and state.state == STATE_UNAVAILABLE

    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state is not None and state.state == STATE_UNAVAILABLE
    assert state.attributes[ATTR_EVENT_TYPES] == ["home"]
    await channel.connect(hass)
    state = hass.states.get(ENTITY)
    assert state is not None and state.state == STATE_UNKNOWN
