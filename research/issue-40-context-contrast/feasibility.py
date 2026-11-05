"""Use already exposed pilot documents to test contrast extraction, not models."""
from collections import Counter
import importlib.util
import json
from pathlib import Path

from sakura_rerank.data.context_contrasts import extract_pool, select_contrasts
from sakura_rerank.data.contracts import canonical_json_bytes
from sakura_rerank.data.kwdlc_probe import write_once

spec=importlib.util.spec_from_file_location("boundary_history_contract","research/issue-31-input-boundary/common.py")
boundary=importlib.util.module_from_spec(spec)
spec.loader.exec_module(boundary)
ROOT=Path("data/generated/issue-40-contrast-feasibility-v1")


def run():
    boundary.authenticate_population()
    _,selection=boundary.pilot.authenticate()
    pool,counts=[],Counter()
    for doc in selection["documents"]:
        raw=(boundary.pilot.ROOT/"source"/(doc["document_id"]+".knp")).read_bytes()
        rows,statuses=extract_pool(doc["document_id"],raw)
        pool.extend(rows);counts.update(statuses)
    selected,groups=select_contrasts(pool)
    if select_contrasts(list(reversed(pool)))!=(selected,groups):
        raise ValueError("selection_order_dependency")
    ROOT.mkdir(exist_ok=False)
    for name,rows in (("pool",pool),("selected",selected)):
        write_once(ROOT/(name+".jsonl"),boundary.jsonl(rows))
    result=dict(kind="context_contrast_extraction_feasibility",documents=250,
                source_selection_sha256=boundary.sha(boundary.pilot.ROOT/"selection.json"),
                previously_exposed_research_sources=True,model_predictions=0,model_fits=0,
                source_history_isolation_executed=False,independent_test=False,gold_certified=False,
                extraction_statuses=dict(counts),contrast_counts=groups,
                pool_sha256=boundary.sha(ROOT/"pool.jsonl"),selected_sha256=boundary.sha(ROOT/"selected.jsonl"),
                extractor_sha256=boundary.sha("src/sakura_rerank/data/context_contrasts.py"),
                script_sha256=boundary.sha(__file__),input_permutation_invariant=True,
                caveat="Different representative annotations are a lexical-contrast proxy, not certified semantic labels. These exposed documents cannot become a new independent Test.")
    for path in (ROOT/"report.json",Path("reports/issue-40-contrast-feasibility-v1.json")):
        write_once(path,canonical_json_bytes(result)+b"\n")
    return result


if __name__=="__main__":
    result=run()
    print(json.dumps({k:result[k] for k in ("documents","extraction_statuses","contrast_counts")}))
