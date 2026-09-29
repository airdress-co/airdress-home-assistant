"""Test setting up and removing Airdress."""

import asyncio
from collections.abc import Generator
import logging
from typing import Any
from unittest.mock import patch

import aiohttp
from airdress_home import ChannelClosed, HomeDisabled, HomeNotLinked, NotAuthorized
from airdress_home.channel import Hint
import pytest

from homeassistant.components.airdress import TransportHints
from homeassistant.components.airdress.const import (
    CONF_OBSERVE,
    CONF_OPERATE,
    CONF_OPERATOR_KEY,
    CONF_RECORD_LOCATION,
    CONF_SENSITIVE,
    CONF_USER_ID,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .conftest import FakeChannel

from tests.common import MockConfigEntry


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry, channel: FakeChannel
) -> None:
    """Setup opens the channel, answers hello with what is shared, and unloads."""
    entry = init_integration
    assert entry.state is ConfigEntryState.LOADED
    assert channel.opened == 1, "setup tests the connection, and run keeps it"
    (shared,) = channel.sent_of("shared")
    assert shared["operate"] == [] and shared["observe"] == []
    assert entry.runtime_data.session.connected

    user = await hass.auth.async_get_user(entry.data[CONF_USER_ID])
    assert user is not None
    assert user.system_generated and not user.is_admin and user.local_only
    assert user.name == "Airdress"

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_the_system_user_is_created_once(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A reload keeps the same system user; removing the entry removes it."""
    entry = init_integration
    user_id = entry.data[CONF_USER_ID]
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.data[CONF_USER_ID] == user_id

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.auth.async_get_user(user_id) is None


@pytest.mark.parametrize(
    ("error", "state"),
    [
        (HomeNotLinked("home_not_linked"), ConfigEntryState.SETUP_RETRY),
        (ChannelClosed("handshake_502"), ConfigEntryState.SETUP_RETRY),
        (aiohttp.ClientConnectionError(), ConfigEntryState.SETUP_RETRY),
        (TimeoutError(), ConfigEntryState.SETUP_RETRY),
        (NotAuthorized("machine_revoked"), ConfigEntryState.SETUP_ERROR),
    ],
)
async def test_setup_tests_the_connection(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    channel: FakeChannel,
    error: Exception,
    state: ConfigEntryState,
) -> None:
    """A channel that cannot open fails setup, retried unless revoked."""
    channel.open_error = error
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is state


async def test_setup_without_a_pinned_key(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, channel: FakeChannel
) -> None:
    """An entry with no pinned operator key never opens a channel."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_OPERATOR_KEY: ""}
    )
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    assert channel.opened == 0


async def test_changed_options_are_shared_without_a_reload(
    hass: HomeAssistant, init_integration: MockConfigEntry, channel: FakeChannel
) -> None:
    """A new choice of entities reaches the operator on the open channel."""
    hass.states.async_set("button.office_pc", "unknown")
    hass.states.async_set("cover.garage", "closed", {"device_class": "garage"})
    hass.config_entries.async_update_entry(
        init_integration,
        options={
            CONF_OPERATE: ["button.office_pc", "cover.garage"],
            CONF_OBSERVE: ["sensor.washer"],
            CONF_SENSITIVE: [],
        },
    )
    await hass.async_block_till_done()
    assert channel.opened == 1
    shared = channel.sent_of("shared")[-1]
    assert shared["operate"] == [
        {"entity": "button.office_pc"},
        {"entity": "cover.garage", "deviceClass": "garage"},
    ]
    assert [e["entity"] for e in shared["observe"]] == [
        "button.office_pc",
        "cover.garage",
        "sensor.washer",
    ]


async def test_a_disabled_home_is_retried(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, channel: FakeChannel
) -> None:
    """A Home switched off on the operator is retried, not an error."""
    channel.open_error = HomeDisabled("home_disabled")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY
    assert mock_config_entry.reason == (
        "The home this Home Assistant is linked as is switched off on your operator"
    )


async def test_a_revoke_reloads_the_entry_into_its_error(
    hass: HomeAssistant, init_integration: MockConfigEntry, channel: FakeChannel
) -> None:
    """Close code 4003 ends the channel for good; setup then reports the revoke."""
    channel.open_error = NotAuthorized("machine_revoked")
    channel.queue.put_nowait(None)
    channel.close_code = 4003
    await hass.async_block_till_done()
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.SETUP_ERROR
    assert channel.opened == 1
    (flow,) = hass.config_entries.flow.async_progress_by_handler("airdress")
    assert flow["context"]["source"] == "reauth"


