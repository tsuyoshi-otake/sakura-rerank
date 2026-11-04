"""Fixed KWDLC training-only feasibility probe; not a Gold or training producer.

Transport is separate. Authenticate Git blobs supplied by the connected GitHub
reader, select before document access, and preserve one outcome per document.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path

from .contracts import canonical_json_bytes, canonical_json_hash

PLAN_SHA256 = "8b54b88c5e450ded7b9461f7815cf03c36ce416f3a10d27d83a59eb291c078ef"
COMMIT = "c6ae49d29eca4e1134c6676d682adf5ed6a25f5a"
TREE = "2bb27542cd2b7832f1e6ff1cc60972326a92ced7"
TRAIN_BLOB = "0caaf63014fea6132b06bf3a3924a9b54d91b99a"
README_BLOB = "318bd75a35e36498b9a94b965068cce4669b07b8"
SEED = 20261104
N_DOCUMENTS = 50
MAX_FILE_BYTES = 1024 * 1024
ID = re.compile(r"w[0-9]{6}-[0-9]{10}\Z")
STRUCTURE = re.compile(r"^[*+] (?:[0-9]+ )?-?[0-9]+[A-Z](?: |$)")


class ProbeError(ValueError):
    """Invalid provenance or unsupported source structure; never infer a label."""


def blob_sha1(raw: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()


def authenticate_blob(content: str, expected: str, size: int | None = None) -> bytes:
    if not isinstance(content, str):
        raise ProbeError("source must be exact decoded UTF-8 content")
    raw = content.encode("utf-8")
    if not 0 < len(raw) <= MAX_FILE_BYTES or blob_sha1(raw) != expected or (size is not None and len(raw) != size):
        raise ProbeError("source Git identity or byte size differs")
    return raw


def write_once(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def read_json(path: Path, maximum: int = 16 * 1024 * 1024):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ProbeError("missing or oversized transport file")
    return json.loads(path.read_bytes())


def select_documents(train: bytes, tree: dict) -> list[dict]:
    if blob_sha1(train) != TRAIN_BLOB or tree.get("commit") != COMMIT or tree.get("tree") != TREE:
        raise ProbeError("membership/tree differs from the pinned source")
    ids = train.decode("utf-8").splitlines()
    if len(ids) != 3915 or len(set(ids)) != len(ids) or any(not ID.fullmatch(value) for value in ids):
        raise ProbeError("training membership differs")
    files = tree.get("files")
    if not isinstance(files, list) or not len(files) <= 20_000:
        raise ProbeError("tree metadata exceeds bound")
    selected = sorted(ids, key=lambda value: (canonical_json_hash([SEED, value]), value))[:N_DOCUMENTS]
    wanted = set(selected)
    matching = {}
    for item in files:
        path = item.get("path", "")
        if not isinstance(path, str):
            raise ProbeError("invalid tree path")
        parts = path.split("/")
        doc = parts[-1].removesuffix(".knp")
        if doc not in wanted or not path.startswith("knp/") or not path.endswith(".knp"):
            continue
        if (len(parts) != 3 or any(part in {"", ".", ".."} or "\\" in part or ":" in part for part in parts)
                or item.get("mode") != "100644" or type(item.get("size")) is not int
                or not 0 < item["size"] <= MAX_FILE_BYTES or not re.fullmatch(r"[0-9a-f]{40}", item.get("sha", ""))
                or doc in matching):
            raise ProbeError("ambiguous or unsupported selected tree entry")
        matching[doc] = dict(document_id=doc, path=path, git_blob_sha1=item["sha"], bytes=item["size"])
    if set(matching) != wanted:
        raise ProbeError("selected training document missing from tree")
    return [matching[doc] for doc in selected]


def prepare(plan: Path, transport: Path, output: Path) -> dict:
    if hashlib.sha256(plan.read_bytes()).hexdigest() != PLAN_SHA256:
        raise ProbeError("preregistered plan changed")
    membership = read_json(transport / "membership.json")
    readme = read_json(transport / "readme.json")
    train = authenticate_blob(membership["content"], TRAIN_BLOB)
    notice = authenticate_blob(readme["content"], README_BLOB)
    docs = select_documents(train, read_json(transport / "tree.json"))
    manifest = dict(kind="kwdlc_development_probe_selection", schema_version=1,
                    plan_sha256=PLAN_SHA256, corpus_commit=COMMIT, corpus_tree=TREE,
                    membership_git_blob_sha1=TRAIN_BLOB, membership_sha256=hashlib.sha256(train).hexdigest(),
                    readme_git_blob_sha1=README_BLOB, readme_sha256=hashlib.sha256(notice).hexdigest(),
                    seed=SEED, selected_documents=docs, selection_sha256=canonical_json_hash(docs),
                    index_base=0, independent_test=False, gold_certified=False,
                    metadata_request_attempts=5,
                    metadata_recovery="One membership reread after a local JSON-decoding assumption failed; no automatic network retries.")
    for name, raw in (("train.id", train), ("source-README.md", notice),
                      ("selection.json", canonical_json_bytes(manifest) + b"\n")):
        write_once(output / name, raw)
    return manifest


def _morpheme(line: str) -> tuple[str, str]:
    fields = line.split()
    if (len(fields) < 11 or any(not fields[i].isdigit() for i in (4, 6, 8, 10))
            or any("\0" in value for value in fields[:11])):
        raise ProbeError("unsupported_morpheme_columns")
    return fields[0], fields[1]


def extract_target(document_id: str, raw: bytes) -> dict:
    """Indices are zero-based; choose before reading validity or converter results."""
    if not ID.fullmatch(document_id) or not 0 < len(raw) <= MAX_FILE_BYTES:
        raise ProbeError("invalid_document_identity_or_size")
    lines = raw.decode("utf-8", errors="strict").splitlines()
    if len(lines) > 10_000 or any(len(line.encode("utf-8")) > 16_384 for line in lines):
        raise ProbeError("document_line_bound")
    sentences, current, candidates = [], None, []
    previous = None
    for line in lines:
        if not line:
            continue
        if line.startswith("# S-ID:"):
            if current is not None:
                raise ProbeError("sentence_missing_eos")
            sid = line.split()[1].removeprefix("S-ID:")
            if sid != f"{document_id}-{len(sentences)+1}":
                raise ProbeError("foreign_or_reordered_sentence")
            current, previous = [], None
        elif line == "EOS":
            if current is None or not current:
                raise ProbeError("unexpected_eos")
            sentences.append(current)
            current, previous = None, None
        elif current is None:
            raise ProbeError("content_outside_sentence")
        elif STRUCTURE.match(line):
            continue
        elif line.startswith("@ "):
            if previous is None:
                raise ProbeError("orphan_alternative")
            _morpheme(line[2:])
            previous["alternative_annotation"] = True
        else:
            surface, reading = _morpheme(line)
            previous = {"surface": surface, "reading": reading, "alternative_annotation": False}
            current.append(previous)
    if current is not None or len(sentences) != 3:
        raise ProbeError("expected_three_complete_sentences")
    for sentence_index, sentence in enumerate(sentences):
        left = ""
        for morpheme_index, token in enumerate(sentence):
            if any(unicodedata.name(char, "").startswith("CJK UNIFIED IDEOGRAPH-") for char in token["surface"]):
                candidates.append(dict(token, sentence_index=sentence_index, morpheme_index=morpheme_index,
                                       left_context=left[-64:]))
            left = (left + token["surface"])[-64:]
    base = dict(kind="kwdlc_development_target_not_gold", document_id=document_id,
                source_sha256=hashlib.sha256(raw).hexdigest(), source_morphemes=sum(map(len, sentences)),
                eligible_ideograph_targets=len(candidates))
    if not candidates:
        return dict(base, status="no_target")
    target = min(candidates, key=lambda row: canonical_json_hash(
        [SEED, document_id, row["sentence_index"], row["morpheme_index"]]))
    reading = target["reading"]
    # This probe does not guess a pronunciation or transliterate annotation syntax.
    if target["alternative_annotation"]:
        status = "alternative_annotation"
    elif not 1 <= len(reading) <= 128 or not 1 <= len(target["surface"]) <= 256:
        status = "length_outside_contract"
    elif not all("\u3041" <= char <= "\u3096" or char == "\u30fc" for char in reading):
        status = "special_reading_annotation"
    else:
        status = "ready_for_forward_check"
    stable_id = "kwdlc-" + canonical_json_hash([COMMIT, document_id, target["sentence_index"], target["morpheme_index"]])
    return dict(base, **target, stable_id=stable_id, status=status)


def ingest(transport: Path, output: Path, *, expected_selection_sha256: str) -> dict:
    if hashlib.sha256((output / "selection.json").read_bytes()).hexdigest() != expected_selection_sha256:
        raise ProbeError("selection differs from its external pre-access commitment")
    manifest = read_json(output / "selection.json")
    docs = manifest["selected_documents"]
    if (manifest.get("plan_sha256") != PLAN_SHA256 or manifest.get("corpus_commit") != COMMIT
            or manifest.get("index_base") != 0 or len(docs) != N_DOCUMENTS
            or canonical_json_hash(docs) != manifest["selection_sha256"]):
        raise ProbeError("selection manifest differs")
    receipt = read_json(output / "acquisition.json")
    attempts = receipt["attempts"]
    if (receipt.get("corpus_commit") != COMMIT or receipt.get("status") != "complete"
            or len(attempts) != 55 or sum(a["kind"] == "document" for a in attempts) != 50
            or [a["index"] for a in attempts if a["kind"] == "document"] != list(range(50))
            or any(a["outcome"] != "received" for a in attempts if a["kind"] == "document")):
        raise ProbeError("acquisition is incomplete or outside its request bound")
    prepared, rows = [], []
    for index, doc in enumerate(docs):
        wrapper = read_json(transport / f"document-{index:03d}.json", 4 * MAX_FILE_BYTES)
        raw = authenticate_blob(wrapper["content"], doc["git_blob_sha1"], doc["bytes"])
        prepared.append((doc, raw))
        try:
            row = extract_target(doc["document_id"], raw)
        except (ProbeError, UnicodeError) as error:
            row = dict(kind="kwdlc_development_target_not_gold", document_id=doc["document_id"],
                       source_sha256=hashlib.sha256(raw).hexdigest(), status="parse_failure",
                       failure_code=str(error) if isinstance(error, ProbeError) else "invalid_utf8")
        rows.append(row)
    source = output / "source"
    source.mkdir(exist_ok=False)
    for doc, raw in prepared:
        write_once(source / (doc["document_id"] + ".knp"), raw)
    targets = b"".join(canonical_json_bytes(row) + b"\n" for row in rows)
    requests = [dict(stable_id=row["stable_id"], reading=row["reading"])
                for row in rows if row["status"] == "ready_for_forward_check"]
    request_bytes = b"".join(canonical_json_bytes(row) + b"\n" for row in sorted(requests, key=lambda row: row["stable_id"]))
    report = dict(kind="kwdlc_development_probe_extraction", schema_version=1,
        plan_sha256=PLAN_SHA256, selection_sha256=manifest["selection_sha256"], corpus_commit=COMMIT,
        selected_documents=N_DOCUMENTS, source_bytes=sum(len(raw) for _, raw in prepared),
        source_request_attempts=len(attempts), document_requests=sum(a["kind"] == "document" for a in attempts),
        metadata_request_attempts=sum(a["kind"] == "metadata" for a in attempts),
        counts=dict(sorted(Counter(row["status"] for row in rows).items())),
        targets_sha256=hashlib.sha256(targets).hexdigest(), requests_sha256=hashlib.sha256(request_bytes).hexdigest(),
        forward_request_count=len(requests), forward_executed=False,
        human_review_count=0, independently_certified_labels=0, gate_a_pass=False,
        new_final_test_used=False, labels_changed=False, models_trained=0,
        raw_text_in_report=False, raw_stable_ids_in_report=False)
    for name, raw in (("targets.jsonl", targets), ("requests.jsonl", request_bytes),
                      ("extraction.json", canonical_json_bytes(report) + b"\n")):
        write_once(output / name, raw)
    return report
