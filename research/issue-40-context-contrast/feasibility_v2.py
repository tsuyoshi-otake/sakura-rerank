"""Explicit original-lemma proxy; preserve the representative-field failure."""
from collections import Counter
import json
from pathlib import Path

from sakura_rerank.data.context_contrasts import extract_pool,select_contrasts
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once
from feasibility import boundary

ROOT=Path("data/generated/issue-40-contrast-feasibility-v2")


def run():
    boundary.authenticate_population()
    _,selection=boundary.pilot.authenticate()
    pool,counts=[],Counter()
    for doc in selection["documents"]:
        raw=(boundary.pilot.ROOT/"source"/(doc["document_id"]+".knp")).read_bytes()
        rows,statuses=extract_pool(doc["document_id"],raw,lexical_basis="original_lemma")
        pool.extend(rows);counts.update(statuses)
    selected,groups=select_contrasts(pool)
    if select_contrasts(list(reversed(pool)))!=(selected,groups):raise ValueError("selection_order_dependency")
    ROOT.mkdir(exist_ok=False)
    for name,rows in (("pool",pool),("selected",selected)):
        write_once(ROOT/(name+".jsonl"),boundary.jsonl(rows))
    result=dict(kind="original_lemma_context_contrast_feasibility",documents=250,
        prior_zero_eligible_result_preserved=True,previously_exposed_sources=True,
        lexical_basis="Original column 3 lemma only; do not infer absent representative forms or semantic senses",
        extraction_statuses=dict(counts),contrast_counts=groups,
        source_selection_sha256=boundary.sha(boundary.pilot.ROOT/"selection.json"),
        pool_sha256=boundary.sha(ROOT/"pool.jsonl"),selected_sha256=boundary.sha(ROOT/"selected.jsonl"),
        extractor_sha256=boundary.sha("src/sakura_rerank/data/context_contrasts.py"),script_sha256=boundary.sha(__file__),
        model_fits=0,model_predictions=0,gold_certified=False,independent_test=False,
        source_history_isolation_executed=False,input_permutation_invariant=True,
        caveat="Different original lemmas can still represent spelling variants. These are source-form contrasts with unresolved semantics, not certified homophone-intent labels.")
    for path in (ROOT/"report.json",Path("reports/issue-40-contrast-feasibility-v2.json")):
        write_once(path,canonical_json_bytes(result)+b"\n")
    return result


if __name__=="__main__":
    r=run();print(json.dumps({k:r[k] for k in ("documents","extraction_statuses","contrast_counts")}))
