"""Fixtures for the Airdress integration tests.

The channel is the only thing faked: a scripted transport under the library's
real session, fed frames signed by a test operator key, so every operator
frame is verified exactly as it would be against a live operator.
"""

import asyncio
from collections.abc import AsyncIterator, Generator
import json
from typing import Any
from unittest.mock import AsyncMock, patch

from airdress_home import ChannelClosed, Enrollment, MachineKey, Started
from airdress_home.channel import ChannelStats
from airdress_home.codes import b64url
from airdress_home.frames import signed_bytes
from airdress_home.rendezvous import LinkStarted
import pytest

from homeassistant.components.airdress.const import (
    CONF_KID,
    CONF_MACHINE_ID,
    CONF_MACHINE_KEY,
    CONF_OBSERVE,
    CONF_OPERATE,
    CONF_OPERATOR,
    CONF_OPERATOR_KEY,
    CONF_SENSITIVE,
    DOMAIN,
)
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry

OPERATOR_KEY = MachineKey(bytes([7]) * 32)
MACHINE_KEY = MachineKey(bytes([3]) * 32)
ORIGIN = "https://home-test.a.airdr.es"
MACHINE_ID = "5b0c7f33-2f4e-4c55-9d0b-1c2d3e4f5a6b"
SESSION = "0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e"


class Frames:
    """Operator frames, signed by the test operator key, with a running seq."""

    def __init__(self, key: MachineKey = OPERATOR_KEY) -> None:
        """Initialize."""
        self.key = key
        self.seq = 0

    def __call__(self, frame_type: str, **body: Any) -> dict[str, Any]:
        """One signed frame."""
        self.seq += 1
        inner = {"session": SESSION, "seq": self.seq, "notAfter": 4_000_000_000, **body}
        if frame_type == "hello":
            inner["protocol"] = 1
        text = json.dumps(inner)
        sig = b64url(self.key.sign(signed_bytes(frame_type, text)))
        return {"type": frame_type, "frame": text, "sig": sig}


