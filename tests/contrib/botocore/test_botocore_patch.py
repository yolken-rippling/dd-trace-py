# This test script was automatically generated by the contrib-patch-tests.py
# script. If you want to make changes to it, you should make sure that you have
# removed the ``_generated`` suffix from the file name, to prevent the content
# from being overwritten by future re-generations.
import pytest

from ddtrace.contrib.botocore import get_version
from ddtrace.contrib.botocore.patch import patch
from tests.utils import override_global_config


try:
    from ddtrace.contrib.botocore.patch import unpatch
except ImportError:
    unpatch = None
from tests.contrib.patch import PatchTestCase


@pytest.mark.parametrize(
    "ddtrace_global_config",
    [dict(_llmobs_enabled=True, _llmobs_ml_app=None)],
)
def test_patch_when_llmobs_errors(ddtrace_global_config):
    with override_global_config(ddtrace_global_config):
        try:
            patch()
            unpatch()
        except ValueError:
            assert False, "patch() should not error if LLMObs.enable() raises an exception"


class TestBotocorePatch(PatchTestCase.Base):
    __integration_name__ = "botocore"
    __module_name__ = "botocore.client"
    __patch_func__ = patch
    __unpatch_func__ = unpatch
    __get_version__ = get_version

    def assert_module_patched(self, botocore_client):
        pass

    def assert_not_module_patched(self, botocore_client):
        pass

    def assert_not_module_double_patched(self, botocore_client):
        pass
