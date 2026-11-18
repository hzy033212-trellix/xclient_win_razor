import copy
import datetime
import logging
import subprocess
from pathlib import Path

import pytest
from addict import Dict
from tests.util import util as razor_util
from tests.util.compatibility import WINDOWS, OS_COMPAT, compatibility_test
from tests.util.fixtures_audits import collect_test_binaries, start_test_binary

from tests.util import memory_utils, audit_result_utils
from tests.util.compatibility import is_memory_audit_compatible, has_8gb_ram_or_more
from tests.util.memory_audit_schema_utils import (
    process_digital_signature_output_schema,
    process_exports_output_schema,
    process_imported_modules_output_schema,
)
from tests.util.memory_utils import check_schema_handles_in_proc, validate_handles_not_missing
from tests.util.schema_utils import return_missing_fields_in_section, return_section_schema_checks
from tests.util.string_formatting_utils import (
    pprint_missing_fields_failure,
    pprint_comparison_field_failure,
    pprint_base_formatter,
)
from tests.util.type_utils import (
    is_numeric_type,
    is_pid_type,
    is_string_type,
    is_duration_type,
    is_filepath_type,
    is_sid_type,
    is_username_type,
    is_iso_8601_time_type,
    is_uid_type,
    is_bool_type,
    is_md5_type,
    is_sha1_type,
    is_sha256_type,
    is_pe_hash_type,
)
from tests.util.util import sha1_hashfile, sha256_hashfile
from tests.test_xclient.provisioned_xclient import (
    Singleton_XClient,
    cancel_prefetched_audits,
    prefetch_audits,
)

xclient = Singleton_XClient()

process_type_map = {
    "name": is_string_type,
    "pid": is_pid_type,
    "parentpid": is_pid_type,
    "Username": is_username_type,
    "SecurityID": is_sid_type,
    "SecurityType": is_string_type,
    "path": is_filepath_type,
    "arguments": is_string_type,
    "startTime": is_iso_8601_time_type,
    "kernelTime": is_duration_type,
    "userTime": is_duration_type,
    "uid": is_uid_type,
    "created": is_iso_8601_time_type,
}

logger = logging.getLogger("tests")


pytestmark = pytest.mark.audit

# Labels of the audits run by the shared (module-scoped) fixtures below. Each test
# lists the ones it actually reads in @pytest.mark.audit_artifacts, and gets a copy
# of only those in its own temp/test_processes_memory/<test>/<label>/ folder
# (see save_fixture_audit_artifacts in conftest.py).


def full_audit_label(binary):
    """Audit of one test binary by run_processes_memory_multi_script_processes."""
    return "processes-memory_full_{}".format(binary)


CREATEH_FULL_AUDIT = full_audit_label("CreateH")
NAME_CREATEH_AUDIT = "processes-memory_name_CreateH"
ALL_MEMORY_AUDIT = "processes-memory_all"
ALL_API_AUDIT = "processes-api_all"
API_CREATEH_AUDIT = "processes-api_CreateH_handles_sections"
STRINGS_TESTHELPER32_AUDIT = "processes-memory_strings_TestHelper32"
# The large-address-aware helper test_processes_memory_large_address_aware_process
# reads on this platform. No test reads the other one (TestHelper32_laa on x64), so
# its full audit is not run.
LAA_BINARY = "TestHelper64_laa" if razor_util.is_x64() else "TestHelper32_laa"
UNUSED_LAA_BINARY = "TestHelper32_laa" if razor_util.is_x64() else None
LAA_FULL_AUDIT = full_audit_label(LAA_BINARY)


def process_sections_peinfo_output_schema(pe_info):
    # TODO: add logic to mismatch utilities to take in these very specific types
    possible_subsystem_types = ["Windows_CUI", "Windows_GUI"]
    possible_pe_types = ["Dll", "Executable"]

    pe_info_type_map = {"BaseAddress": is_numeric_type, "PETSHash": is_pe_hash_type}
    if "PETimeStamp" in pe_info:
        pe_info_type_map["PETimeStamp"] = is_iso_8601_time_type

    pe_info_results = return_section_schema_checks(
        section=pe_info,
        type_mapping=pe_info_type_map,
        required_keys=pe_info_type_map.keys(),
        output_keys_to_exclude=["Exports", "ImportedModules"],
    )

    if pe_info["Type"] not in possible_pe_types:
        pe_info_results["type_unexpected"] = "Type unexpected: {}".format(pe_info["Type"])
    if pe_info["Subsystem"] not in possible_subsystem_types:
        pe_info_results["subsystem_unexpected"] = "Subsystem unexpected: {}".format(
            pe_info["Subsystem"]
        )

    return pe_info_results


def process_sections_output_schema(section):
    section_type_map = {
        "Mapped": is_bool_type,
        "Protection": is_string_type,
        "RawFlags": is_numeric_type,
        "RegionSize": is_numeric_type,
        "RegionStart": is_numeric_type,
    }
    if section["Mapped"] == "true":
        section_type_map["Name"] = is_filepath_type
        section_type_map["MemD5"] = is_md5_type
        section_type_map["Md5sum"] = is_md5_type
        section_type_map["Sha1sum"] = is_sha1_type
        section_type_map["Sha256sum"] = is_sha256_type

    section_results = return_section_schema_checks(
        section=section,
        type_mapping=section_type_map,
        required_keys=section_type_map.keys(),
        output_keys_to_exclude=["PEInfo"],
    )
    if "PEInfo" in section:
        pe_failures = process_sections_peinfo_output_schema(section["PEInfo"])
        if pe_failures:
            section_results["pe_info_results"] = pe_failures

    return section_results


