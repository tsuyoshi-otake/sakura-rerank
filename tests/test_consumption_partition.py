"""Independent source/input and interval oracles for a non-admitting proposal."""
from collections import Counter
import hashlib
import importlib.util
from pathlib import Path
import random
import unittest

from sakura_rerank.data.contracts import canonical_json_hash
from sakura_rerank.data.reconstruction_graph import build_source_graph

HERE = Path(__file__).resolve().parents[1]/'research/issue-35-consumption-partition'
SPEC = importlib.util.spec_from_file_location('consumption_partition_contract', HERE/'partition.py')
partition = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(partition)


def h(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def record(name, *, article=None, family=None, paragraph=None, signature=None,
           reading=None, population='evaluation'):
    row = dict(stable_id=name, population=population, source=dict(
        article_id=article or name, template_cluster_id=family,
        paragraph_hash=h(paragraph or name), sentence_hash=h(name),
        sentence_shingle_hashes=sorted(h(v) for v in (signature or [name]))))
    if population != 'source_coverage':
        row['input_hash'] = h(reading or name)
    return row


def oracle(records, assignments, aliases, exposed):
    """All raw pairs, with no typed witness graph or production union helper."""
    neighbors = {r['stable_id']:set() for r in records}
    for i, x in enumerate(records):
        for y in records[i+1:]:
            a, b = x['source'], y['source']
            left, right = set(a['sentence_shingle_hashes']), set(b['sentence_shingle_hashes'])
            source_match = (a['article_id'] == b['article_id']
                or a['template_cluster_id'] is not None and a['template_cluster_id'] == b['template_cluster_id']
                or a['paragraph_hash'] == b['paragraph_hash']
                or 5*len(left & right) >= 4*len(left | right))
            if source_match:
                neighbors[x['stable_id']].add(y['stable_id'])
                neighbors[y['stable_id']].add(x['stable_id'])
    groups = {}
    for r in records:
        seen, todo = set(), [r['stable_id']]
        while todo:
            current = todo.pop()
            if current not in seen:
                seen.add(current)
                todo.extend(neighbors[current]-seen)
        groups[r['stable_id']] = seen
    history = set(aliases) | {r['input_hash'] for r in records if r['population'] == 'historical' and 'input_hash' in r}
    old_ids = set(exposed) | {r['stable_id'] for r in records if r['population'] == 'historical'}
    target = [r for r in records if r['stable_id'] in assignments]
    expected = {}
    for r in target:
        group = groups[r['stable_id']]
        peers = [t for t in target if t['input_hash'] == r['input_hash']]
        reasons = []
        if group & old_ids: reasons.append('historical_source_component')
        if len({assignments[k] for k in group if k in assignments}) > 1: reasons.append('cross_partition_source_component')
        if r['input_hash'] in history: reasons.append('historical_input')
        if len({assignments[t['stable_id']] for t in peers}) > 1: reasons.append('cross_partition_input')
        if len(peers) > 1: reasons.append('repeated_new_input')
        expected[r['stable_id']] = (canonical_json_hash(sorted(group)), reasons)
    return expected


class ConsumptionPartitionTests(unittest.TestCase):
    def check(self, records, assignments, aliases=(), exposed=()):
        graph = build_source_graph(records)
        result = partition.audit(graph, assignments, aliases, exposed)
        observed = {r['stable_id']:(r['source_component'], r['reasons']) for r in result['rows']}
        self.assertEqual(observed, oracle(records, assignments, aliases, exposed))
        self.assertEqual(sum(result['summary']['exclusive_statuses'].values()), len(assignments))
        self.assertFalse(result['summary']['final_test'])
        self.assertFalse(result['summary']['training_admission'])
        self.assertEqual(result, partition.audit(build_source_graph(list(reversed(records))), assignments, aliases, exposed))
        return {r['stable_id']:r for r in result['rows']}

    def test_shared_input_does_not_propagate_to_other_source_units(self):
        rows = [record('old', reading='shared', population='historical'),
                record('a', article='new', reading='shared'), record('b', article='new')]
        result = self.check(rows, dict(a='test', b='test'))
        self.assertEqual(result['a']['status'], 'historical_input')
        self.assertEqual(result['b']['status'], 'metadata_only_unblocked')

    def test_all_source_relations_and_explicit_consumption_still_propagate(self):
        for relation in ('article', 'family', 'paragraph', 'signature'):
            with self.subTest(relation=relation):
                args = {relation:'same'} if relation != 'signature' else dict(signature=['same'])
                rows = [record('old', population='source_coverage', **args), record('a', **args)]
                result = self.check(rows, dict(a='calibration'), exposed={'old'})
                self.assertEqual(result['a']['status'], 'historical_source_component')

    def test_near_source_relation_is_not_weakened(self):
        rows = [record('old', population='historical', signature=list(range(10))),
                record('a', signature=list(range(1,11)))]
        self.assertEqual(self.check(rows, dict(a='test'))['a']['status'], 'historical_source_component')

    def test_cross_partition_source_quarantines_all_members(self):
        rows = [record('a', family='same'), record('b', family='same')]
        result = self.check(rows, dict(a='train', b='test'))
        self.assertTrue(all(r['status'] == 'cross_partition_source_component' for r in result.values()))

    def test_cross_partition_input_quarantines_every_occurrence_only(self):
        rows = [record('a', article='one', reading='shared'), record('b', article='two', reading='shared'),
                record('c', article='two')]
        result = self.check(rows, dict(a='train', b='calibration', c='calibration'))
        self.assertIn('cross_partition_input', result['a']['reasons'])
        self.assertIn('cross_partition_input', result['b']['reasons'])
        self.assertEqual(result['c']['status'], 'metadata_only_unblocked')

    def test_within_population_repeats_and_aliases_are_not_selected_away(self):
        rows = [record('a', reading='shared'), record('b', reading='shared'), record('c', reading='alias')]
        result = self.check(rows, dict(a='test', b='test', c='test'), aliases={h('alias')})
        self.assertEqual(result['a']['status'], 'repeated_new_input')
        self.assertEqual(result['b']['status'], 'repeated_new_input')
        self.assertEqual(result['c']['status'], 'historical_input')

    def test_roles_extent_and_unknown_exposure_fail_closed(self):
        graph = build_source_graph([record('a')])
        for assignments, aliases, exposed in [({}, [], []), ({'a':'unknown'}, [], []),
                ({'b':'test'}, [], []), ({'a':'test'}, ['invalid'], []), ({'a':'test'}, [], ['absent'])]:
            with self.subTest(assignments=assignments):
                with self.assertRaises(ValueError): partition.audit(graph, assignments, aliases, exposed)

    def test_random_small_populations_match_all_pair_oracle(self):
        rng = random.Random(35)
        for trial in range(35):
            rows = [record(str(i), article='article'+str(rng.randrange(7)), family=None,
                paragraph='p'+str(rng.randrange(11)), reading='r'+str(rng.randrange(9)),
                population='historical' if i < 2 else 'evaluation') for i in range(12)]
            roles = {r['stable_id']:rng.choice(['train','calibration','test']) for r in rows[2:]}
            with self.subTest(trial=trial): self.check(rows, roles)


def span(start, end, **extra):
    return dict(source_sha256=h('source'), preprocessing_sha256=h('projection'), start=start, end=end, **extra)


class ConsumptionSpanTests(unittest.TestCase):
    def test_every_consumption_channel_detects_reentry(self):
        used = [span(4,6,channel=c,partition='test') for c in partition.CHANNELS]
        result = partition.check_spans([span(0,5)], used)
        self.assertEqual(result['statuses'], {'quarantined_span_reentry':4})
        self.assertEqual(set(result['affected_channels']), partition.CHANNELS)
        self.assertFalse(result['coverage_certified'])
        self.assertFalse(result['admission'])

    def test_half_open_boundaries_and_merged_intervals(self):
        result = partition.check_spans([span(0,3),span(2,5),span(5,7)],
            [span(7,8,channel='input',partition='train'), span(6,8,channel='input',partition='train')])
        self.assertEqual(result['statuses'], {'no_overlap_in_supplied_spans':1, 'quarantined_span_reentry':1})

    def test_changed_preprocessing_is_pending_not_disjoint(self):
        other = span(100,101,channel='teacher',partition='test')
        other['preprocessing_sha256'] = h('other')
        result = partition.check_spans([span(0,5)], [other])
        self.assertEqual(result['statuses'], {'incomparable_preprocessing_projection':1})

    def test_missing_malformed_and_empty_footprints_do_not_certify(self):
        self.assertFalse(partition.check_spans([], [])['coverage_certified'])
        for value in [span(1,1),span(-1,2),span(True,2),dict(start=0,end=2)]:
            with self.assertRaises(ValueError): partition.check_spans([value], [])

    def test_random_intervals_match_quadratic_overlap_oracle(self):
        rng = random.Random(3501)
        for _ in range(40):
            blocked = [span(v, v+rng.randrange(1,8)) for v in (rng.randrange(50) for _ in range(20))]
            used = [span(v,v+rng.randrange(1,8),channel='left_context',partition='test') for v in (rng.randrange(50) for _ in range(20))]
            counts = Counter('quarantined_span_reentry' if any(q['start'] < u['end'] and u['start'] < q['end'] for q in blocked)
                             else 'no_overlap_in_supplied_spans' for u in used)
            self.assertEqual(partition.check_spans(blocked, used)['statuses'], dict(counts))


if __name__ == '__main__':
    unittest.main()
