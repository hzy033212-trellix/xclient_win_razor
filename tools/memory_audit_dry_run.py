"""Dry run the Windows memory audit tests against recorded XClient outputs.

Usage:
    venv\\Scripts\\python.exe tools\\memory_audit_dry_run.py <audit_outputs dir>
        [--host-razor <dir>] [--host-user <DOMAIN\\user>] [--host-sid <S-1-...>]
        [--extra-outputs <dir>]

<audit_outputs dir> is what win_xclient_memory_audit-main\\run_and_evaluate_all.py writes
(run_all.log, summary.json, _shared/<audit>/...). See MEMORY_AUDIT_TESTS.md. From win_razor,
adapted to this repo's fixtures (prefetch_module_audits is passed as None).

No XClient audit is run: each module's ``xclient.run_job`` is replaced by a stand-in that
renders the repo's audit script (tests/audit_scripts/<name>.json, with the same placeholder
substitution as the real run_job), checks it matches the script that produced the recorded
output, and returns that output. Live helper processes are stood in for by objects carrying
the recording host's values: pids from run_all.log, and the helpers' folder, user and user
SID, which are read from the recorded CreateH audit unless --host-razor/--host-user/--host-sid
are given. Start times and parent pids are never recorded outside the audit, so they are
always taken from it (checks on those fields only compare the audit with itself).

--extra-outputs adds the 3 tests that xclient_dryrun\\run_three.py runs (its outputs folder:
summary.json, <audit>/...). Those tests read only that folder's recordings.
"""
import argparse
import ast
import calendar
import datetime
import json
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("outputs", type=Path, help="audit_outputs folder written by run_and_evaluate_all.py")
parser.add_argument("--host-razor", help="folder the helpers ran from on the recording host")
parser.add_argument("--host-user", help="DOMAIN\\user the helpers ran as on the recording host")
parser.add_argument("--host-sid", help="SID of that user (whoami /user)")
parser.add_argument("--extra-outputs", type=Path, help="outputs folder written by xclient_dryrun\\run_three.py")
ARGS = parser.parse_args()
OUTPUTS = ARGS.outputs
SHARED = OUTPUTS / "_shared"

from addict import Dict  # noqa: E402
from tests.util import paths, memory_utils  # noqa: E402
from tests.util import util as razor_util  # noqa: E402
from tests.util.util import sha1_hashfile, sha256_hashfile  # noqa: E402
from tests.test_audits import (  # noqa: E402
    test_drivers_modulelist as t_mod,
    test_drivers_signature as t_sig,
    test_processes_api as t_api,
    test_processes_handle as t_handle,
    test_processes_memory as t_mem,
    test_processes_memoryacquire as t_acq,
)
from tests.test_xclient.provisioned_xclient import Singleton_XClient  # noqa: E402

LOCAL_RAZOR = str(paths.RAZOR_PUBLIC)

helpers_line = next(l for l in (OUTPUTS / "run_all.log").read_text().splitlines() if l.startswith("helpers:"))
HELPER_PIDS = ast.literal_eval(helpers_line.split(":", 1)[1].strip())
PID_TO_STEM = {pid: stem for stem, pid in HELPER_PIDS.items()}

# audit_script_name -> recorded audit label under _shared/ (None: chosen by the pid param)
SCRIPT_TO_LABEL = {
    "test_process_memory_single_process_result_validate": None,
    "test_process_memory_single_process_schema_validate": "processes-memory_name_CreateH",
    "test_processes_memory_all_processes_no_options_schema_validate": "processes-memory_all",
    "test_processes_api_memory_compare_base_no_options": "processes-api_all",
    "test_processes_memory_compare_processes_api_single_process": "processes-api_CreateH_handles_sections",
    "test_processes_memory_content_regexfield_validate": "processes-memory_regex_CreateH",
    "test_processes_memory_data_arguments_greater_than_4k": "processes-memory_AslrTest_5k_arg",
    "test_processes_memory_string_capture_single_process": "processes-memory_strings_TestHelper32",
    "test_audit_drivers_modulelist": "drivers-modulelist",
    "test_audit_drivers_signature": "drivers-signature",
    "test_audit_processes_handle": "w32processes-handle",
    "test_audit_processes_api": "processes-api_all",
    "test_audit_processes_memoryacquire_completes": "processes-memoryacquire",
}
# root: folder holding the recorded audits the current test reads
CURRENT_TEST = {"name": "", "root": SHARED}
SCRIPT_MISMATCHES = []