@pytest.fixture
def no_backoff() -> Generator[None]:
    """The library dials again at once: an unlinked close backs off a minute."""
    with patch("airdress_home.session.random.uniform", return_value=0.0):
        yield


@pytest.mark.usefixtures("no_backoff")
@pytest.mark.parametrize("close_code", [4003, 4004])
async def test_a_401_on_redial_starts_reauth_as_revoked(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    channel: FakeChannel,
    close_code: int,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A redial refused 401 ends the channel for good and reauthenticates.

    The phone's Disconnect ended the channel 4004 and every redial was then
    refused 401: the library took each for one more drop and retried forever.
    """
    channel.open_error = NotAuthorized("invalid_signature")
    channel.queue.put_nowait(None)
    channel.close_code = close_code
    for _ in range(50):
        await asyncio.sleep(0.01)
        await hass.async_block_till_done()
        if hass.config_entries.flow.async_progress_by_handler("airdress"):
            break
    assert "revoked this Home Assistant" in caplog.text
    assert init_integration.state is ConfigEntryState.SETUP_ERROR
    (flow,) = hass.config_entries.flow.async_progress_by_handler("airdress")
    assert flow["context"]["source"] == "reauth"
    assert flow["context"]["entry_id"] == init_integration.entry_id


async def test_a_lapsed_approval_reloads_into_a_renewal(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    channel: FakeChannel,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 4003 whose redial says lapsed is reported as a lapse, not a revoke."""
    channel.open_error = NotAuthorized("machine_authorization_expired")
    channel.queue.put_nowait(None)
    channel.close_code = 4003
    for _ in range(3):
        await hass.async_block_till_done()
    assert "approval of this Home Assistant has lapsed" in caplog.text
    assert "revoked this Home Assistant" not in caplog.text
    assert init_integration.state is ConfigEntryState.SETUP_ERROR
    (flow,) = hass.config_entries.flow.async_progress_by_handler("airdress")
    assert flow["context"]["source"] == "reauth"


async def test_positions_for_no_declared_tracker_are_dropped(
    hass: HomeAssistant, init_integration: MockConfigEntry, channel: FakeChannel
) -> None:
    """With no tracker declared, a track changes nothing and is not answered."""
    before = list(channel.sent)
    states = hass.states.async_all()
    await channel.feed(
        hass,
        channel.frames(
            "track",
            trackId="t1",
            tracker="jefe",
            lat=52.5,
            lon=13.4,
            accuracyM=12.0,
            function="location-to-home",
        ),
    )
    assert channel.sent == before
    assert hass.states.async_all() == states


async def test_the_transport_hint_is_kept_in_storage(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    channel: FakeChannel,
    hass_storage: dict[str, Any],
) -> None:
    """The channel remembers per network what worked, in the entry's store."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "homeassistant.components.airdress.for_client", return_value=channel
    ) as for_client:
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    hints = for_client.call_args.kwargs["hints"]
    assert isinstance(hints, TransportHints)
    assert await hints.load() == {}
    await hints.save({"a1b2": Hint("poll", 1000.0, 999.0)})
    key = f"airdress.{mock_config_entry.entry_id}.transport"
    assert hass_storage[key]["data"] == {
        "a1b2": {"transport": "poll", "since": 1000.0, "preferredFailed": 999.0}
    }
    hass_storage[key]["data"]["broken"] = {"transport": 1}
    assert await TransportHints(hass, mock_config_entry.entry_id).load() == {
        "a1b2": Hint("poll", 1000.0, 999.0)
    }

    await hass.config_entries.async_remove(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert key not in hass_storage


async def test_transport_changes_are_logged(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    channel: FakeChannel,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A fallback says which transport the channel moved to, and why."""
    mock_config_entry.add_to_hass(hass)
    with patch(
        "homeassistant.components.airdress.for_client", return_value=channel
    ) as for_client:
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    on_event = for_client.call_args.kwargs["on_event"]
    with caplog.at_level(logging.INFO):
        on_event(
            {
                "t": 1.0,
                "kind": "transport_fallback",
                "transport": "poll",
                "refused": ["ws"],
            }
        )
    assert "transport_fallback" in caplog.text
    assert "'transport': 'poll'" in caplog.text


async def test_the_recording_option_reloads_the_entry(
    hass: HomeAssistant, init_integration: MockConfigEntry, channel: FakeChannel
) -> None:
    """The tracker's recorded attributes are per class, so a change reloads."""
    assert init_integration.runtime_data.record_location is False
    opened = channel.opened
    hass.config_entries.async_update_entry(
        init_integration,
        options={**init_integration.options, CONF_RECORD_LOCATION: True},
    )
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.LOADED
    assert init_integration.runtime_data.record_location is True
    assert channel.opened == opened + 1
