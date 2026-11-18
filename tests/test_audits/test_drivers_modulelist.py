import logging

import pytest
from tests.util.compatibility import WINDOWS, OS_COMPAT, compatibility_test

from tests.util.compatibility import is_memory_audit_compatible
from tests.util.schema_utils import return_section_schema_checks
from tests.util.string_formatting_utils import pprint_base_formatter
from tests.util.type_utils import is_numeric_type, is_string_type, is_filepath_type
from tests.test_xclient.provisioned_xclient import Singleton_XClient

xclient = Singleton_XClient()

logger = logging.getLogger("tests")


pytestmark = pytest.mark.audit


@pytest.fixture(scope="module")
#def run_driver_module_audit(provisioned_agent, emplace_audits_dll):
def run_driver_module_audit():
    data = xclient.run_job(
        "drivers-modulelist",
        notes="drivers-modulelist driver no params task",
        audit_script_name="test_audit_drivers_modulelist",
        timeout=500,
    )
    assert (
               data.get("ModuleItem", None)
    ), f"Audit result should have some content, none found: f{pprint_base_formatter(data)}"
    assert (
        len(data["ModuleItem"]) > 1
    ), "There should be more than 1 driver contained within the results"

    return data


@OS_COMPAT(WINDOWS)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.smoke
@pytest.mark.caseid(30409500)
def test_audit_drivers_modulelist(run_driver_module_audit):
    assert run_driver_module_audit, "Data for the audit should be returned."


@OS_COMPAT(WINDOWS)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.smoke
@pytest.mark.caseid(45344)
def test_drive_module_schema_validate(run_driver_module_audit):
    module_type_map = {
        "ModuleAddress": is_numeric_type,
        "ModuleInit": is_numeric_type,
        "ModuleBase": is_numeric_type,
        "ModuleSize": is_numeric_type,
        "ModuleName": is_string_type,
        "ModulePath": is_filepath_type,
    }
    all_failures = []
    modules = [module for module in run_driver_module_audit["ModuleItem"]]
    for module in modules:
        failure_results = return_section_schema_checks(
            section=module, type_mapping=module_type_map, required_keys=module_type_map.keys()
        )
        if failure_results:
            all_failures.append(pprint_base_formatter(failure_results))

    assert not all_failures, "Shouldn't have any missing fields or mismatches, found: {}".format(
        pprint_base_formatter(all_failures)
    )
