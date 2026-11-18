import json
import logging
import os

from tests.test_xclient.provisioned_xclient import current_test_artifact_dir
from tests.util import hxsim_task
from tests.util.paths import AUDIT_OUTPUT_DIR, AUDIT_SCRIPTS_DIR
from tests.util.util import func_wait

# How long the restart audit's result may take to reach HXSim after the restart.
RESULT_TIMEOUT = 300


def process_details_fetch(cmd_details):
    """Return [pid, count] from the ``Select-Object ProcessId, Name, CommandLine`` table.

    The table starts with a blank line, a header and a dashes line and ends with
    blank lines; only rows whose first column is a numeric ProcessId count. pid
    is the last such row's ProcessId ('' if there is none).
    """
    pid = ''
    count = 0

    for process_details in cmd_details.splitlines():
        columns = process_details.split()
        if columns and columns[0].isdigit():
            pid = columns[0]
            count += 1

    return [pid, count]


def run_fetch_command(cmd):
    try:
        return os.popen(cmd).read()
    except Exception:
        raise Exception("Observed: Exception found while process fetch command execution, " \
                        "Expected: Process should be executed without any error")


# The restart audit restarts the agent it runs in. As an HXSim server task it
# runs in the SERVICE daemon, so the daemon gets a new PID; the audit still
# uploads its result ("SUCCESS / Agent restart initiated."), which is checked as
# win_razor's test did.
def test_pid_check(hxsim_ioc_setup):
    # os.popen runs cmd.exe, so the cmdlets must be wrapped in powershell
    cmd_1 = "powershell -NoProfile -Command \"Get-CimInstance Win32_Process -Filter \\\"Name = 'xclient.exe'\\\" | Where-Object {$_.CommandLine -like '*--mode SERVICE*'} | Select-Object ProcessId, Name, CommandLine\""
    cmd_2 = "powershell -NoProfile -Command \"Get-CimInstance Win32_Process -Filter \\\"Name = 'xclientnotif.exe'\\\" | Select-Object ProcessId, Name, CommandLine\""

    pid_before_restart, count_xclient_before_restart = process_details_fetch(run_fetch_command(cmd_1))
    count_xclientnotif_before_restart = process_details_fetch(run_fetch_command(cmd_2))[1]
    assert pid_before_restart, "Observed: no XClient SERVICE process before restart. " \
        "Expected: XClient daemon running with --mode SERVICE"

    script = (AUDIT_SCRIPTS_DIR / "test_pid_check.json").read_text(encoding="utf-8")
    task = hxsim_task.Task("test_pid_check", script).drop()
    try:
        # Wait for a new SERVICE PID instead of a fixed sleep: the daemon picks
        # the task up on its next poll and restarts within about a minute.
        restarted = func_wait(lambda: process_details_fetch(run_fetch_command(cmd_1))[0] not in ('', pid_before_restart),
                              interval=5, timeout=300)
    finally:
        task.cancel()
    pid_after_restart, count_xclient_after_restart = process_details_fetch(run_fetch_command(cmd_1))
    logging.info("XClient SERVICE pid before restart %s, after restart %s", pid_before_restart, pid_after_restart)

    assert task.wait(RESULT_TIMEOUT), \
        "Observed: the restart audit's result never reached HXSim (task {}). " \
        "Expected: restart audit should upload its result".format(task.id)
    output_dir = current_test_artifact_dir(AUDIT_OUTPUT_DIR)
    task.collect(output_dir)
    with open(output_dir / "restart.json", "r", encoding="utf-8") as file:
        data = json.load(file)
    assert data["StatusItem"][0]["Status"] == "SUCCESS", \
        "Observed: restart audit did not report SUCCESS. Expected: restart audit should succeed"
    logging.info("The restart audit output: " + str(data))

    assert restarted and (pid_before_restart != pid_after_restart), \
        "Observed: PID matches which means process didn't restarted. " \
        "Expected: PID shouldn't match"

    assert (count_xclient_before_restart == count_xclient_after_restart), \
        "Observed: Process doesn't started successfully. " \
        "Expected: Process should restart successfully"

    count_xclientnotif_after_restart = process_details_fetch(run_fetch_command(cmd_2))[1]

    assert (count_xclientnotif_before_restart == count_xclientnotif_after_restart), \
        "Observed: Process doesn't started successfully. " \
        "Expected: Process should restart successfully"
