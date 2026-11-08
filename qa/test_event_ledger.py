"""Event ordering, deduplication and gap detection."""
import pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from schemas import Event, EventLedger


def main():
    ledger = EventLedger()
    e2 = Event("run", 2, "2026-01-01T00:00:02", "verify", status="passed")
    e1 = Event("run", 1, "2026-01-01T00:00:01", "plan", status="info")
    assert ledger.add(e2) is True
    assert ledger.add(e1) is True
    assert ledger.add(e2) is False
    assert [event.seq for event in ledger.ordered()] == [1, 2]
    assert ledger.missing(4) == [3, 4]
    print("  PASS sequence ordering and duplicate suppression")
    print("  PASS missing-event replay detection")
    print("EVENT LEDGER TESTS PASSED")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