class FakeChannel:
    """A transport that yields what the test puts on it."""

    name = "fake"

    def __init__(self) -> None:
        """Initialize."""
        self.stats = ChannelStats()
        self.sent: list[dict[str, Any]] = []
        self.open_error: BaseException | None = None
        self.opened = 0
        self.queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.frames = Frames()
        self.close_code: int | None = None

    async def open(self) -> None:
        """Open, or fail as told."""
        if self.open_error is not None:
            raise self.open_error
        self.opened += 1
        # A new connection carries none of the old one's lines.
        while not self.queue.empty():
            self.queue.get_nowait()

    async def lines(self) -> AsyncIterator[dict[str, Any]]:
        """What the test fed, until it ends the channel."""
        while (item := await self.queue.get()) is not None:
            yield item
        code = self.close_code
        raise ChannelClosed(f"closed_{code}" if code else "test_end", code)

    def bind(self, session: str) -> None:
        """Nothing to bind."""

    def acked(self, seq: int) -> None:
        """Nothing to acknowledge."""

    async def send(self, frame: dict[str, Any]) -> None:
        """Record a hub frame."""
        self.sent.append(frame)

    def abort(self) -> None:
        """End the channel."""
        self.queue.put_nowait(None)

    async def close(self) -> None:
        """End the channel."""
        self.queue.put_nowait(None)

    def sent_of(self, frame_type: str) -> list[dict[str, Any]]:
        """The hub frames of one type."""
        return [f for f in self.sent if f["type"] == frame_type]

    async def feed(self, hass: HomeAssistant, *lines: dict[str, Any]) -> None:
        """Put signed frames on the channel and wait until they are handled."""
        for line in lines:
            self.queue.put_nowait(line)
        for _ in range(100):
            await asyncio.sleep(0)
            if self.queue.empty():
                break
        await hass.async_block_till_done()
        for _ in range(10):
            await asyncio.sleep(0)
        await hass.async_block_till_done()

    async def connect(self, hass: HomeAssistant) -> None:
        """Say hello, as the operator does first."""
        await self.feed(hass, self.frames("hello", transport="ws", operatorKid="k-1"))


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """A linked airdress."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="home-test.a.airdr.es",
        unique_id=ORIGIN,
        data={
            CONF_OPERATOR: ORIGIN,
            CONF_MACHINE_ID: MACHINE_ID,
            CONF_KID: MACHINE_KEY.kid,
            CONF_OPERATOR_KEY: b64url(OPERATOR_KEY.public),
            CONF_MACHINE_KEY: MACHINE_KEY.seed_b64(),
        },
        options={CONF_OPERATE: [], CONF_OBSERVE: [], CONF_SENSITIVE: []},
    )


@pytest.fixture
def channel() -> Generator[FakeChannel]:
    """The channel the integration holds."""
    fake = FakeChannel()
    with patch("homeassistant.components.airdress.for_client", return_value=fake):
        yield fake


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, channel: FakeChannel
) -> MockConfigEntry:
    """A loaded entry whose channel is up."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    await channel.connect(hass)
    return mock_config_entry


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Setting up an entry does nothing."""
    with patch(
        "homeassistant.components.airdress.async_setup_entry", return_value=True
    ) as mock:
        yield mock


def started(
    *, complete: str | None = f"{ORIGIN}/machines/approve?code=ABCD-EFGH"
) -> Started:
    """What an operator answers to an enrollment."""
    return Started(
        device_code="device-code",
        user_code="ABCD-EFGH",
        expires_in=600,
        interval=5,
        fingerprint=MACHINE_KEY.fingerprint,
        verification_uri=f"{ORIGIN}/machines/approve",
        verification_uri_complete=complete,
        operator_key=b64url(OPERATOR_KEY.public),
        operator_kid="k-op",
        operator_proof="proof",
        confirmation_code="AAAA-BBBB-CCCC-DDDD-EEEE",
    )


ENROLLMENT = Enrollment(
    operator=ORIGIN,
    machine_id=MACHINE_ID,
    kid=MACHINE_KEY.kid,
    operator_key=b64url(OPERATOR_KEY.public),
)

LINK = LinkStarted(
    device_code="link-device",
    user_code="WXYZ-1234",
    verification_uri="https://airdress.co/link",
    verification_uri_complete="https://airdress.co/link?code=WXYZ-1234",
    interval=5,
    expires_in=600,
)


@pytest.fixture
def approval() -> asyncio.Event:
    """Set when the owner approves on the operator."""
    return asyncio.Event()


@pytest.fixture
def mock_enroll(approval: asyncio.Event) -> Generator[dict[str, AsyncMock]]:
    """The operator's enrollment, answering as told."""

    async def decided(*args: Any) -> Enrollment:
        await approval.wait()
        return ENROLLMENT

    with (
        patch(
            "homeassistant.components.airdress.config_flow.start_enrollment",
            return_value=started(),
        ) as start,
        patch(
            "homeassistant.components.airdress.config_flow.poll_until_decided",
            side_effect=decided,
        ) as poll,
        patch(
            "homeassistant.components.airdress.config_flow.MachineKey.generate",
            return_value=MACHINE_KEY,
        ),
    ):
        yield {"start": start, "poll": poll}


@pytest.fixture
def bound() -> asyncio.Event:
    """Set when the owner binds an airdress at the hub."""
    return asyncio.Event()


@pytest.fixture
def mock_hub(bound: asyncio.Event) -> Generator[dict[str, AsyncMock]]:
    """The hub's rendezvous, answering as told."""

    async def poll(*args: Any, **kwargs: Any) -> str:
        await bound.wait()
        return ORIGIN

    base = "homeassistant.components.airdress.config_flow.rendezvous"
    with (
        patch(f"{base}.start", return_value=LINK) as start,
        patch(f"{base}.poll", side_effect=poll) as poll_mock,
        patch(f"{base}.enrolled", return_value=None) as enrolled,
    ):
        yield {"start": start, "poll": poll_mock, "enrolled": enrolled}