def process_base_process_item_schema(process):
    return return_section_schema_checks(
        section=process,
        type_mapping=process_type_map,
        required_keys=process_type_map.keys(),
        output_keys_to_exclude=["HandleList", "SectionList"],
    )


def assertion_compare_wrapper(found, expected):
    assert found == expected, pprint_comparison_field_failure(found, expected)


def current_user_sid():
    # The test binaries are started by this test run, so they run as the current user
    output = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True, check=True
    ).stdout
    return output.strip().split(",")[-1].strip('"')


def assertion_start_time_wrapper(found, target_proc_obj, margin_seconds=2):
    # startTime is reported in whole seconds (UTC), psutil's create_time has sub-second precision
    expected = datetime.datetime.utcfromtimestamp(target_proc_obj.create_time())
    found_time = datetime.datetime.strptime(found, "%Y-%m-%dT%H:%M:%SZ")
    assert abs((found_time - expected).total_seconds()) <= margin_seconds, (
        pprint_comparison_field_failure(found, expected.strftime("%Y-%m-%dT%H:%M:%SZ"))
    )


def check_process_result_and_merge(data):
    try:
        if len(data["ProcessItem"]) > 1:
            # processes can be duplicated in the audit result, each entry could have part of the
            # total desired content for a process, here we're merging results together to get a
            # single final ProcessItem to look through
            items = [item for item in data["ProcessItem"]]
            final_process_item = {}
            for i in items:
                audit_result_utils.update(final_process_item, i)
            # NOW we have a merged and huge result. de-duping can be done with each test case
            logger.info(
                "Audit returned result as multiple ProcessItems, merging results will cause "
                "duplicates, remaining tests should handle these duplicates as needed."
            )
        else:
            final_process_item = data["ProcessItem"][0]
    except (KeyError, IndexError):
        raise AssertionError(
            "Unable to find ProcessItem in audit result: {}".format(pprint_base_formatter(data))
        )
    return final_process_item


################################
# Memory Audits audit fixtures #
################################

# Each audit of the module-scoped fixtures below, built from the started processes:
# (audit name, audit script, params, timeout, artifact label). A fixture and
# prefetch_module_audits use the same spec, so a prefetched script is exactly the
# one its fixture runs.


def full_audit_jobs(processes):
    """run_processes_memory_multi_script_processes: one audit per started binary."""
    return [
        ("processes-memory", "test_process_memory_single_process_result_validate", {
            "pid": proc.pid,
            "handles": True,
            "sections": True,
            "enumerate imports": True,
            "enumerate exports": True,
            "MemD5": True,
            "MD5": True,
            "SHA1": True,
            "SHA256": True,
            "Verify Digital Signatures": True,
        }, 500, full_audit_label(binary))
        for binary, proc in processes.items() if binary != UNUSED_LAA_BINARY
    ]


def name_createh_job(processes):
    return ("processes-memory", "test_process_memory_single_process_schema_validate",
            {"process name": processes.CreateH.name()}, 300, NAME_CREATEH_AUDIT)


def all_memory_job(processes):
    return ("processes-memory", "test_processes_memory_all_processes_no_options_schema_validate",
            {}, 300, ALL_MEMORY_AUDIT)


def all_api_job(processes):
    return ("processes-api", "test_processes_api_memory_compare_base_no_options", {}, 300, ALL_API_AUDIT)


def api_createh_job(processes):
    return ("processes-api", "test_processes_memory_compare_processes_api_single_process", {
        "process name": processes.CreateH.name(),
        "handles": True,
        "sections": True,
    }, 300, API_CREATEH_AUDIT)


def regex_createh_job(processes):
    return ("processes-memory", "test_processes_memory_content_regexfield_validate",
            {"pid": processes.CreateH.pid, "Content Regex": ["sfAgent"]}, 500, "")


STRINGS_MIN_LENGTH = 15


def strings_testhelper32_job(processes):
    return ("processes-memory", "test_processes_memory_string_capture_single_process", {
        "pid": processes.TestHelper32.pid,
        "strings": True,
        "shortest matched string": STRINGS_MIN_LENGTH,
    }, 500, STRINGS_TESTHELPER32_AUDIT)


# fixture (or test) name -> its audits, for prefetch_module_audits
MODULE_AUDITS = {
    "run_processes_memory_multi_script_processes": full_audit_jobs,
    "run_audit_with_process_name_option": lambda p: [name_createh_job(p)],
    "run_audit_all_processes_no_options": lambda p: [all_memory_job(p)],
    "run_api_audit_all_processes_no_options": lambda p: [all_api_job(p)],
    "run_api_audit_with_options_enabled_single_process": lambda p: [api_createh_job(p)],
    "test_processes_memory_content_regexfield_validate": lambda p: [regex_createh_job(p)],
    "collect_testhelper_with_strings_argument": lambda p: [strings_testhelper32_job(p)],
}


def run_audit_job(job, notes=""):
    audit_name, audit_script_name, params, timeout, label = job
    return xclient.run_job(audit_name, params=params, notes=notes, audit_script_name=audit_script_name,
                           timeout=timeout, artifact_label=label)


@pytest.fixture(scope="module")
def start_test_binaries(collect_test_binaries):
    test_processes = Dict()
    try:
        for binary, binary_path in collect_test_binaries.items():
            test_processes[binary] = start_test_binary(binary_path)
        yield test_processes
    finally:
        # Stop the binaries after the module's tests have completed
        for proc in test_processes.values():
            proc.kill()


