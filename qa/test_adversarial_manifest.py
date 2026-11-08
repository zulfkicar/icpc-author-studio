"""Validate that every adversarial matrix row has an automation owner."""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "ADVERSARIAL-VERIFICATION.md"
MANIFEST = ROOT / "qa" / "adversarial_manifest.json"


def main():
    ids = set(re.findall(r"^\| ([A-M]\d+) \|", DOC.read_text("utf-8"), re.M))
    data = json.loads(MANIFEST.read_text("utf-8"))
    missing = sorted(ids - set(data))
    extra = sorted(set(data) - ids)
    if missing or extra:
        print("FAIL missing:", missing, "extra:", extra)
        return 1
    valid = {"automated", "partial", "manual", "external"}
    for row, item in data.items():
        if item.get("status") not in valid:
            print("FAIL status", row, item)
            return 1
        test = ROOT / item.get("test", "")
        if not test.exists():
            print("FAIL missing test file", row, test)
            return 1
    counts = {}
    for item in data.values():
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    print(f"  PASS {len(ids)} adversarial rows mapped")
    print(f"  coverage: {counts}")
    print("ADVERSARIAL MANIFEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
