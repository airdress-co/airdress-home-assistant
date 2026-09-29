"""Test the owner's tracker, and what the recorder keeps of it."""

from homeassistant.components.airdress.const import CONF_RECORD_LOCATION
from homeassistant.components.device_tracker import ATTR_IN_ZONES
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_GPS_ACCURACY,
    ATTR_LATITUDE,
    ATTR_LONGITUDE,
    STATE_HOME,
    STATE_NOT_HOME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .conftest import MACHINE_ID, FakeChannel

from tests.common import MockConfigEntry

ENTITY = "device_tracker.home_test_a_airdr_es_jefe"
AWAY = (45.0, 5.0)
COORDINATES = (ATTR_LATITUDE, ATTR_LONGITUDE, ATTR_GPS_ACCURACY, ATTR_IN_ZONES)


async def _declare(hass: HomeAssistant, channel: FakeChannel, *trackers: str) -> None:
    await channel.feed(
        hass,
        channel.frames(
            "features",
            events=[],
            notify={"enabled": True},
            trackers=[{"name": t} for t in trackers],
        ),
    )


async def _track(
    hass: HomeAssistant,
    channel: FakeChannel,
    at: tuple[float, float],
    tracker: str = "jefe",
) -> None:
    await channel.feed(
        hass,
        channel.frames(
            "track",
            trackId="t1",
            tracker=tracker,
            lat=at[0],
            lon=at[1],
            accuracyM=12.5,
            function="location-to-home",
        ),
    )


def _home(hass: HomeAssistant) -> tuple[float, float]:
    zone = hass.states.get("zone.home")
    assert zone is not None
    return zone.attributes[ATTR_LATITUDE], zone.attributes[ATTR_LONGITUDE]


async def test_a_declared_tracker_moves_with_each_report(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    channel: FakeChannel,
    entity_registry: er.EntityRegistry,
) -> None:
    """A declared tracker is an entity; a function's report moves it."""
    await _declare(hass, channel, "jefe")
    state = hass.states.get(ENTITY)
    assert state is not None and state.state == STATE_UNKNOWN
    reg = entity_registry.async_get(ENTITY)
    assert reg is not None and reg.unique_id == f"{MACHINE_ID}-tracker-jefe"

    await _track(hass, channel, AWAY)
    state = hass.states.get(ENTITY)
    assert state is not None and state.state == STATE_NOT_HOME
    assert (state.attributes[ATTR_LATITUDE], state.attributes[ATTR_LONGITUDE]) == AWAY
    assert state.attributes[ATTR_GPS_ACCURACY] == 12.5

    await _track(hass, channel, _home(hass))
    state = hass.states.get(ENTITY)
    assert state is not None and state.state == STATE_HOME


async def test_undeclared_trackers_are_dropped_and_withdrawn_ones_removed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    channel: FakeChannel,
    entity_registry: er.EntityRegistry,
) -> None:
    """A report for a tracker the Home did not declare moves nothing."""
    await _declare(hass, channel, "jefe")
    await _track(hass, channel, AWAY, tracker="someone")
    state = hass.states.get(ENTITY)
    assert state is not None and state.state == STATE_UNKNOWN

    await _declare(hass, channel)
    assert entity_registry.async_get(ENTITY) is None


async def test_a_tracker_is_restored_before_the_channel_is_up(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    channel: FakeChannel,
) -> None:
    """After a reload the tracker exists, unavailable until the channel is up."""
    await _declare(hass, channel, "jefe")
    channel.open_error = None
    await hass.config_entries.async_reload(init_integration.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state is not None and state.state == STATE_UNAVAILABLE
    await channel.connect(hass)
    state = hass.states.get(ENTITY)
    assert state is not None and state.state == STATE_UNKNOWN


def _unrecorded(hass: HomeAssistant) -> frozenset[str]:
    """What the recorder leaves out of this state.

    Its ``state_info`` is exactly what the recorder reads
    (``StateAttributes.shared_data_bytes_from_event``).
    """
    state = hass.states.get(ENTITY)
    assert state is not None and state.state_info is not None
    return frozenset(state.state_info["unrecorded_attributes"])


async def test_by_default_the_recorder_keeps_no_coordinates(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    channel: FakeChannel,
) -> None:
    """The default: history holds home / away, never where exactly."""
    await _declare(hass, channel, "jefe")
    await _track(hass, channel, AWAY)
    state = hass.states.get(ENTITY)
    assert state is not None and state.attributes[ATTR_LATITUDE] == AWAY[0]
    assert _unrecorded(hass) >= frozenset(COORDINATES)


async def test_recording_is_chosen_and_then_keeps_coordinates(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    channel: FakeChannel,
) -> None:
    """With "record" (chosen with a confirmation) history holds coordinates."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={**mock_config_entry.options, CONF_RECORD_LOCATION: True},
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    await channel.connect(hass)
    await _declare(hass, channel, "jefe")
    await _track(hass, channel, AWAY)
    assert _unrecorded(hass).isdisjoint(COORDINATES)


async def test_the_tracker_is_never_shared_back(
    hass: HomeAssistant, init_integration: MockConfigEntry, channel: FakeChannel
) -> None:
    """Airdress's own tracker is never shared, streamed, read or operated."""
    await _declare(hass, channel, "jefe")
    await _track(hass, channel, AWAY)
    hass.config_entries.async_update_entry(
        init_integration,
        options={**init_integration.options, "observe": [ENTITY], "operate": [ENTITY]},
    )
    await hass.async_block_till_done()
    (shared,) = channel.sent_of("shared")[-1:]
    assert shared["operate"] == [] and shared["observe"] == []
    await channel.feed(
        hass,
        channel.frames(
            "features",
            events=[],
            notify={"enabled": True},
            trackers=[{"name": "jefe"}],
            observe=[ENTITY],
            observeAttributes={ENTITY: ["latitude"]},
        ),
        channel.frames("read", readId="r1", entity=ENTITY),
    )
    await _track(hass, channel, _home(hass))
    assert channel.sent_of("state") == []
    (answer,) = channel.sent_of("read_result")
    assert answer["outcome"] == "not_exposed"
