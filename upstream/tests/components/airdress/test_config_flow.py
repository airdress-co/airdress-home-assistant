"""Test the Airdress config flow."""

import asyncio
from unittest.mock import AsyncMock

import aiohttp
from airdress_home import (
    EnrollmentDenied,
    EnrollmentError,
    EnrollmentExpired,
    OperatorProofError,
)
import pytest

from homeassistant.components.airdress.const import (
    CONF_KID,
    CONF_MACHINE_ID,
    CONF_MACHINE_KEY,
    CONF_OBSERVE,
    CONF_OPERATE,
    CONF_OPERATOR,
    CONF_OPERATOR_KEY,
    CONF_PREAUTH_KEY,
    CONF_SENSITIVE,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import ATTR_DEVICE_CLASS, CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import ENROLLMENT, LINK, MACHINE_KEY, ORIGIN, started

from tests.common import MockConfigEntry

EXPECTED_DATA = {
    CONF_OPERATOR: ORIGIN,
    CONF_MACHINE_ID: ENROLLMENT.machine_id,
    CONF_KID: ENROLLMENT.kid,
    CONF_OPERATOR_KEY: ENROLLMENT.operator_key,
    CONF_MACHINE_KEY: MACHINE_KEY.seed_b64(),
}


async def _menu(hass: HomeAssistant, choice: str) -> str:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["link", "address", "preauth"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": choice}
    )
    return result["flow_id"]


async def _approve(hass: HomeAssistant, flow_id: str, approval: asyncio.Event) -> dict:
    approval.set()
    await hass.async_block_till_done()
    return await hass.config_entries.flow.async_configure(flow_id)


@pytest.mark.usefixtures("mock_setup_entry")
async def test_sign_in_with_airdress(
    hass: HomeAssistant,
    mock_hub: dict[str, AsyncMock],
    mock_enroll: dict[str, AsyncMock],
    bound: asyncio.Event,
    approval: asyncio.Event,
) -> None:
    """The hub introduces the operator; the owner approves there."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "link"}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["progress_action"] == "link"
    assert result["description_placeholders"] == {
        "url": LINK.verification_uri_complete,
        "code": LINK.user_code,
    }
    assert mock_hub["start"].call_args.kwargs == {"client_name": "Home Assistant"}

    bound.set()
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["step_id"] == "approve"
    assert result["description_placeholders"]["user_code"] == "ABCD-EFGH"
    assert (
        result["description_placeholders"]["confirmation_code"]
        == "AAAA-BBBB-CCCC-DDDD-EEEE"
    )
    args, kwargs = mock_enroll["start"].call_args
    assert args[1] == ORIGIN
    assert kwargs == {"preauth_key": None, "require_proof": True}
    assert mock_hub["enrolled"].call_args.args[2] == "ABCD-EFGH"

    result = await _approve(hass, result["flow_id"], approval)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "home-test.a.airdr.es"
    assert result["data"] == EXPECTED_DATA
    assert result["options"] == {CONF_OPERATE: [], CONF_OBSERVE: [], CONF_SENSITIVE: []}
    assert result["result"].unique_id == ORIGIN


@pytest.mark.usefixtures("mock_setup_entry", "mock_enroll")
async def test_sign_in_when_the_hub_is_not_told(
    hass: HomeAssistant,
    mock_hub: dict[str, AsyncMock],
    bound: asyncio.Event,
    approval: asyncio.Event,
) -> None:
    """The approve link still works when the hub is not told of the enrollment."""
    mock_hub["enrolled"].side_effect = EnrollmentError("not_bound")
    flow_id = await _menu(hass, "link")
    bound.set()
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(flow_id)
    assert result["step_id"] == "approve"
    result = await _approve(hass, flow_id, approval)
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    "error", [EnrollmentError("temporarily_unavailable"), aiohttp.ClientError()]
)
async def test_sign_in_hub_unreachable(
    hass: HomeAssistant, mock_hub: dict[str, AsyncMock], error: Exception
) -> None:
    """A hub that cannot start a link aborts, to be retried."""
    mock_hub["start"].side_effect = error
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "link"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect_hub"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (EnrollmentDenied("denied"), "link_denied"),
        (EnrollmentExpired("expired"), "link_expired"),
        (EnrollmentError("bad_origin"), "cannot_connect_hub"),
        (TimeoutError(), "cannot_connect_hub"),
    ],
)
async def test_sign_in_not_bound(
    hass: HomeAssistant,
    mock_hub: dict[str, AsyncMock],
    error: Exception,
    reason: str,
) -> None:
    """The owner declined at the hub, or the code expired."""
    mock_hub["poll"].side_effect = error
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "link"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


@pytest.mark.usefixtures("mock_hub")
async def test_sign_in_to_an_airdress_already_linked(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_enroll: dict[str, AsyncMock],
    bound: asyncio.Event,
) -> None:
    """A second link to the same airdress aborts before enrolling."""
    mock_config_entry.add_to_hass(hass)
    flow_id = await _menu(hass, "link")
    bound.set()
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(flow_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    mock_enroll["start"].assert_not_called()


@pytest.mark.usefixtures("mock_hub")
async def test_sign_in_operator_proof_fails(
    hass: HomeAssistant, mock_enroll: dict[str, AsyncMock], bound: asyncio.Event
) -> None:
    """An operator whose answer does not verify is not trusted."""
    mock_enroll["start"].side_effect = OperatorProofError("bad")
    flow_id = await _menu(hass, "link")
    bound.set()
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(flow_id)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "operator_proof"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_link_by_address(
    hass: HomeAssistant, mock_enroll: dict[str, AsyncMock], approval: asyncio.Event
) -> None:
    """A typed address, normalized to its origin, then approval."""
    mock_enroll["start"].return_value = started(complete=None)
    flow_id = await _menu(hass, "address")
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_ADDRESS: " Home-Test.a.airdr.es/ "}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["description_placeholders"]["url"] == f"{ORIGIN}/machines/approve"
    assert mock_enroll["start"].call_args.args[1] == ORIGIN
    result = await _approve(hass, flow_id, approval)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == EXPECTED_DATA


@pytest.mark.usefixtures("mock_enroll")
async def test_approve_url_when_the_operator_names_none(
    hass: HomeAssistant, mock_enroll: dict[str, AsyncMock]
) -> None:
    """An operator that names no approval page gets its standard one."""
    answer = started(complete=None)
    answer.verification_uri = None
    mock_enroll["start"].return_value = answer
    flow_id = await _menu(hass, "address")
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_ADDRESS: ORIGIN}
    )
    assert result["description_placeholders"]["url"] == f"{ORIGIN}/machines/approve"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (EnrollmentError("not_enabled"), "not_enabled"),
        (EnrollmentError("slow_down"), "busy"),
        (EnrollmentError("server_error"), "enroll_refused"),
        (OperatorProofError("no proof"), "operator_proof"),
        (aiohttp.ClientError(), "cannot_connect"),
        (TimeoutError(), "cannot_connect"),
    ],
)
@pytest.mark.usefixtures("mock_setup_entry")
async def test_link_by_address_errors_can_be_retried(
    hass: HomeAssistant,
    mock_enroll: dict[str, AsyncMock],
    approval: asyncio.Event,
    error: Exception,
    reason: str,
) -> None:
    """Each refusal is shown on the form, and the form can be sent again."""
    mock_enroll["start"].side_effect = error
    flow_id = await _menu(hass, "address")
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_ADDRESS: ORIGIN}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": reason}
    mock_enroll["start"].side_effect = None
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_ADDRESS: ORIGIN}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    result = await _approve(hass, flow_id, approval)
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    "address", ["http://home-test.a.airdr.es", "https://x.example/path", "https://"]
)
async def test_link_by_address_invalid(
    hass: HomeAssistant, mock_enroll: dict[str, AsyncMock], address: str
) -> None:
    """Only a bare https origin is an airdress's address."""
    flow_id = await _menu(hass, "address")
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_ADDRESS: address}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_ADDRESS: "invalid_address"}
    mock_enroll["start"].assert_not_called()


