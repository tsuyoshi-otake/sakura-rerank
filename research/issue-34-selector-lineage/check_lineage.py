"""Full regression suite with an aggregate terminal result."""
import json
import unittest
from lineage_common import ROOT,save

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests',pattern='test*.py'))
    report=dict(tests=result.testsRun,successful=result.wasSuccessful(),failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped))
    save(ROOT/'full-tests.json',report);print(json.dumps(report))
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
