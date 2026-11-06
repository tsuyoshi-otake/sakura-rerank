"""Recover authenticated source facts for the declared consumed population."""
from collections import Counter, defaultdict
import hashlib
import zipfile

from sakura_rerank.data.aozora_ruby_evidence import paragraphs_with_ruby, ruby_state
from sakura_rerank.data.contracts import canonical_json_hash, text_sha256

from conflict_common import BASE, ANNOTATION, CONSUMPTION, GROWTH, read, require, rows, sha
from conflict_metrics import source_observation


def provenance(cohort):
    """Authenticate all75k source metadata joins, before selecting conflicts."""
    selected = {r['encoder_input']['stable_id']: r for r in cohort}
    dictionary, annotation, receipts = {}, {}, {}
    for record in rows(BASE/'source/row-origins.jsonl.gz', 162502):
        if record['stable_id'] in selected:
            require(record['stable_id'] not in dictionary, 'duplicate_dictionary_receipt')
            dictionary[record['stable_id']] = record
    for record in rows(CONSUMPTION, 110000):
        if record['stable_id'] in selected:
            require(record['stable_id'] not in receipts, 'duplicate_annotation_receipt')
            receipts[record['stable_id']] = record
    for target in rows(ANNOTATION, 101625):
        if target['stable_id'] in selected:
            require(target['stable_id'] not in annotation, 'duplicate_annotation_target')
            target['candidate_request_id'] = 'growth-reading-'+canonical_json_hash(target['reading'])
            annotation[target['stable_id']] = target
    require(len(dictionary) == 50000 and len(annotation) == len(receipts) == 25000, 'source_join_counts')
    require(not set(dictionary) & set(annotation) and set(dictionary) | set(annotation) == set(selected), 'source_join_union')
    result = []
    for row in cohort:
        value, origin = row['encoder_input'], row['origin']
        stable = value['stable_id']
        receipt = dictionary.get(stable, receipts.get(stable))
        require(canonical_json_hash(receipt) == origin['consumption_sha256'], 'consumption_hash')
        require(receipt['training_eligible'] is False and receipt['independent_gold_eligible'] is False, 'source_admission')
        require(all(receipt[k+'_sha256'] == text_sha256(value[k]) for k in ('reading', 'target'))
                and receipt['context_sha256'] == text_sha256(value['left_context'])
                and receipt['input_and_label_sha256'] == canonical_json_hash([value['left_context'], value['reading'], value['target']]), 'source_projection_hash')
        if stable in dictionary:
            require(receipt['source_row_sha256'] == origin['original_row_sha256'] and origin['group'] == 'dictionary', 'dictionary_original')
            meta = dict(receipt)
            meta['annotation_origin'] = False
        else:
            target = annotation[stable]
            require(canonical_json_hash(target) == origin['original_row_sha256'] and origin['group'] == 'annotation', 'annotation_original')
            require(all(target[k] == value[k] for k in ('stable_id', 'corpus', 'reading', 'target', 'left_context', 'candidate_request_id')), 'annotation_input')
            require(target['population'] == 'train' and target['training_eligible'] is False and target['independent_gold_eligible'] is False, 'annotation_admission')
            require(receipt['source_revision'] == target['source_revision'] and receipt['source_line_sha256'] == target['source_line_sha256']
                    and receipt['target_start'] == target['paragraph_start'] and receipt['target_end'] == target['paragraph_end']
                    and receipt['paragraph_index'] == target['paragraph_index'], 'annotation_extent')
            meta = dict(receipt, corpus='aozora', source_id=target['source_id'],
                        paragraph_sha256=target['source']['paragraph_hash'], annotation_origin=True)
        require(meta['context_start'] == max(0, meta['target_start']-64), 'context_extent')
        result.append(meta)
    return result


