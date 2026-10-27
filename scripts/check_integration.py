#!/usr/bin/env python3
"""Run the integration adapter checks and optionally save inspectable JSON evidence."""
import argparse
import io
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests/integration"), pattern="test_*.py")
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    report = {
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "scope": "HTTP adapter with synthetic principals; not real provider or full customer acceptance",
        "success": result.wasSuccessful(), "testsRun": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
        "paidSubmissionAttempted": False, "realAuthorizationAttempted": False,
        "output": stream.getvalue(),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(stream.getvalue(), end="")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