@pytest.fixture(scope="module")
def prefetch_module_audits(request, start_test_binaries):
    """Drop the audits of this module's selected tests as one batch, in the order the
    tests need them, as soon as the binaries run (provisioned_xclient.prefetch_audits).
    Each fixture's run_job then takes its task instead of dropping its own, so the
    daemon runs them back to back. Not prefetched: the 5k-argument audit, whose
    function-scoped fixture starts its own process."""
    needed = []
    for item in request.session.items:
        if item.module is not request.module:
            continue
        for name in [item.originalname] + list(item.fixturenames):
            if name in MODULE_AUDITS and name not in needed:
                needed.append(name)
    prefetch_audits([(job[1], job[2], job[3]) for name in needed
                     for job in MODULE_AUDITS[name](start_test_binaries)])
    yield
    cancel_prefetched_audits()


@pytest.fixture(scope="module")
def run_processes_memory_multi_script_processes(start_test_binaries, prefetch_module_audits):
    """
    This fixture will take started binaries and collect audit results for each, simplifying re-use
    later in the test suite.
    :param start_test_binaries: a list of running processes related to test files (psutil Processes)
    :return: dict containing audits for each test file which is running, accessible by filename
    """
    audit_results = {}
    for job in full_audit_jobs(start_test_binaries):
        data = run_audit_job(job, notes="processes-memory single process collection")
        final_process_item = check_process_result_and_merge(data)
        audit_results[final_process_item["name"]] = final_process_item
    return audit_results


@pytest.fixture(scope="module")
def run_audit_with_process_name_option(start_test_binaries, prefetch_module_audits):
    data = run_audit_job(name_createh_job(start_test_binaries),
                         notes="processes-memory single process process name collection")
    final_process_item = check_process_result_and_merge(data)
    return final_process_item


@pytest.fixture(scope="module")
def run_audit_all_processes_no_options(start_test_binaries, prefetch_module_audits):
    data = run_audit_job(all_memory_job(start_test_binaries), notes="processes-memory all processes collection")
    assert "ProcessItem" in data, f"Audit result did not contain any process items, {pprint_base_formatter(data)}"
    assert len(data["ProcessItem"]) > 1, "There should be more than 1 process in the result"
    return data


@pytest.fixture(scope="module")
def run_api_audit_all_processes_no_options(start_test_binaries, prefetch_module_audits):
    data = run_audit_job(all_api_job(start_test_binaries), notes="processes-api all processes collection")
    assert "ProcessItem" in data, f"Audit result did not contain any process items, {pprint_base_formatter(data)}"
    assert len(data["ProcessItem"]) > 1, "There should be more than 1 process in the result"
    return data


@pytest.fixture(scope="module")
def run_api_audit_with_options_enabled_single_process(start_test_binaries, prefetch_module_audits):
    data = run_audit_job(api_createh_job(start_test_binaries),
                         notes="processes-api single process initial collection")
    assert "ProcessItem" in data, f"Audit result did not contain any process items, {pprint_base_formatter(data)}"
    assert (
        len(data["ProcessItem"]) == 1
    ), "There should only be one resulting item in the audit, Full audit results: \n{}".format(
        pprint_base_formatter(data)
    )
    # Here only returning the 1 result from the audit instead of looping later.
    return data["ProcessItem"][0]


############################################
# Memory Audits single process validations #
############################################


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45629)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(NAME_CREATEH_AUDIT)
def test_process_memory_single_process_schema_validate(run_audit_with_process_name_option):
    createh_process = run_audit_with_process_name_option
    schema_failure = process_base_process_item_schema(createh_process)
    assert not schema_failure, "Found process issues: {}".format(
        pprint_base_formatter(schema_failure)
    )


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45626)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(CREATEH_FULL_AUDIT)
def test_process_memory_single_process_result_validate(
    start_test_binaries, run_processes_memory_multi_script_processes
):
    process = run_processes_memory_multi_script_processes["CreateH.exe"]
    # We need to assume there is only 1 instance running
    target_proc_obj = start_test_binaries.CreateH
    # Not compared: uid is random, created is when the item was written to the audit, and
    # kernelTime/userTime keep changing while the process runs
    assertion_compare_wrapper(found=process["SecurityID"], expected=current_user_sid())
    assertion_start_time_wrapper(found=process["startTime"], target_proc_obj=target_proc_obj)
    assertion_compare_wrapper(found=process["SecurityType"], expected="SidTypeUser")
    assertion_compare_wrapper(
        found=Path(process["path"]), expected=Path(target_proc_obj.exe()).parent
    )
    assertion_compare_wrapper(found=process["name"], expected=target_proc_obj.name())
    assertion_compare_wrapper(found=process["parentpid"], expected=target_proc_obj.ppid())
    assertion_compare_wrapper(found=process["pid"], expected=target_proc_obj.pid)
    assertion_compare_wrapper(
        found=process["arguments"].lower(), expected=target_proc_obj.exe().lower()
    )
    assertion_compare_wrapper(found=process["Username"], expected=target_proc_obj.username())


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45630)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(CREATEH_FULL_AUDIT)
def test_process_memory_single_process_sections_schema_validate(
    run_processes_memory_multi_script_processes,
):
    """
    Basic capture test for a process with the sections option enabled
    :return:
    """
    data = run_processes_memory_multi_script_processes["CreateH.exe"]
    assert "SectionList" in data, "Should have SectionList, found: {}".format(data.keys())
    sections = [section for section in data["SectionList"]]
    section_schema_failures = []
    for section in sections:
        schema_failure = process_sections_output_schema(section)
        if schema_failure:
            section_schema_failures.append(schema_failure)
    assert not section_schema_failures, "Found sections issues: {}".format(
        pprint_base_formatter(section_schema_failures)
    )


