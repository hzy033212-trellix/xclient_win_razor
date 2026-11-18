import pytest

from tests.test_xclient.provisioned_xclient import update_xclient_config


@pytest.fixture(scope="module")
def update_config_eventor_disabled():
    update_xclient_config("mxa/container/Eventor/enabled", "false")
    yield
    update_xclient_config("mxa/container/Eventor/enabled", "true")
