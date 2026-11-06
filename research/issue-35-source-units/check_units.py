"""Bounded full unit suite with a separate immutable terminal count."""
import json
import unittest

from unit35_common import ROOT,save


if __name__=='__main__':
    suite=unittest.defaultTestLoader.discover('tests')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report=dict(tests=result.testsRun,successful=result.wasSuccessful(),failures=len(result.failures),
                errors=len(result.errors),skipped=len(result.skipped))
    save(ROOT/'full-unit-tests.json',report)
    print(json.dumps(report))
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