@pytest.fixture(scope="module")
def handle_de_duper(run_processes_memory_multi_script_processes):
    process = run_processes_memory_multi_script_processes["CreateH.exe"]
    raw_handle_list = process["HandleList"]
    # de-dupe handles here, handles will only ever be a list of dicts, nothing complex
    handle_list = list({frozenset(item.items()): item for item in raw_handle_list}.values())
    yield handle_list, process


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45628)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(CREATEH_FULL_AUDIT)
def test_process_memory_single_process_handles_schema_validate(handle_de_duper):
    handle_list, data = handle_de_duper
    assert "HandleList" in data, "Should have HandleList, found: {}".format(data.keys())
    check_schema_handles_in_proc(handle_list)


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45618)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(CREATEH_FULL_AUDIT)
def test_process_memory_single_process_handles_result_validate(handle_de_duper):
    expected_handles = {
        "Section": "sfAgentSection",
        "Semaphore": "sfAgentSemaphore",
        "SymbolicLink": "sfAgentSymbolicLink",
        "Timer": "sfAgentWaitableTimer",
        "WindowStation": "sfAgentWinSta",
        "Directory": "sfAgent",
        "ALPC Port": "sfAgentTestPort",
        "Desktop": "sfAgentDesktop",
        "Event": "sfAgentEvent",
        "Job": "sfAgentJob",
        "Mutant": "sfAgentMutex",
    }
    handle_list, process = handle_de_duper
    validate_handles_not_missing(
        expected_handles=expected_handles, process=process, handle_list=handle_list
    )


#########################################
# functions for "cleaning" audit result #
#########################################


def imported_mod_builder(imported_modules):
    flattened_imports = [item for sublist in imported_modules for item in sublist]
    import_name_list = set([item["Name"] for item in flattened_imports])
    # Can't just de-dupe must update items
    list_imported_modules = []
    for _item in import_name_list:
        final_imported_module = {}
        # make a new empty dictionary, cram info from the duplicates into one record
        for match in [i for i in flattened_imports if i["Name"] == _item]:
            audit_result_utils.update(final_imported_module, match)
        # set the final imported module
        final_imported_module["ImportedFunctions"] = list(
            set(final_imported_module["ImportedFunctions"])
        )
        list_imported_modules.append(final_imported_module)
    return list_imported_modules


def export_func_builder(exports_list):
    export_dll_name_list = set([item["DllName"] for item in exports_list])
    final_exports = {}
    for unique_dllname in export_dll_name_list:
        for match in [i for i in exports_list if i["DllName"] == unique_dllname]:
            audit_result_utils.update(final_exports, match)
    # Now that we have one "Exports" section, de duplicate the list "ExportedFunctions"
    final_exported_func_list = []
    empty_string_count = len([x for x in final_exports["ExportedFunctions"] if x == ""])
    # This is to keep down the number of empty strings in the result to "match" what would occur
    # with 1 item instead of duplicates in the audit result
    empty_string_count = empty_string_count // len(exports_list)
    empty_strings_added = 0
    for _export_name in final_exports["ExportedFunctions"]:
        if _export_name == "" and empty_strings_added < empty_string_count:
            final_exported_func_list.append("")
        else:
            if _export_name not in final_exported_func_list:
                final_exported_func_list.append(_export_name)
    final_exports["ExportedFunctions"] = final_exported_func_list
    return final_exports


def collect_sections_to_merge_and_sha1s(process):
    sections_peinfos = [sec for sec in process["SectionList"] if "PEInfo" in sec]
    sections_imports_or_exports = [
        sec for sec in sections_peinfos if "ImportedModules" in sec["PEInfo"]
    ]
    sections_imports_or_exports.extend(
        [sec for sec in sections_peinfos if "Exports" in sec["PEInfo"]]
    )
    # get a unique list of Sha1sums, to help guide the sections which need to be updated
    module_sha1_list_imports = set([item["Sha1sum"] for item in sections_imports_or_exports])
    return sections_imports_or_exports, module_sha1_list_imports


def collect_imported_modules_in_sections(sections):
    return [
        sec["PEInfo"]["ImportedModules"] for sec in sections if "ImportedModules" in sec["PEInfo"]
    ]


def collect_exports_in_sections(sections):
    return [sec["PEInfo"]["Exports"] for sec in sections if "Exports" in sec["PEInfo"]]


def process_section_constructor(process, imports_only=False, exports_only=False):
    sections_to_modify, sha1_list = collect_sections_to_merge_and_sha1s(process)

    final_section_list = []
    for item in sha1_list:
        # get the first item in my big group of sections with the target sha1sum
        # the whole point here is to have a single element which is getting all
        # the info collected in the other duplicates. So we get our target to update, and all the
        # others
        section_matches = [i for i in sections_to_modify if i["Sha1sum"] == item]
        final_section = section_matches[0]
        # process the ImportedModules portions of the audit for a single section
        imported_modules = collect_imported_modules_in_sections(section_matches)
        if imported_modules and not exports_only:
            # final_imported_modules is now correct/complete re_apply it to the audit result
            final_section["PEInfo"]["ImportedModules"] = imported_mod_builder(imported_modules)
        # process the Exports portions of the audit for a single section
        exports_list = collect_exports_in_sections(section_matches)
        if exports_list and not imports_only:
            final_section["PEInfo"]["Exports"] = export_func_builder(exports_list)
        # append "cleaned" section to our results
        final_section_list.append(copy.deepcopy(final_section))

    if imports_only:
        return [item for item in final_section_list if "ImportedModules" in item["PEInfo"]]
    if exports_only:
        return [item for item in final_section_list if "Exports" in item["PEInfo"]]
    else:
        return final_section_list


