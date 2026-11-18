import logging
from pathlib import Path

import pytest
from tests.util import util as razor_util
from tests.util.compatibility import WINDOWS, OS_COMPAT, compatibility_test

from tests.util import memory_utils
from tests.util.compatibility import is_memory_audit_compatible, is_64bit_win10
from tests.util.memory_audit_schema_utils import (
    process_digital_signature_output_schema,
    process_exports_output_schema,
    process_imported_modules_output_schema,
    process_device_item_output_schema,
)
from tests.util.schema_utils import return_missing_fields_in_section, return_section_schema_checks
from tests.util.string_formatting_utils import (
    pprint_missing_fields_failure,
    pprint_comparison_field_failure,
    pprint_base_formatter,
)
from tests.util.type_utils import (
    is_numeric_type,
    is_iso_8601_time_type,
    is_uid_type,
    is_filepath_type,
)
from tests.util.util import sha1_hashfile, sha256_hashfile
from tests.test_xclient.provisioned_xclient import Singleton_XClient

xclient = Singleton_XClient()

driver_item_type_map = {
    "DriverObjectAddress": is_numeric_type,
    "ImageSize": is_numeric_type,
    "ImageBase": is_numeric_type,
    "DriverName": is_filepath_type,
    "DriverInit": is_numeric_type,
    "DriverStartIo": is_numeric_type,
    "DriverUnload": is_numeric_type,
    "created": is_iso_8601_time_type,
    "uid": is_uid_type,
}

irp_type_map = {
    "IRP_MJ_CREATE": is_numeric_type,
    "IRP_MJ_CREATE_NAMED_PIPE": is_numeric_type,
    "IRP_MJ_CLOSE": is_numeric_type,
    "IRP_MJ_WRITE": is_numeric_type,
    "IRP_MJ_READ": is_numeric_type,
    "IRP_MJ_QUERY_INFORMATION": is_numeric_type,
    "IRP_MJ_SET_INFORMATION": is_numeric_type,
    "IRP_MJ_QUERY_EA": is_numeric_type,
    "IRP_MJ_SET_EA": is_numeric_type,
    "IRP_MJ_FLUSH_BUFFERS": is_numeric_type,
    "IRP_MJ_QUERY_VOLUME_INFORMATION": is_numeric_type,
    "IRP_MJ_SET_VOLUME_INFORMATION": is_numeric_type,
    "IRP_MJ_DIRECTORY_CONTROL": is_numeric_type,
    "IRP_MJ_FILE_SYSTEM_CONTROL": is_numeric_type,
    "IRP_MJ_DEVICE_CONTROL": is_numeric_type,
    "IRP_MJ_INTERNAL_DEVICE_CONTROL": is_numeric_type,
    "IRP_MJ_SHUTDOWN": is_numeric_type,
    "IRP_MJ_LOCK_CONTROL": is_numeric_type,
    "IRP_MJ_CLEANUP": is_numeric_type,
    "IRP_MJ_CREATE_MAILSLOT": is_numeric_type,
    "IRP_MJ_QUERY_SECURITY": is_numeric_type,
    "IRP_MJ_SET_SECURITY": is_numeric_type,
    "IRP_MJ_POWER": is_numeric_type,
    "IRP_MJ_SYSTEM_CONTROL": is_numeric_type,
    "IRP_MJ_DEVICE_CHANGE": is_numeric_type,
    "IRP_MJ_QUERY_QUOTA": is_numeric_type,
    "IRP_MJ_SET_QUOTA": is_numeric_type,
    "IRP_MJ_PNP": is_numeric_type,
}

logger = logging.getLogger("tests")


pytestmark = pytest.mark.audit


def process_base_driver_item_schema(driver):
    return return_section_schema_checks(
        section=driver,
        type_mapping=driver_item_type_map,
        required_keys=driver_item_type_map.keys(),
        output_keys_to_exclude=["PEInfo", "StringList"],
    )


def process_base_driver_item_irp_schema(driver):
    return return_section_schema_checks(
        section=driver,
        type_mapping=irp_type_map,
        required_keys=irp_type_map.keys(),
        output_keys_to_exclude=["PEInfo", "StringList"],
    )


def check_for_target_driver(driver_name, driver_names_found):
    assert any([driver.endswith(driver_name) for driver in driver_names_found]), (
        "Should be able to find the driver we want in the audit results, "
        "found the following: \n{}".format(pprint_base_formatter(driver_names_found))
    )


def assertion_compare_wrapper(found, expected):
    assert found == expected, pprint_comparison_field_failure(found, expected)


