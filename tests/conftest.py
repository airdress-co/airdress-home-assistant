"""Harness for the generated tests.

The integration's tests are written for home-assistant/core, whose root
conftest provides `hass` and friends. Here that is
pytest-homeassistant-custom-component, which also needs custom integrations
switched on for every test, since the integration lives in custom_components/.
"""

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/airdress as the airdress integration."""