################################################
# end of functions for "cleaning" audit result #
################################################


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(31711652)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(CREATEH_FULL_AUDIT)
def test_process_memory_import_pe_result_validate(run_processes_memory_multi_script_processes):
    process = run_processes_memory_multi_script_processes["CreateH.exe"]
    sections_of_note = process_section_constructor(process, imports_only=True)
    overall_empty_import_modules, remaining_disk_imports_unmatched = [], []
    for section in sections_of_note:
        section_unaccounted_imports = []
        # We know these will have PEInfo and imports at this point
        disk_imports = memory_utils.collect_imports_from_pefile(Path(section["Name"]))
        for imp in section["PEInfo"]["ImportedModules"]:
            if not imp["Name"]:
                section_unaccounted_imports.extend(imp["ImportedFunctions"])
                logger.info("Found an imported module without a name, storing and continuing...")
                continue
            disk_match = next(
                filter(lambda x: x["Name"].lower() == imp["Name"].lower(), disk_imports), None
            )
            assert disk_match, "Audit import {} of {} not found on disk, disk imports: {}".format(
                imp["Name"], section["Name"], pprint_base_formatter(disk_imports)
            )
            disk_imports.remove(disk_match)
            # pefile only lists imports by name, so leave out imports by ordinal: empty
            # names, and XClient's placeholder (the module's own name, e.g. USER32.dll)
            assertion_compare_wrapper(
                found=sorted(set(
                    f for f in imp["ImportedFunctions"]
                    if f and not memory_utils.is_xclient_ordinal_placeholder(f, imp["Name"])
                )),
                expected=sorted(set(filter(None, disk_match["ImportedFunctions"]))),
            )
        if section_unaccounted_imports:
            overall_empty_import_modules.append(
                {
                    "section": section["Name"],
                    "imported_funcs_no_module_name": list(
                        filter(None, section_unaccounted_imports)
                    ),
                }
            )
        if disk_imports:
            remaining_disk_imports_unmatched.append(
                {
                    "section": section["Name"],
                    "disk_imports_not_found": list(filter(None, disk_imports)),
                }
            )
    assert (
        not overall_empty_import_modules
    ), "Found some sections where the ImportedModule has no name: {}".format(
        pprint_base_formatter(overall_empty_import_modules)
    )
    assert (
        not remaining_disk_imports_unmatched
    ), "Found some disk imports which were found in the PE, but not the audit: {}".format(
        pprint_base_formatter(remaining_disk_imports_unmatched)
    )


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(31711653)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(CREATEH_FULL_AUDIT)
def test_process_memory_export_pe_result_validate(run_processes_memory_multi_script_processes):
    process = run_processes_memory_multi_script_processes["CreateH.exe"]
    sections_of_note = process_section_constructor(process, exports_only=True)
    overall_empty_export_list = []
    for section in sections_of_note:
        # We know these will have PEInfo and imports at this point
        disk_exports = memory_utils.collect_exports_from_pefile(Path(section["Name"]))
        audit_exports = copy.deepcopy(section["PEInfo"]["Exports"]["ExportedFunctions"])
        empties_removed = list(filter(None, audit_exports))
        if not empties_removed:
            overall_empty_export_list.append(
                {"section": section["Name"], "exports_with_only_empty_strings": empties_removed}
            )
        if len(empties_removed) < len(audit_exports) and empties_removed:
            overall_empty_export_list.append(
                {"section": section["Name"], "exports_with_some_empty_strings": empties_removed}
            )
        # XClient's "Ordinal:<n>" placeholder is only right for an export that has no
        # name. If the file on disk has a name for that ordinal, XClient failed to
        # read the name; report that plainly instead of as a list mismatch.
        named_ordinals = memory_utils.collect_named_export_ordinals(Path(section["Name"]))
        mislabeled = {
            ordinal: named_ordinals[ordinal]
            for ordinal in (memory_utils.xclient_ordinal_export_number(f) for f in empties_removed)
            if ordinal is not None and ordinal in named_ordinals
        }
        assert not mislabeled, (
            "XClient reported {} named export(s) of {} by ordinal only (Ordinal:<n>); "
            "the file on disk names them:\n{}".format(
                len(mislabeled), section["Name"],
                "\n".join("  Ordinal:{:04d} -> {}".format(o, n) for o, n in sorted(mislabeled.items())),
            )
        )
        # pefile only lists exports by name, so leave out XClient's placeholders for
        # exports by ordinal only ("Ordinal:0008")
        named_exports = [f for f in empties_removed if not memory_utils.is_xclient_ordinal_placeholder(f)]
        assertion_compare_wrapper(
            found=sorted(set(named_exports)), expected=sorted(set(filter(None, disk_exports)))
        )
    assert (
        not overall_empty_export_list
    ), "Found exports which were found in the PE, but not the audit: {}".format(
        pprint_base_formatter(overall_empty_export_list)
    )


@pytest.fixture()
def import_export_validator(request, run_processes_memory_multi_script_processes):
    key_name = request.param[0]
    validation_func = request.param[1]
    sections_with_mismatch = []
    section_with_key_found = False
    sections_no_collection = []

    process = run_processes_memory_multi_script_processes["CreateH.exe"]
    for section in process["SectionList"]:
        # Can only currently validate that the result has been included, nothing more than that.
        # Sections without a Name are not backed by a file, so they have no PE info to check.
        if "Name" in section:
            if "PEInfo" not in section:
                logger.info("PEInfo not found in section, skipping")
                continue
            missing_fields = return_missing_fields_in_section(section, ["PEInfo"])
            assert not missing_fields, pprint_missing_fields_failure(missing_fields, process)
            pe_info = section["PEInfo"]
            if key_name in pe_info:
                section_with_key_found = True
                schema_mismatch = validation_func(pe_info[key_name])
                if schema_mismatch:
                    sections_with_mismatch.append(
                        {"_pe_name": section["Name"], "mismatches": schema_mismatch}
                    )
            elif "Exports" not in section["PEInfo"] and "ImportedModules" not in section["PEInfo"]:
                sections_no_collection.append(section["Name"])
    assert (
        section_with_key_found
    ), "Should have at least 1 section with {}. sections found which don't have key: \n {}".format(
        key_name, pprint_base_formatter(sections_no_collection)
    )
    assert not sections_with_mismatch, pprint_base_formatter(sections_with_mismatch)


