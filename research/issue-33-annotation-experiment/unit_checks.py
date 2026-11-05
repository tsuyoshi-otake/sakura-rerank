"""Run the complete suite with a persisted terminal summary under the stage owner."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path.cwd()))


if __name__=='__main__':
    suite=unittest.defaultTestLoader.discover('tests')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    summary=dict(tests=result.testsRun,successful=result.wasSuccessful(),failures=len(result.failures),
                 errors=len(result.errors),skipped=len(result.skipped))
    path=Path('data/generated/issue-33-annotation-experiment-v1/unit-tests.json')
    with path.open('xb') as stream:stream.write((json.dumps(summary,sort_keys=True)+'\n').encode())
    raise SystemExit(0 if result.wasSuccessful() else 1)