@pytest.fixture(scope="module")
#def run_audit_with_options_enabled(provisioned_agent, emplace_audits_dll):
def run_audit_with_options_enabled():
    test_params = {
        "enumerate imports": True,
        "enumerate exports": True,
        "MD5": True,
        "SHA1": True,
        "SHA256": True,
        "Verify Digital Signatures": True,
        "strings": True,
        "shortest matched string": "10",
    }
    logger.info("Preparing to run the audit")
    data = xclient.run_job(
        "drivers-signature",
        params=test_params,
        notes="drivers-signature driver process initial collection",
        audit_script_name="test_audit_drivers_signature",
        timeout=500,
    )
    logger.info("Successfully ran the audit")
    failure_assertion_string = "Should have some driver results in the output, none found."
    assert "DriverItem" in data, "{} Audit result: {}".format(
        failure_assertion_string, pprint_base_formatter(data)
    )
    driver_names_found = [
        driver["DriverName"] for driver in data["DriverItem"] if "DriverName" in driver
    ]
    return data, driver_names_found


@pytest.fixture(scope="module")
def collect_acpi_driver_from_audit_results(run_audit_with_options_enabled):
    driver_name = "acpi.sys"
    data, driver_names_found = run_audit_with_options_enabled
    check_for_target_driver(driver_name, driver_names_found)
    acpi_section = [
        driver
        for driver in data["DriverItem"]
        if "DriverName" in driver and driver["DriverName"].endswith('\\' + driver_name)
    ]
    assert len(acpi_section) == 1, f"Should only get 1 instance of acpi.sys driver in results: {acpi_section}"
    yield acpi_section[0]


@pytest.fixture(scope="module")
def collect_volume_driver_from_audit_results(run_audit_with_options_enabled):
    driver_name = "volume.sys"
    data, driver_names_found = run_audit_with_options_enabled
    check_for_target_driver(driver_name, driver_names_found)
    volume_section = [
        driver
        for driver in data["DriverItem"]
        if "DriverName" in driver and driver["DriverName"].endswith(driver_name)
    ]
    assert len(volume_section) == 1, "Should only get 1 instance of volume.sys driver in results"
    yield volume_section[0]


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.caseid(30955641)
def test_audit_drivers_signature(run_audit_with_options_enabled):
    data, _ = run_audit_with_options_enabled
    for driver in data["DriverItem"]:
        base_results = process_base_driver_item_schema(driver)
        irp_results = process_base_driver_item_irp_schema(driver)
        assert not base_results, str(base_results)
        assert not irp_results, str(irp_results)


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.caseid(58117954)
def test_driver_sig_imports_validate_pe_file_single(collect_acpi_driver_from_audit_results):
    audit_acpi_driver = collect_acpi_driver_from_audit_results
    overall_empty_import_modules, remaining_disk_imports_unmatched = {}, {}
    section_unaccounted_imports = []
    # We know these will have PEInfo and imports at this point
    disk_imports = memory_utils.collect_imports_from_pefile(Path(audit_acpi_driver["DriverName"]))
    for imp in audit_acpi_driver["PEInfo"]["ImportedModules"]:
        if not imp["Name"]:
            section_unaccounted_imports.extend(imp["ImportedFunctions"])
            logger.info("Found an imported module without a name, storing and continuing...")
            continue
        disk_match = next(
            filter(lambda x: x["Name"].lower() == imp["Name"].lower(), disk_imports), None
        )
        assert disk_match, "Audit import {} not found on disk, disk imports: {}".format(
            imp["Name"], pprint_base_formatter(disk_imports)
        )
        disk_imports.remove(disk_match)
        # pefile only lists imports by name, so leave out imports by ordinal: empty
        # names, and XClient's "<dll>:<ordinal>" placeholders (e.g. ntoskrnl.exe:0004)
        assertion_compare_wrapper(
            found=sorted(set(
                f for f in imp["ImportedFunctions"]
                if f and not memory_utils.is_xclient_ordinal_placeholder(f, imp["Name"])
            )),
            expected=sorted(set(filter(None, disk_match["ImportedFunctions"]))),
        )
    if section_unaccounted_imports:
        overall_empty_import_modules = {
            "section": audit_acpi_driver["DriverName"],
            "unknown_imports": list(filter(None, section_unaccounted_imports)),
        }
    if disk_imports:
        remaining_disk_imports_unmatched = {
            "section": audit_acpi_driver["DriverName"],
            "disk_imports_not_found": list(filter(None, disk_imports)),
        }
    assert (
        not overall_empty_import_modules
    ), "Found some sections where the ImportedModule has no name: {}".format(
        pprint_base_formatter(overall_empty_import_modules)
    )
    assert (
        not remaining_disk_imports_unmatched
    ), "Found some disk imports which were never found in the audit: {}".format(
        pprint_base_formatter(remaining_disk_imports_unmatched)
    )


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.caseid(14736962)
def test_driver_sig_imports_validate_single_schema(collect_acpi_driver_from_audit_results):
    audit_acpi_driver = collect_acpi_driver_from_audit_results
    results = process_imported_modules_output_schema(audit_acpi_driver["PEInfo"]["ImportedModules"])
    assert not results, pprint_base_formatter(results)


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
# Known failure: Exports missing for acpi.sys and other drivers, ENDPT-109143, ENDPT-225870
@pytest.mark.defect
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.caseid(14736963)
def test_driver_sig_exports_validate_single_schema(collect_acpi_driver_from_audit_results):
    audit_acpi_driver = collect_acpi_driver_from_audit_results
    assert (
        "Exports" in audit_acpi_driver["PEInfo"]
    ), f"Exports section missing in driver results, found: {pprint_base_formatter(audit_acpi_driver)}"
    results = process_exports_output_schema(audit_acpi_driver["PEInfo"]["Exports"])
    assert not results, pprint_base_formatter(results)


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
# Test de-prioritized for feature, known failure: ENDPT-77040
@pytest.mark.defect
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.caseid(14736964)
def test_driver_sig_strings_validate_single_item(collect_acpi_driver_from_audit_results):
    required_string = "KeQueryPerformanceCounter"
    audit_acpi_driver = collect_acpi_driver_from_audit_results
    missing = return_missing_fields_in_section(audit_acpi_driver, ["StringList"])
    assert not missing, pprint_missing_fields_failure(missing, audit_acpi_driver.keys())
    assert audit_acpi_driver["StringList"], "No strings found in the output, unable to compare"
    assert (
        required_string in audit_acpi_driver["StringList"]
    ), "StringList doesn't contain the expected string: \n{}".format(
        pprint_base_formatter(audit_acpi_driver["StringList"])
    )


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
# Test de-prioritized for feature, known failure: ENDPT-77040
@pytest.mark.defect
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.caseid(14736965)
def test_driver_sig_shortest_string_validate_single_item(collect_acpi_driver_from_audit_results):
    audit_acpi_driver = collect_acpi_driver_from_audit_results
    min_string_len = 10
    missing_field = return_missing_fields_in_section(audit_acpi_driver, ["StringList"])
    assert not missing_field, pprint_base_formatter(missing_field)
    assert audit_acpi_driver["StringList"], "No strings found in the output, unable to compare"
    short_strings = [txt for txt in audit_acpi_driver["StringList"] if len(txt) < min_string_len]
    assert (
        not short_strings
    ), "Shouldn't have strings shorter than minimum length, found: {}".format(
        pprint_base_formatter(short_strings)
    )