@pytest.mark.parametrize(
    "import_export_validator",
    [
        pytest.param(
            (
                "ImportedModules",
                process_imported_modules_output_schema,
                "Should end up with at least 1 section containing imports",
            ),
            marks=[pytest.mark.caseid(45616)],
        ),
        pytest.param(
            (
                "Exports",
                process_exports_output_schema,
                "Should end up with at least 1 section containing exports",
            ),
            marks=[pytest.mark.caseid(45615)],
        ),
    ],
    indirect=["import_export_validator"],
    ids=lambda params: params[0],
)
@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(CREATEH_FULL_AUDIT)
def test_process_memory_import_export_schema_validate(import_export_validator):
    pass


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45638)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(CREATEH_FULL_AUDIT)
def test_process_memory_single_process_digital_signature_result_validate(
    run_processes_memory_multi_script_processes,
):
    digital_schema_results = []
    signature_found = False
    process = run_processes_memory_multi_script_processes["CreateH.exe"]
    for section in process["SectionList"]:
        if "DigitalSignature" in section:
            signature_found = True
            schema_results = process_digital_signature_output_schema(section["DigitalSignature"])
            if schema_results:
                digital_schema_results.append(
                    {"_section": section.get("Name"), "mismatches": schema_results}
                )
    assert signature_found, "Should have at least 1 section with DigitalSignature"
    assert not digital_schema_results, pprint_base_formatter(digital_schema_results)


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45621)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(CREATEH_FULL_AUDIT)
def test_process_memory_single_process_memd5_hash_result_validate(
    run_processes_memory_multi_script_processes,
):
    sections_without_memd5 = []
    process = run_processes_memory_multi_script_processes["CreateH.exe"]
    for section in process["SectionList"]:
        if "MemD5" in section:
            result = is_md5_type(section["MemD5"])
            if not result:
                # make a copy of the section and pop large fields
                section_copy = copy.deepcopy(section)
                for item in ["ImportedModules", "Exports"]:
                    section_copy.pop(item, None)
                sections_without_memd5.append(section_copy)
    assert not sections_without_memd5, pprint_base_formatter(sections_without_memd5)


@pytest.fixture()
def hash_validator(
    request,
    collect_test_binaries,
    start_test_binaries,
    run_processes_memory_multi_script_processes,
):
    key_name = request.param[0]
    # Hash the file first before walking the audit results
    expected_value = request.param[1](collect_test_binaries.CreateH)
    binary = start_test_binaries.CreateH
    process = run_processes_memory_multi_script_processes["CreateH.exe"]
    sections_compared = 0
    for section in process["SectionList"]:
        if key_name in section and binary.name() in section["Name"]:
            sections_compared += 1
            assert section[key_name] == expected_value, "Hash should match the expected value"
    assert sections_compared, "Should have at least 1 {} section with {}".format(
        binary.name(), key_name
    )


@pytest.mark.parametrize(
    "hash_validator",
    [
        pytest.param(("Md5sum", razor_util.md5_hash_file), marks=[pytest.mark.caseid(45620)]),
        pytest.param(("Sha1sum", sha1_hashfile), marks=[pytest.mark.caseid(45633)]),
        pytest.param(("Sha256sum", sha256_hashfile), marks=[pytest.mark.caseid(45634)]),
    ],
    indirect=["hash_validator"],
    ids=lambda params: params[0],
)
@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(CREATEH_FULL_AUDIT)
def test_process_memory_single_process_hash_result_validate(hash_validator):
    pass