def load_output(label, root=None):
    folder = (root or CURRENT_TEST["root"]) / label / "audit_output"
    for audit in json.loads((folder / "manifest.json").read_text())["audits"]:
        for r in audit["results"]:
            if r["type"] == "application/json":
                return json.loads((folder / r["payload"]).read_text(encoding="utf-8"))
    raise AssertionError(f"no json payload in {folder}")


def recorded_createh():
    try:
        return load_output("processes-memory_full_CreateH")["ProcessItem"][0]
    except (KeyError, IndexError):
        sys.exit("processes-memory_full_CreateH has no ProcessItem: the recording host's Windows "
                 "build is not supported by the memory audit (see MEMORY_AUDIT_OS_SUPPORT.md)")


REMOTE_RAZOR = ARGS.host_razor or recorded_createh()["path"]
REMOTE_USER = ARGS.host_user or recorded_createh()["Username"]
REMOTE_SID = ARGS.host_sid or recorded_createh()["SecurityID"]
print(f"recording host: helpers in {REMOTE_RAZOR}, user {REMOTE_USER} ({REMOTE_SID}); "
      f"local helpers in {LOCAL_RAZOR}\n")


class FakeXClient:
    def run_job(self, audit_name="eventbuffer", params={}, notes="", output_file_name="",
                audit_script_name="", timeout=None, artifact_label=""):
        if not audit_script_name:
            audit_script_name = CURRENT_TEST["name"]
        source_script = paths.AUDIT_SCRIPTS_DIR / "{}.json".format(audit_script_name)
        # same substitution as Singleton_XClient.run_job
        script = source_script.read_text(encoding="utf-8").replace(
            "{RAZOR_PUBLIC}", json.dumps(str(paths.RAZOR_PUBLIC))[1:-1])
        for param_name, param_value in params.items():
            script = script.replace('"{%s}"' % param_name, json.dumps(param_value))
        rendered = json.loads(script)["commands"][0]
        assert rendered["name"] == audit_name, (rendered["name"], audit_name)
        label = SCRIPT_TO_LABEL[audit_script_name]
        if label is None:
            label = "processes-memory_full_" + PID_TO_STEM[params["pid"]]
        recorded = json.loads((CURRENT_TEST["root"] / label / "audit_script.json").read_text())["commands"][0]
        if rendered.get("parameters", []) != recorded["parameters"] or rendered["name"] != recorded["name"]:
            SCRIPT_MISMATCHES.append((CURRENT_TEST["name"], audit_script_name, rendered, recorded))
        # tests with binary payloads read the output folder themselves
        Singleton_XClient.last_audit = {"output_dir": str(CURRENT_TEST["root"] / label / "audit_output")}
        if audit_name == "processes-memoryacquire":
            return {}
        return load_output(label)


class FakeProcess:
    """psutil.Process stand-in with the remote host's values for a started helper."""

    def __init__(self, stem, ppid, start_time):
        self.pid = HELPER_PIDS[stem]
        self._name = stem + ".exe"
        self._exe = REMOTE_RAZOR + "\\" + self._name
        self._ppid = ppid
        self._start_time = start_time

    def create_time(self):
        return self._start_time

    def name(self):
        return self._name

    def exe(self):
        return self._exe

    def ppid(self):
        return self._ppid

    def username(self):
        return REMOTE_USER

    def cmdline(self):
        return [self._exe]


def remote_ppid(stem):
    # The parent (the remote runner's python) pid is not recorded anywhere but in the audit.
    data = load_output("processes-memory_full_" + stem)
    return data["ProcessItem"][0]["parentpid"]