@pytest.mark.usefixtures("mock_enroll")
async def test_link_by_address_already_linked(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """One entry per airdress."""
    mock_config_entry.add_to_hass(hass)
    flow_id = await _menu(hass, "address")
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_ADDRESS: ORIGIN}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_link_with_a_preauth_key(
    hass: HomeAssistant, mock_enroll: dict[str, AsyncMock], approval: asyncio.Event
) -> None:
    """A refused key is shown on the form; a good one links."""
    mock_enroll["start"].side_effect = EnrollmentError("access_denied")
    flow_id = await _menu(hass, "preauth")
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_ADDRESS: ORIGIN, CONF_PREAUTH_KEY: "wrong"}
    )
    assert result["errors"] == {"base": "invalid_preauth_key"}
    mock_enroll["start"].side_effect = None
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_ADDRESS: ORIGIN, CONF_PREAUTH_KEY: "adk_good"}
    )
    assert mock_enroll["start"].call_args.kwargs["preauth_key"] == "adk_good"
    result = await _approve(hass, flow_id, approval)
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (EnrollmentDenied("access_denied"), "denied"),
        (EnrollmentExpired("expired_token"), "expired"),
        (EnrollmentError("invalid_grant"), "enroll_refused"),
        (aiohttp.ClientError(), "enroll_refused"),
    ],
)
async def test_approval_not_given(
    hass: HomeAssistant,
    mock_enroll: dict[str, AsyncMock],
    error: Exception,
    reason: str,
) -> None:
    """Denied, expired or failed approvals abort with their reason."""
    mock_enroll["poll"].side_effect = error
    flow_id = await _menu(hass, "address")
    result = await hass.config_entries.flow.async_configure(
        flow_id, {CONF_ADDRESS: ORIGIN}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


@pytest.mark.usefixtures("mock_enroll", "mock_hub")
async def test_abandoned_flows_stop_waiting(hass: HomeAssistant) -> None:
    """Closing the dialog cancels the waits on the hub and on the operator."""
    flow_id = await _menu(hass, "link")
    flow = hass.config_entries.flow._progress[flow_id]
    link_task = flow._link_task
    hass.config_entries.flow.async_abort(flow_id)
    await hass.async_block_till_done()
    assert link_task.cancelled()

    flow_id = await _menu(hass, "address")
    await hass.config_entries.flow.async_configure(flow_id, {CONF_ADDRESS: ORIGIN})
    flow = hass.config_entries.flow._progress[flow_id]
    approve_task = flow._approve_task
    hass.config_entries.flow.async_abort(flow_id)
    await hass.async_block_till_done()
    assert approve_task.cancelled()


async def test_options_levels_without_sensitive_entities(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Choosing entities with nothing sensitive among them is one step."""
    mock_config_entry.add_to_hass(hass)
    hass.states.async_set("button.office_pc", "unknown")
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_OPERATE: ["button.office_pc"], CONF_OBSERVE: ["sensor.washer"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_OPERATE: ["button.office_pc"],
        CONF_OBSERVE: ["sensor.washer"],
        CONF_SENSITIVE: [],
    }


async def test_options_sensitive_entities_need_their_own_opt_in(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Locks and entry-point covers are offered for opt-in, none by default."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={
            **mock_config_entry.options,
            CONF_SENSITIVE: ["lock.front", "lock.old"],
        },
    )
    hass.states.async_set("lock.front", "locked")
    hass.states.async_set("cover.garage", "closed", {ATTR_DEVICE_CLASS: "garage"})
    hass.states.async_set("cover.blind", "open", {ATTR_DEVICE_CLASS: "blind"})
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_OPERATE: ["lock.front", "cover.garage", "cover.blind"]},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "sensitive"
    assert result["description_placeholders"] == {"count": "2"}
    schema = result["data_schema"].schema
    (key,) = schema
    assert key.description == {"suggested_value": ["lock.front"]}
    assert schema[key].config["include_entities"] == ["lock.front", "cover.garage"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SENSITIVE: ["cover.garage"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options == {
        CONF_OPERATE: ["lock.front", "cover.garage", "cover.blind"],
        CONF_OBSERVE: [],
        CONF_SENSITIVE: ["cover.garage"],
    }
