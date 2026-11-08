"""Bounded test collection with durable aggregate terminal counts."""
import argparse
import json
import unittest

from model35_common import ROOT, save


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--result', required=True)
    parser.add_argument('--pattern', default='test*.py')
    args = parser.parse_args()
    if '/' in args.result or '\\' in args.result or not args.result.endswith('.json'):
        raise ValueError('consumption_test_result_path')
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover('tests', pattern=args.pattern))
    report = dict(tests=result.testsRun, successful=result.wasSuccessful(), failures=len(result.failures),
                  errors=len(result.errors), skipped=len(result.skipped))
    save(ROOT/args.result, report)
    print(json.dumps(report))
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