def remote_start_time(stem):
    # Neither is the helper's start time; psutil's create_time() is seconds since the epoch.
    start = load_output("processes-memory_full_" + stem)["ProcessItem"][0]["startTime"]
    return calendar.timegm(datetime.datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").timetuple())


def to_local(path):
    """Helper binaries live in the remote RAZOR_PUBLIC; read the identical local copies instead."""
    s = str(path)
    if s.lower().startswith(REMOTE_RAZOR.lower()):
        return Path(LOCAL_RAZOR + s[len(REMOTE_RAZOR):])
    return Path(s)


_imports, _exports = memory_utils.collect_imports_from_pefile, memory_utils.collect_exports_from_pefile
memory_utils.collect_imports_from_pefile = lambda p: _imports(to_local(p))
memory_utils.collect_exports_from_pefile = lambda p: _exports(to_local(p))

for module in (t_mod, t_sig, t_api, t_handle, t_mem, t_acq):
    module.xclient = FakeXClient()
# The tests compare SecurityID with the user running them; here that is the recording host's user
t_mem.current_user_sid = lambda: REMOTE_SID


def unwrap(fixture):
    if hasattr(fixture, "_get_wrapped_function"):  # pytest >= 8.4
        return fixture._get_wrapped_function()
    return fixture.__pytest_wrapped__.obj


def fixture_value(fixture, *args, **kwargs):
    result = unwrap(fixture)(*args, **kwargs)
    return next(result) if hasattr(result, "__next__") else result


def build():
    stems = list(HELPER_PIDS)
    procs = Dict({stem: FakeProcess(stem, remote_ppid(stem), remote_start_time(stem)) for stem in stems})
    binaries = Dict({stem: Path(LOCAL_RAZOR) / f"{stem}.exe" for stem in stems})
    cache = {}

    def once(key, func):
        if key not in cache:
            cache[key] = func()
        return cache[key]

    # The second argument of the processes-memory fixtures is prefetch_module_audits (None:
    # nothing is prefetched; each fixture's run_job renders the same script).
    multi = lambda: once("multi", lambda: fixture_value(t_mem.run_processes_memory_multi_script_processes, procs, None))
    by_name = lambda: once("name", lambda: fixture_value(t_mem.run_audit_with_process_name_option, procs, None))
    all_mem = lambda: once("all_mem", lambda: fixture_value(t_mem.run_audit_all_processes_no_options, procs, None))
    all_api = lambda: once("all_api", lambda: fixture_value(t_mem.run_api_audit_all_processes_no_options, procs, None))
    api_single = lambda: once("api_single", lambda: fixture_value(
        t_mem.run_api_audit_with_options_enabled_single_process, procs, None))
    dedupe = lambda: fixture_value(t_mem.handle_de_duper, multi())
    laa = lambda: fixture_value(t_mem.collect_laa_result_for_platform, multi())
    strings = lambda: once("strings", lambda: fixture_value(t_mem.collect_testhelper_with_strings_argument, procs, None))
    mod = lambda: once("mod", lambda: fixture_value(t_mod.run_driver_module_audit))
    sig = lambda: once("sig", lambda: fixture_value(t_sig.run_audit_with_options_enabled))
    acpi = lambda: fixture_value(t_sig.collect_acpi_driver_from_audit_results, sig())
    volume = lambda: fixture_value(t_sig.collect_volume_driver_from_audit_results, sig())
    handle = lambda: once("handle", lambda: fixture_value(t_handle.collect_process_handle_audit, procs.CreateH))

    def five_k():
        # The fixture starts AslrTest with a random 5000-char argument; replay the remote run's
        # argument and pid instead of starting a local process.
        data = load_output("processes-memory_AslrTest_5k_arg")
        remote_args = data["ProcessItem"][0]["arguments"].split(" ", 1)[1]
        recorded_pid = json.loads((SHARED / "processes-memory_AslrTest_5k_arg" / "audit_script.json")
                                  .read_text())["commands"][0]["parameters"][0]["value"]
        killed = []
        saved = (t_mem.razor_util.random_string, t_mem.start_test_binary)
        t_mem.razor_util.random_string = lambda length: remote_args
        t_mem.start_test_binary = lambda path, arguments="": SimpleNamespace(
            pid=recorded_pid, kill=lambda: killed.append(recorded_pid))
        try:
            gen = unwrap(t_mem.run_collect_aslr_process_with_5k_argument)(binaries)
            value = next(gen)
        finally:
            t_mem.razor_util.random_string, t_mem.start_test_binary = saved
        return value

    def node_process():
        # test_processes_api's node_process fixture starts node; use the node.exe in the recording.
        node = next(p for p in load_output("processes-api_all")["ProcessItem"]
                    if p.get("name", "").lower() == "node.exe")
        return SimpleNamespace(pid=node["pid"])

    def param(fixture, key, func):
        return lambda: unwrap(fixture)(SimpleNamespace(param=(key, func)), *{
            t_mem.hash_validator: lambda: (binaries, procs, multi()),
            t_sig.hash_validator: lambda: (acpi(),),
        }[fixture]())

    def impexp(key, func):
        return lambda: unwrap(t_mem.import_export_validator)(SimpleNamespace(param=(key, func, "")), multi())

    return {
        "test_audit_drivers_modulelist": lambda: t_mod.test_audit_drivers_modulelist(mod()),
        "test_drive_module_schema_validate": lambda: t_mod.test_drive_module_schema_validate(mod()),
        "test_audit_drivers_signature": lambda: t_sig.test_audit_drivers_signature(sig()),
        "test_driver_sig_device_info_validate_single_item":
            lambda: t_sig.test_driver_sig_device_info_validate_single_item(volume()),
        "test_driver_sig_digital_sig_validate_single_item":
            lambda: t_sig.test_driver_sig_digital_sig_validate_single_item(acpi()),
        "test_driver_sig_hash_validate_single_item[Md5sum]": param(t_sig.hash_validator, "Md5sum", razor_util.md5_hash_file),
        "test_driver_sig_hash_validate_single_item[Sha1sum]": param(t_sig.hash_validator, "Sha1sum", sha1_hashfile),
        "test_driver_sig_hash_validate_single_item[Sha256sum]": param(t_sig.hash_validator, "Sha256sum", sha256_hashfile),
        "test_driver_sig_imports_validate_pe_file_single":
            lambda: t_sig.test_driver_sig_imports_validate_pe_file_single(acpi()),
        "test_driver_sig_imports_validate_single_schema":
            lambda: t_sig.test_driver_sig_imports_validate_single_schema(acpi()),
        "test_audit_processes_api": lambda: t_api.test_audit_processes_api(node_process()),
        "test_audit_processes_handle": lambda: t_handle.test_audit_processes_handle(handle()),
        "test_processes_handle_check_all_parameters":
            lambda: t_handle.test_processes_handle_check_all_parameters(handle(), procs.CreateH),
        "test_process_memory_export_pe_result_validate":
            lambda: t_mem.test_process_memory_export_pe_result_validate(multi()),
        "test_process_memory_import_export_schema_validate[Exports]":
            impexp("Exports", t_mem.process_exports_output_schema),
        "test_process_memory_import_export_schema_validate[ImportedModules]":
            impexp("ImportedModules", t_mem.process_imported_modules_output_schema),
        "test_process_memory_import_pe_result_validate":
            lambda: t_mem.test_process_memory_import_pe_result_validate(multi()),
        "test_process_memory_single_process_digital_signature_result_validate":
            lambda: t_mem.test_process_memory_single_process_digital_signature_result_validate(multi()),
        "test_process_memory_single_process_handles_result_validate":
            lambda: t_mem.test_process_memory_single_process_handles_result_validate(dedupe()),
        "test_process_memory_single_process_handles_schema_validate":
            lambda: t_mem.test_process_memory_single_process_handles_schema_validate(dedupe()),
        "test_process_memory_single_process_hash_result_validate[Md5sum]":
            param(t_mem.hash_validator, "Md5sum", razor_util.md5_hash_file),
        "test_process_memory_single_process_hash_result_validate[Sha1sum]":
            param(t_mem.hash_validator, "Sha1sum", sha1_hashfile),
        "test_process_memory_single_process_hash_result_validate[Sha256sum]":
            param(t_mem.hash_validator, "Sha256sum", sha256_hashfile),
        "test_process_memory_single_process_memd5_hash_result_validate":
            lambda: t_mem.test_process_memory_single_process_memd5_hash_result_validate(multi()),
        "test_process_memory_single_process_result_validate":
            lambda: t_mem.test_process_memory_single_process_result_validate(procs, multi()),
        "test_process_memory_single_process_schema_validate":
            lambda: t_mem.test_process_memory_single_process_schema_validate(by_name()),
        "test_process_memory_single_process_sections_schema_validate":
            lambda: t_mem.test_process_memory_single_process_sections_schema_validate(multi()),
        "test_processes_api_memory_compare_base_no_options":
            lambda: t_mem.test_processes_api_memory_compare_base_no_options(all_mem(), all_api()),
        "test_processes_memory_compare_processes_api_single_process":
            lambda: t_mem.test_processes_memory_compare_processes_api_single_process(api_single(), multi()),
        "test_processes_memory_content_regexfield_validate":
            lambda: t_mem.test_processes_memory_content_regexfield_validate(procs, None),
        "test_processes_memory_data_arguments_greater_than_4k":
            lambda: t_mem.test_processes_memory_data_arguments_greater_than_4k(five_k()),
        "test_processes_memory_datahandling_32bit_process":
            lambda: t_mem.test_processes_memory_datahandling_32bit_process(multi()),
        "test_processes_memory_datahandling_64bit_process":
            lambda: t_mem.test_processes_memory_datahandling_64bit_process(multi()),
        "test_processes_memory_large_address_aware_process":
            lambda: t_mem.test_processes_memory_large_address_aware_process(laa()),
        "test_processes_memory_shortest_matched_string_capture_single_process":
            lambda: t_mem.test_processes_memory_shortest_matched_string_capture_single_process(strings()),
        "test_processes_memory_single_process_pid_option_result_validate":
            lambda: t_mem.test_processes_memory_single_process_pid_option_result_validate(procs, multi()),
        "test_processes_memory_string_capture_single_process":
            lambda: t_mem.test_processes_memory_string_capture_single_process(strings()),
        "test_processes_memory_system_state_handles_aslr":
            lambda: t_mem.test_processes_memory_system_state_handles_aslr(multi()),
    }


def build_extra():
    """Tests recorded by xclient_dryrun\\run_three.py (not cached with build()'s fixtures)."""
    sig = lambda: fixture_value(t_sig.run_audit_with_options_enabled)
    return {
        "test_driver_sig_exports_validate_single_schema": lambda: t_sig.test_driver_sig_exports_validate_single_schema(
            fixture_value(t_sig.collect_acpi_driver_from_audit_results, sig())),
        "test_processes_memory_all_processes_no_options_schema_validate":
            lambda: t_mem.test_processes_memory_all_processes_no_options_schema_validate(
                fixture_value(t_mem.run_audit_all_processes_no_options, None, None)),
        "test_audit_processes_memoryacquire_completes": t_acq.test_audit_processes_memoryacquire_completes,
    }


def main():
    expected = json.loads((OUTPUTS / "summary.json").read_text())
    tests = build()
    assert set(tests) == set(expected), set(tests) ^ set(expected)
    roots = dict.fromkeys(expected, SHARED)
    if ARGS.extra_outputs:
        extra_expected = json.loads((ARGS.extra_outputs / "summary.json").read_text())
        extra = build_extra()
        assert set(extra) == set(extra_expected), set(extra) ^ set(extra_expected)
        tests.update(extra)
        roots.update(dict.fromkeys(extra_expected, ARGS.extra_outputs))
    results = {}
    for test_id in roots:
        CURRENT_TEST["name"] = test_id.split("[")[0]
        CURRENT_TEST["root"] = roots[test_id]
        try:
            tests[test_id]()
            status, detail = "PASS", ""
        except AssertionError as exc:
            status, detail = "FAIL", str(exc)
        except Exception:
            status, detail = "ERROR", traceback.format_exc()
        results[test_id] = status
        print(f"{status:5} {test_id}" + (f"\n      {detail[:1500]}" if detail else ""), flush=True)
    print("\nscript mismatches vs. recorded audits:", len(SCRIPT_MISMATCHES))
    for m in SCRIPT_MISMATCHES:
        print("  ", m)
    counts = {s: list(results.values()).count(s) for s in ("PASS", "FAIL", "ERROR")}
    print("SUMMARY", counts)


if __name__ == "__main__":
    main()