######################################################
# Memory Audits single process pid option validation #
######################################################


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45623)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(CREATEH_FULL_AUDIT)
def test_processes_memory_single_process_pid_option_result_validate(
    start_test_binaries, run_processes_memory_multi_script_processes
):
    createh_process = start_test_binaries.CreateH
    process = run_processes_memory_multi_script_processes["CreateH.exe"]
    missing_fields = return_missing_fields_in_section(process, process_type_map.keys())
    assert not missing_fields, pprint_missing_fields_failure(missing_fields, process)
    # Not compared: uid is random, created is when the item was written to the audit, and
    # kernelTime/userTime keep changing while the process runs
    assertion_compare_wrapper(found=process["SecurityID"], expected=current_user_sid())
    assertion_start_time_wrapper(found=process["startTime"], target_proc_obj=createh_process)
    assertion_compare_wrapper(found=process["SecurityType"], expected="SidTypeUser")
    assertion_compare_wrapper(
        found=Path(process["path"]), expected=Path(createh_process.exe()).parent
    )
    assertion_compare_wrapper(found=process["name"], expected=createh_process.name())
    assertion_compare_wrapper(found=process["parentpid"], expected=createh_process.ppid())
    assertion_compare_wrapper(found=process["pid"], expected=createh_process.pid)
    assertion_compare_wrapper(
        found=process["arguments"].lower(), expected=createh_process.exe().lower()
    )
    assertion_compare_wrapper(found=process["Username"], expected=createh_process.username())


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45632)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(ALL_MEMORY_AUDIT)
def test_processes_memory_all_processes_no_options_schema_validate(
    run_audit_all_processes_no_options,
):
    data = run_audit_all_processes_no_options
    processes_to_exclude = [
        "System Idle Process",
        "WmiPrvSE.exe",
        "Memory Compression",
        "Registry",
        "System",
    ]

    full_schema_results = []
    for audit_process in data["ProcessItem"]:
        # check for missing fields and type mismatches in all processes
        if audit_process["name"] in processes_to_exclude:
            continue
        schema_results = process_base_process_item_schema(audit_process)
        if schema_results:
            full_schema_results.append(schema_results)

    assert not full_schema_results, pprint_base_formatter(full_schema_results)


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(31645138)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(API_CREATEH_AUDIT, CREATEH_FULL_AUDIT)
def test_processes_memory_compare_processes_api_single_process(
    run_api_audit_with_options_enabled_single_process, run_processes_memory_multi_script_processes
):
    api_process = run_api_audit_with_options_enabled_single_process
    raw_process = run_processes_memory_multi_script_processes["CreateH.exe"]
    mismatched_fields = []
    for api_item_key, api_item_value in api_process.items():
        # the created key is the time at which the item is added to the audit.
        if api_item_key in ["HandleList", "SectionList", "created", "uid"]:
            continue
        if not api_item_value == raw_process.get(api_item_key):
            mix = {
                "_key": api_item_key,
                "raw_value": raw_process.get(api_item_key),
                "api_value": api_item_value,
            }
            mismatched_fields.append(mix)
    assert not mismatched_fields, pprint_base_formatter(mismatched_fields)


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(31645137)
# Known failure when the XClient service runs the audits: processes-memory reports System
# (S-1-5-18) as SidTypeUser, processes-api as SidTypeWellKnownGroup.
# See XCLIENT_BUG_SYSTEM_SECURITYTYPE.md
@pytest.mark.defect
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(ALL_API_AUDIT, ALL_MEMORY_AUDIT)
def test_processes_api_memory_compare_base_no_options(
    run_audit_all_processes_no_options, run_api_audit_all_processes_no_options
):
    api_result = run_api_audit_all_processes_no_options
    raw_result = run_audit_all_processes_no_options

    def formatter(result):
        # List of dictionaries
        result_string = ""
        for item in result:
            result_string += "\n Process Name: {}" "\n\t Mismatches: {}\n".format(
                item["_process_name_api"], pprint_base_formatter(item["mismatches"])
            )
        return result_string

    def compare_raw_to_api(raw_item, api_item):
        diffs = []
        # Copy so we don't alter the "common" dictionary
        raw_copy = copy.deepcopy(raw_item)
        [raw_copy.pop(rem_item, None) for rem_item in ["uid", "created", "kernelTime", "userTime"]]
        for raw_key, raw_value in raw_copy.items():
            # The API audit can't read some fields (e.g. path, arguments) of protected processes
            # and reports them empty; reading them from memory is what processes-memory adds
            if api_item.get(raw_key) == "" and raw_value:
                continue
            if not raw_value == api_item.get(raw_key):
                mismatch = {"_key": raw_key, "raw_value": raw_value, "api_value": api_item.get(raw_key)}
                diffs.append(mismatch)
        return diffs

    def process_identity(process):
        # a process is a "match" when the following are the same: name, startTime, pid
        return process.get("name"), process.get("startTime"), process.get("pid")

    # The two audits list processes in different orders, so match them by identity. Processes
    # which started or exited between the two audits are only in one of them.
    api_by_identity = {process_identity(p): p for p in api_result["ProcessItem"]}
    raw_not_matching_api = []
    matched_count = 0
    for raw_process in raw_result["ProcessItem"]:
        api_process = api_by_identity.get(process_identity(raw_process))
        if api_process is None:
            continue
        matched_count += 1
        mismatches = compare_raw_to_api(raw_process, api_process)
        if mismatches:
            process_mismatch = {
                "_process_name_api": api_process["name"],
                "mismatches": mismatches,
            }
            raw_not_matching_api.append(process_mismatch)

    assert matched_count * 2 >= len(raw_result["ProcessItem"]), (
        "Only {} of {} processes-memory processes were found in processes-api by name, "
        "startTime and pid".format(matched_count, len(raw_result["ProcessItem"]))
    )
    pretty_string = "Nothing found"
    if raw_not_matching_api:
        pretty_string = formatter(raw_not_matching_api)
    assert not raw_not_matching_api, pretty_string


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45609)
@compatibility_test(razor_util.is_x64)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(full_audit_label("TestHelper32"))
def test_processes_memory_datahandling_32bit_process(run_processes_memory_multi_script_processes):
    target_process = run_processes_memory_multi_script_processes["TestHelper32.exe"]
    failures = process_base_process_item_schema(target_process)
    assert not failures, pprint_base_formatter(failures)
    # TODO: add additional specific checks


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45610)
@compatibility_test(razor_util.is_x64)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(full_audit_label("TestHelper64"))
def test_processes_memory_datahandling_64bit_process(run_processes_memory_multi_script_processes):
    target_process = run_processes_memory_multi_script_processes["TestHelper64.exe"]
    failures = process_base_process_item_schema(target_process)
    assert not failures, pprint_base_formatter(failures)
    # TODO: add additional specific checks


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45607)
@compatibility_test(is_memory_audit_compatible)
def test_processes_memory_content_regexfield_validate(start_test_binaries, prefetch_module_audits):
    data = run_audit_job(regex_createh_job(start_test_binaries), notes="processes-memory regex CreateH collection")
    non_regex_found = False
    assert data.get("ProcessItem"), f"Audit result did not contain any process items, {pprint_base_formatter(data)}"
    for process in data["ProcessItem"]:
        if "detectedAnomaly" not in process:
            non_regex_found = True
            break
        if process["detectedAnomaly"] != "content_regex_hit":
            non_regex_found = True
            break

    assert not non_regex_found, "Returned process should have content regex hit in result."
    # TODO: find additional fields/checks to assert on/for


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(339884)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(full_audit_label("AslrTest"))
def test_processes_memory_system_state_handles_aslr(run_processes_memory_multi_script_processes):
    process = run_processes_memory_multi_script_processes["AslrTest.exe"]
    failures = process_base_process_item_schema(process)
    assert not failures, pprint_base_formatter(failures)


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(5035600)
# Test de-prioritized for feature, further automation required
@pytest.mark.defect
@compatibility_test(is_memory_audit_compatible)
def test_processes_memory_filter_validate():
    # TODO: start a process to target (or rely on an existing one like xagt)
    # TODO: run the audit against said process with a filter defined
    # TODO: make sure that the process is captured and that some details are correct.
    # TODO: determine how exhaustive we should be in the test
    # TODO: make the assertions
    pass


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45624)
# Test de-prioritized for feature, known failure: ENDPT-29802
@pytest.mark.defect
@compatibility_test(is_memory_audit_compatible)
def test_processes_memory_ports_schema_validate():
    # TODO: start a process which has a port connection made
    # TODO: collect audit with port results
    # TODO: determine level of detail for this test case
    # TODO: make the assertions
    # TODO: cleanup the process after the test case
    pass


