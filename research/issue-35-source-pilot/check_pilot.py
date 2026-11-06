"""Bounded full test runner with an inspectable terminal count."""
import json
import unittest

from pilot35_common import ROOT, save


if __name__=='__main__':
    suite=unittest.defaultTestLoader.discover('tests')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    summary=dict(tests=result.testsRun,successful=result.wasSuccessful(),failures=len(result.failures),
                 errors=len(result.errors),skipped=len(result.skipped))
    save(ROOT/'full-unit-tests.json',summary)
    print(json.dumps(summary))
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
