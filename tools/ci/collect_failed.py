"""Copy what a CI run needs for investigating its failures into one folder (for upload).

    python tools\\ci\\collect_failed.py <run log dir> <out dir> [--build-logs <dir>]

Copied: the run's own logs (run.log, install.log, pytest.log, junit.xml, memory.csv, ...), the
newest fake-MA build log folder, and from results\\ (the per-test audit outputs,
results\\<test script>\\<test name>\\: audit script, outputs and, for a failed test,
xclient_config.txt = XClient's config with keys redacted, written by conftest.py) only the folders of the tests that failed or errored in
junit.xml, plus results\\hxsim\\ (HXSim server log, IOC feed) without the stub policy, which holds
the agent key. Prints the number of failed tests.
"""
import argparse
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.test_xclient.provisioned_xclient import artifact_dir_for  # noqa: E402


def failed_node_ids(junit, results):
    """pytest node ids (``<script>.py::<test>``) of the failed / errored test cases."""
    ids = []
    for case in ET.parse(str(junit)).getroot().iter("testcase"):
        if case.find("failure") is None and case.find("error") is None:
            continue
        # classname is the dotted module path, then any test classes: tests.test_audits.test_x[.Class]
        parts = case.get("classname", "").split(".")
        module = next((i for i in range(len(parts) - 1, -1, -1) if (results / parts[i]).is_dir()), len(parts) - 1)
        test = "::".join(parts[module + 1:] + [case.get("name", "")])
        ids.append("{}.py::{}".format(parts[module], test))
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--build-logs", type=Path)
    args = ap.parse_args()
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    failed = []
    if args.run_dir.is_dir():
        for item in args.run_dir.iterdir():
            if item.is_file():
                shutil.copy2(str(item), str(out / item.name))
        results = args.run_dir / "results"
        junit = args.run_dir / "junit.xml"
        if junit.is_file():
            failed = failed_node_ids(junit, results)
        for node_id in failed:
            src = artifact_dir_for(results, node_id)
            if src.is_dir():
                shutil.copytree(str(src), str(out / "results" / src.relative_to(results)))
            print("failed: {}{}".format(node_id, "" if src.is_dir() else " (no results folder)"))
        hxsim = results / "hxsim"
        if failed and hxsim.is_dir():
            shutil.copytree(str(hxsim), str(out / "results" / "hxsim"),
                            ignore=shutil.ignore_patterns("ma_stub_policy.xml"))

    if args.build_logs and args.build_logs.is_dir():
        newest = sorted((d for d in args.build_logs.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime)
        if newest:
            shutil.copytree(str(newest[-1]), str(out / "fakema-build" / newest[-1].name))
    print("{} failed test(s)".format(len(failed)))


if __name__ == "__main__":
    main()