@pytest.fixture()
def hash_validator(request, collect_acpi_driver_from_audit_results):
    key_name = request.param[0]
    audit_acpi_driver = collect_acpi_driver_from_audit_results
    expected_value = request.param[1](Path(audit_acpi_driver["DriverName"]))
    assert key_name in audit_acpi_driver.keys(), pprint_missing_fields_failure(
        [key_name], audit_acpi_driver.keys()
    )

    assert audit_acpi_driver[key_name] == expected_value, "Hash should match the expected value"


@pytest.mark.parametrize(
    "hash_validator",
    [
        pytest.param(("Md5sum", razor_util.md5_hash_file), marks=[pytest.mark.caseid(14736966)]),
        pytest.param(("Sha1sum", sha1_hashfile), marks=[pytest.mark.caseid(14736967)]),
        pytest.param(("Sha256sum", sha256_hashfile), marks=[pytest.mark.caseid(14736968)]),
    ],
    indirect=["hash_validator"],
    ids=lambda params: params[0],
)
@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@compatibility_test(is_memory_audit_compatible)
def test_driver_sig_hash_validate_single_item(hash_validator):
    pass


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.caseid(14736969)
def test_driver_sig_digital_sig_validate_single_item(collect_acpi_driver_from_audit_results):
    audit_acpi_driver = collect_acpi_driver_from_audit_results
    results = process_digital_signature_output_schema(
        audit_acpi_driver["PEInfo"]["DigitalSignature"]
    )
    assert not results, pprint_base_formatter(results)


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@compatibility_test(is_64bit_win10)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.caseid(14736970)
def test_driver_sig_device_info_validate_single_item(collect_volume_driver_from_audit_results):
    # TODO: determine valid device info formats/strings/values
    audit_volume_driver = collect_volume_driver_from_audit_results
    results = process_device_item_output_schema(audit_volume_driver["DeviceItem"])
    assert not results, pprint_base_formatter(results)
