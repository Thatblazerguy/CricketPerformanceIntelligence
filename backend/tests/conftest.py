"""Global pytest configuration and markers."""
import pytest


def pytest_collection_modifyitems(items):
    """Automatically tag tests in tests/integration with the integration marker."""
    for item in items:
        if "tests/integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
