"""Compare the test results of two run_tests.ps1 runs (e.g. the Orbit msi and the fake-MA msi).

    venv\\Scripts\\python compare_results.py logs\\<run A> logs\\<run B> [--out report.md]

Reads each run's junit.xml and compares every test's outcome (passed / failed /
skipped / error). Tests listed in MA_DIFFERENCES.md (its "| `<node id>` |" table
rows) are differences known to come from MA only: they are reported but don't
make the comparison fail. Exit code 0: same outcomes (apart from those), 1: not.
"""
import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parent
MA_DIFFERENCES = REPO / "MA_DIFFERENCES.md"


def outcomes(run_dir):
    """{node id: (outcome, message)} from <run_dir>/junit.xml."""
    root = ET.parse(str(Path(run_dir) / "junit.xml")).getroot()
    result = {}
    for case in root.iter("testcase"):
        path = case.get("classname", "").replace(".", "/")
        nodeid = "{}.py::{}".format(path, case.get("name"))
        outcome, message = "passed", ""
        for tag in ("failure", "error", "skipped"):
            element = case.find(tag)
            if element is not None:
                outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                message = (element.get("message") or "").splitlines()[0][:200] if element.get("message") else ""
                break
        result[nodeid] = (outcome, message)
    return result


def known_ma_differences():
    if not MA_DIFFERENCES.is_file():
        return set()
    return set(re.findall(r"^\|\s*`([^`]+::[^`]+)`\s*\|", MA_DIFFERENCES.read_text(encoding="utf-8"), re.M))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_a")
    parser.add_argument("run_b")
    parser.add_argument("--out", help="write the report (markdown) here too")
    args = parser.parse_args()

    a, b = outcomes(args.run_a), outcomes(args.run_b)
    known = known_ma_differences()
    lines = ["# Test results: {} vs {}".format(Path(args.run_a).name, Path(args.run_b).name), ""]
    counts = {}
    for name, res in (("A", a), ("B", b)):
        for outcome, _ in res.values():
            counts.setdefault(name, {}).setdefault(outcome, 0)
            counts[name][outcome] += 1
    lines.append("| | " + " | ".join(sorted({o for c in counts.values() for o in c})) + " |")
    lines.append("|---|" + "---|" * len({o for c in counts.values() for o in c}))
    for name, run in (("A", args.run_a), ("B", args.run_b)):
        lines.append("| {} `{}` | ".format(name, Path(run).name) + " | ".join(
            str(counts.get(name, {}).get(o, 0)) for o in sorted({o for c in counts.values() for o in c})) + " |")
    lines.append("")

    unexpected, expected = [], []
    for nodeid in sorted(set(a) | set(b)):
        ra, rb = a.get(nodeid, ("missing", "")), b.get(nodeid, ("missing", ""))
        if ra[0] == rb[0]:
            continue
        row = "| `{}` | {} | {} | {} | {} |".format(nodeid, ra[0], rb[0], ra[1].replace("|", "/"), rb[1].replace("|", "/"))
        (expected if nodeid in known else unexpected).append(row)

    header = ["| Test | A | B | A message | B message |", "|---|---|---|---|---|"]
    lines.append("## Different outcomes not explained by MA ({})".format(len(unexpected)))
    lines += (header + unexpected) if unexpected else ["None."]
    lines.append("")
    lines.append("## Different outcomes due to MA only, per MA_DIFFERENCES.md ({})".format(len(expected)))
    lines += (header + expected) if expected else ["None."]
    lines.append("")
    lines.append("RESULT: {}".format("SAME" if not unexpected else "DIFFERENT"))
    report = "\n".join(lines) + "\n"
    print(report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
    return 0 if not unexpected else 1


if __name__ == "__main__":
    sys.exit(main())
