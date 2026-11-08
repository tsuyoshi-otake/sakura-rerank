"""Run the complete suite with a persisted terminal summary under the stage owner."""
import argparse
import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0,str(Path.cwd()))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--receipt',default='unit-tests.json')
    args=parser.parse_args()
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}\.json',args.receipt):raise ValueError('unit_receipt_name')
    suite=unittest.defaultTestLoader.discover('tests')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    summary=dict(tests=result.testsRun,successful=result.wasSuccessful(),failures=len(result.failures),
                 errors=len(result.errors),skipped=len(result.skipped))
    path=Path('data/generated/issue-33-train-change-audit-v1')/args.receipt
    with path.open('xb') as stream:stream.write((json.dumps(summary,sort_keys=True)+'\n').encode())
    raise SystemExit(0 if result.wasSuccessful() else 1)