def read_archive(receipt, entry):
    path = GROWTH/'aozora-download'/(receipt['work_id']+'.json')
    require(sha(path) == receipt['acquisition_receipt_sha256'], 'acquisition_receipt')
    download = read(path)
    require(download['status'] == 'downloaded' and entry['partition'] == 'train'
            and all(download[k] == value for k, value in entry.items()), 'archive_selection')
    archive_path = path.with_suffix('.zip')
    require(sha(archive_path) == receipt['archive_sha256'], 'source_archive')
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        require(len(entries) == 1 and not entries[0].is_dir() and 0 < entries[0].file_size <= 32*1024*1024, 'archive_bound')
        raw = archive.read(entries[0])
    require(len(raw) == receipt['decoded_bytes'] and hashlib.sha256(raw).hexdigest() == receipt['decoded_sha256'], 'decoded_source')
    return raw


def recover(cohort, origins, positions, registry, selection):
    by_wiki, by_work = defaultdict(list), defaultdict(list)
    for i in positions:
        record = origins[i]
        if record['corpus'] == 'jawiki':
            by_wiki[(record['source_id'], record['paragraph_index'])].append(i)
        else:
            require(record['corpus'] == 'aozora', 'source_corpus')
            by_work[record['source_id']].append(i)
    observations = {}

    def observe(i, paragraph, state, source_line=None):
        meta, row = origins[i], cohort[i]['encoder_input']
        require(text_sha256(paragraph) == meta['paragraph_sha256'], 'paragraph_hash')
        if source_line is not None and meta['annotation_origin']:
            require(source_line == meta['source_line_sha256'], 'source_line_hash')
        item = source_observation(paragraph, meta['target_start'], meta['target_end'], row['target'], row['left_context'])
        observations[i] = dict(item, index=i, reading_evidence=state,
                              provenance='original_ruby' if meta['annotation_origin'] else 'frozen_unique_dictionary',
                              source_revision_sha256=canonical_json_hash(meta['source_revision']))

    found = set()
    for paragraph in rows(BASE/'source/wikipedia-paragraphs.jsonl.gz', 62404):
        key = (paragraph['source_id'], paragraph['paragraph_index'])
        if key not in by_wiki:
            continue
        require(key not in found, 'duplicate_wikipedia_paragraph')
        found.add(key)
        for i in by_wiki[key]:
            require(paragraph['source_revision'] == origins[i]['source_revision'], 'wikipedia_revision')
            observe(i, paragraph['text'], 'wikipedia_no_original_reading_annotation')
    require(found == set(by_wiki), 'wikipedia_join_complete')
    receipts = {r['work_id']: r for r in registry}
    opened = []
    for work in sorted(by_work):
        require(work in receipts, 'source_work_missing')
        receipt = receipts[work]
        raw = read_archive(receipt, selection[work])
        paragraphs, _ = paragraphs_with_ruby(raw)
        require(len(paragraphs) == receipt['paragraph_count'], 'original_paragraph_count')
        for i in by_work[work]:
            meta, row = origins[i], cohort[i]['encoder_input']
            require(meta['source_revision'] == receipt['decoded_sha256'], 'source_revision')
            paragraph = paragraphs[meta['paragraph_index']]
            state, _ = ruby_state(paragraph, meta['target_start'], meta['target_end'], row['reading'])
            observe(i, paragraph['text'], state, paragraph['source_line_sha256'])
        opened.append(dict(work_key=canonical_json_hash(work), archive_sha256=receipt['archive_sha256'],
                           decoded_sha256=receipt['decoded_sha256'], source_rows=len(by_work[work])))
    require(set(observations) == set(positions), 'source_observation_denominator')
    return observations, opened, summarize(observations, origins, positions)


def summarize(observations, origins, positions):
    chosen = [observations[i] for i in positions]
    return dict(rows=len(chosen), exact_source_spans=len(chosen),
        wikipedia_paragraphs=len({(origins[i]['source_id'],origins[i]['paragraph_index']) for i in positions if origins[i]['corpus']=='jawiki'}),
        aozora_works=len({origins[i]['source_id'] for i in positions if origins[i]['corpus']=='aozora'}),
        source_terminals=dict(Counter(o['reading_evidence'] for o in chosen)),
        boundary_classes=dict(Counter('/'.join(o['classes'][k] for k in ('left','first','last','right')) for o in chosen)),
        ime_input_units_unresolved=len(chosen), semantic_reviews=0, human_reviews=0)
