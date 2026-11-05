"""Bounded unit runner; terminal output is separate for preflight and full suite."""
import argparse
import json
from pathlib import Path
import unittest


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('loss','full'))
    mode=parser.parse_args().mode
    pattern='test_balanced_reconstruction_loss.py' if mode=='loss' else 'test*.py'
    suite=unittest.defaultTestLoader.discover('tests',pattern=pattern)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    summary=dict(tests=result.testsRun,successful=result.wasSuccessful(),failures=len(result.failures),
        errors=len(result.errors),skipped=len(result.skipped))
    path=Path('data/generated/issue-33-loss-balance-v1')/(mode+'-unit-tests.json')
    with path.open('xb') as stream:stream.write((json.dumps(summary,sort_keys=True)+'\n').encode())
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
