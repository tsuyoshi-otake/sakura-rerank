"""Exact original-fragment evidence for separately planned weak-source research.

These functions verify source positions and dictionary provenance, not IME intent.
They do not admit training, choose a split, or expose right text to model inputs.
"""
from collections import defaultdict

from .contracts import canonical_json_hash, sentence_shingle_hashes, text_sha256
from .growth_corpus import SEED
from .jawiki_preprocess import _sentences


def source_metadata(corpus, source_id, paragraph, sentence, author_id=None):
    if corpus not in ('jawiki','aozora') or not isinstance(source_id,str) or not source_id.isdigit():
        raise ValueError('reconstruction_source_identity')
    if ((corpus=='aozora' and not (isinstance(author_id,str) and author_id.isdigit()))
            or (corpus=='jawiki' and author_id is not None)):
        raise ValueError('reconstruction_author_identity')
    return dict(article_id=('jawiki-page-' if corpus=='jawiki' else 'aozora-work-')+source_id,
        paragraph_hash=text_sha256(paragraph),sentence_hash=text_sha256(sentence),
        sentence_shingle_hashes=sentence_shingle_hashes(sentence),
        template_cluster_id='aozora-author-'+author_id if author_id else None)


def recover_dictionary_rows(paragraphs, targets, *, corpus, source_id, revision, readings, author_id=None):
    """Recover stable-ID preimages and full original bounded inputs; never relabel.

    The caller authenticates document bytes, its revision and dictionary index.
    Returns hash-only row evidence plus indices of consumed original paragraphs.
    """
    if not 1<=len(targets)<=200 or len({r['stable_id'] for r in targets})!=len(targets):
        raise ValueError('reconstruction_document_target_bound')
    if not isinstance(revision,str) or not revision:
        raise ValueError('reconstruction_revision_missing')
    by_hash=defaultdict(list)
    for pi,paragraph in enumerate(paragraphs):
        if not isinstance(paragraph,str) or len(paragraph)>100000:
            raise ValueError('reconstruction_paragraph_bound')
        by_hash[text_sha256(paragraph)].append((pi,paragraph))
    result=[];used=set()
    for row in sorted(targets,key=lambda r:r['stable_id']):
        if (row.get('corpus')!=corpus or row.get('source_id')!=source_id or row.get('source_revision')!=revision
                or row.get('population')!='train' or row.get('label_kind')!='source_exact_weak_supervision'
                or row.get('independent_gold_eligible') is not False or row.get('training_eligible',False) is not False
                or row.get('context_origin')!='synthetic_source_prefix_not_observed_session'
                or not 8<=len(row['left_context'])<=64 or not 1<=len(row['target'])<=64
                or not 3<=len(row['reading'])<=32 or readings.get(row['target'])!=row['reading']):
            raise ValueError('reconstruction_weak_dictionary_contract')
        matches=[]
        for pi,paragraph in by_hash.get(row['source']['paragraph_hash'],()):
            for si,(offset,sentence) in enumerate(_sentences(paragraph)):
                if text_sha256(sentence)!=row['source']['sentence_hash']:
                    continue
                if not 4<=len(sentence)<=512:
                    raise ValueError('reconstruction_sentence_bound')
                start=sentence.find(row['target'])
                while start>=0:
                    end=start+len(row['target'])
                    identity='growth-'+canonical_json_hash([SEED,corpus,source_id,revision,pi,si,start,end,row['target']])
                    if identity==row['stable_id']:
                        absolute=offset+start
                        expected=source_metadata(corpus,source_id,paragraph,sentence,author_id)
                        if (expected!=row['source'] or paragraph[max(0,absolute-64):absolute]!=row['left_context']):
                            raise ValueError('reconstruction_original_input_changed')
                        matches.append(dict(stable_id=row['stable_id'],source_row_sha256=canonical_json_hash(row),
                            corpus=corpus,source_id=source_id,source_revision=revision,paragraph_index=pi,sentence_index=si,
                            context_start=max(0,absolute-64),target_start=absolute,target_end=offset+end,
                            paragraph_sha256=text_sha256(paragraph),context_sha256=text_sha256(row['left_context']),
                            target_sha256=text_sha256(row['target']),reading_sha256=text_sha256(row['reading']),
                            input_and_label_sha256=canonical_json_hash([row['left_context'],row['reading'],row['target']]),
                            reading_provenance='frozen_unique_dictionary_not_contextual_annotation',ime_quality='unresolved',
                            training_eligible=False,independent_gold_eligible=False))
                        used.add(pi)
                    start=sentence.find(row['target'],start+1)
        if len(matches)!=1:
            raise ValueError('reconstruction_original_span_missing_or_nonunique')
        result.extend(matches)
    return result,sorted(used)


def paragraph_coverage(paragraphs, indices, *, corpus, source_id, revision, author_id=None):
    """All sentences of consumed original paragraphs, with no invented input keys."""
    result=[]
    if list(indices)!=sorted(set(indices)):
        raise ValueError('reconstruction_paragraph_indices')
    for pi in indices:
        if type(pi) is not int or not 0<=pi<len(paragraphs):
            raise ValueError('reconstruction_paragraph_index_bound')
        paragraph=paragraphs[pi]
        for si,(_,sentence) in enumerate(_sentences(paragraph)):
            result.append(dict(stable_id='reconstruction-coverage-'+canonical_json_hash([corpus,source_id,revision,pi,si]),
                population='source_coverage',source=source_metadata(corpus,source_id,paragraph,sentence,author_id)))
    return result