@pytest.fixture(scope="function")
def run_collect_aslr_process_with_5k_argument(collect_test_binaries):
    aslr_path = collect_test_binaries.AslrTest
    long_args = razor_util.random_string(length=5000)
    proc_obj = start_test_binary(aslr_path, long_args)
    # The AslrTest process itself: win_razor passed the pid of the cmd.exe that
    # started it, whose command line holds the argument as well.
    test_params = {"pid": proc_obj.pid}
    try:
        data = xclient.run_job(
            "processes-memory",
            params=test_params,
            notes="processes-memory long arg process {} collection".format(aslr_path.stem),
            audit_script_name="test_processes_memory_data_arguments_greater_than_4k",
            timeout=500,
        )
        assert "ProcessItem" in data, f"Audit result did not contain any process items, {pprint_base_formatter(data)}"
        proc = data["ProcessItem"][0]
        yield proc, long_args
    finally:
        proc_obj.kill()


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45608)
@compatibility_test(is_memory_audit_compatible)
def test_processes_memory_data_arguments_greater_than_4k(run_collect_aslr_process_with_5k_argument):
    aslr_proc, argument = run_collect_aslr_process_with_5k_argument

    assert (
        argument in aslr_proc["arguments"]
    ), "Should find argument in audit output, found: {}".format(pprint_base_formatter(aslr_proc))


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(339885)
# Template additions required, no 8GB template available for test
@pytest.mark.broken
@compatibility_test(is_memory_audit_compatible)
@compatibility_test(has_8gb_ram_or_more)
def test_processes_memory_large_amounts_of_ram():
    # TODO: collect a process
    # TODO: evaluate the runtime of the audit
    # TODO: define acceptable limits/thresholds for audit runtime based on system specs/ desires
    pass


@pytest.fixture(scope="module")
def collect_laa_result_for_platform(run_processes_memory_multi_script_processes):
    proc = run_processes_memory_multi_script_processes[LAA_BINARY + ".exe"]
    # Cleanup is handled in other fixtures which started the process
    yield proc


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45611)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(LAA_FULL_AUDIT)
def test_processes_memory_large_address_aware_process(collect_laa_result_for_platform):
    laa_process = collect_laa_result_for_platform
    failures = process_base_process_item_schema(laa_process)
    assert not failures, pprint_base_formatter(failures)


@pytest.fixture(scope="module")
def collect_testhelper_with_strings_argument(start_test_binaries, prefetch_module_audits):
    # separated as the strings option has high time cost
    string_len_minimum = STRINGS_MIN_LENGTH
    data = run_audit_job(strings_testhelper32_job(start_test_binaries),
                         notes="processes-memory strings process TestHelper32.exe collection")
    assert "ProcessItem" in data, f"Audit result did not contain any process items, {pprint_base_formatter(data)}"
    proc = data["ProcessItem"][0]
    yield proc, string_len_minimum


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45637)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(STRINGS_TESTHELPER32_AUDIT)
def test_processes_memory_string_capture_single_process(collect_testhelper_with_strings_argument):
    process, _ = collect_testhelper_with_strings_argument
    missing = return_missing_fields_in_section(process, ["StringList"])
    assert not missing, pprint_missing_fields_failure(missing, process.keys())
    assert process["StringList"], "No strings found in the output, unable to compare"


@OS_COMPAT(WINDOWS)
@pytest.mark.memory
@pytest.mark.caseid(45635)
@compatibility_test(is_memory_audit_compatible)
@pytest.mark.audit_artifacts(STRINGS_TESTHELPER32_AUDIT)
def test_processes_memory_shortest_matched_string_capture_single_process(
    collect_testhelper_with_strings_argument,
):
    process, min_length = collect_testhelper_with_strings_argument
    missing = return_missing_fields_in_section(process, ["StringList"])
    assert not missing, pprint_missing_fields_failure(missing, process.keys())
    assert process["StringList"], "No strings found in the output, unable to compare"
    short_strings = [line for line in process["StringList"] if len(line) < min_length]
    assert (
        not short_strings
    ), "Shouldn't have strings shorter than minimum length, found: {}".format(
        pprint_base_formatter(short_strings)
    )