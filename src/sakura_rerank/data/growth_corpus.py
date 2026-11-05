"""Source-preserving weak-label cohorts for the Issue-33 growth experiment.

This module never admits legacy training records or certifies Gold. Source
reservations, dictionary readings and bounded left context stay explicit.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import heapq
import re
from urllib.parse import urlsplit

from .contracts import canonical_json_hash, sentence_shingle_hashes, text_sha256
from .jawiki_preprocess import ExtractorConfig, SurfaceMatcher, _sentences
from .source_quality import quality_flags

SEED = 20261105
SOURCE_PATTERN = re.compile(rb'"source":(\{[^\r\n]*?\})[,}]')
ID_PATTERN = re.compile(rb'(?<!\\)"stable_id":"([A-Za-z0-9_.:-]+)"')
SOURCE_KEYS = {"corpus", "snapshot_date", "article_id", "page_id", "revision_id",
               "paragraph_hash", "sentence_hash", "sentence_shingle_hashes", "template_cluster_id"}


def partition(corpus: str, group: str) -> str:
    value = int(canonical_json_hash([SEED, corpus, group, "partition"]), 16)
    return "evaluation" if value % 10 < 2 else "train"


def wiki_page_selected(page_id: str, slot: int = 0) -> bool:
    if type(slot) is not int or not 0 <= slot < 100:
        raise ValueError("wiki_sample_slot_outside_bound")
    return int(canonical_json_hash([SEED, "jawiki", page_id, "sample"]), 16) % 100 == slot


def history_metadata(line: bytes) -> dict:
    """Decode only the source object and opaque ID, never labels/candidates."""
    if len(line) > 256 * 1024:
        raise ValueError("history_line_outside_bound")
    import json
    sources, ids = SOURCE_PATTERN.findall(line), ID_PATTERN.findall(line)
    if len(sources) != 1 or len(ids) != 1:
        raise ValueError("canonical_history_source_required")
    source = json.loads(sources[0])
    if (set(source) != SOURCE_KEYS or source["corpus"] != "jawiki"
            or not re.fullmatch(r"jawiki-page-[0-9]+", source["article_id"])
            or not isinstance(source["sentence_shingle_hashes"], list)):
        raise ValueError("historical_source_contract_differs")
    for field in ("paragraph_hash", "sentence_hash"):
        if not re.fullmatch(r"[0-9a-f]{64}", source[field]):
            raise ValueError("historical_source_hash_invalid")
    return dict(stable_id=ids[0].decode("ascii"), source=source, population="historical")


def select_aozora(rows: list[dict], train_count: int = 600, evaluation_count: int = 150) -> tuple[list[dict], dict]:
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["作品ID"]].append(row)
    eligible, counts = [], Counter()
    for work, entries in grouped.items():
        if len(entries) != 1:
            counts["multiple_contributor_rows"] += 1
            continue
        row = entries[0]
        if (row["役割フラグ"] != "著者" or row["作品著作権フラグ"] != "なし"
                or row["人物著作権フラグ"] != "なし" or row["文字遣い種別"] != "新字新仮名"
                or not any(code in row["分類番号"] for code in ("NDC 913", "NDC 914"))):
            counts["metadata_outside_scope"] += 1
            continue
        url = row["テキストファイルURL"]
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.netloc != "www.aozora.gr.jp"
                or parsed.query or parsed.fragment or not re.fullmatch(r"/cards/[0-9]+/files/[A-Za-z0-9_.-]+\.zip", parsed.path)
                or not work.isdigit() or not row["人物ID"].isdigit()
                or row["テキストファイル符号化方式"] != "ShiftJIS"):
            counts["unsupported_source_metadata"] += 1
            continue
        eligible.append(dict(work_id=work, author_id=row["人物ID"], url=url,
            partition=partition("aozora", row["人物ID"]), metadata_sha256=canonical_json_hash(row)))
    eligible.sort(key=lambda row: (canonical_json_hash([SEED, "aozora", row["work_id"], "select"]), row["work_id"]))
    selected, per_author, per_partition = [], Counter(), Counter()
    limits = {"train": train_count, "evaluation": evaluation_count}
    for row in eligible:
        if per_author[row["author_id"]] >= 8 or per_partition[row["partition"]] >= limits[row["partition"]]:
            continue
        selected.append(row)
        per_author[row["author_id"]] += 1
        per_partition[row["partition"]] += 1
    if dict(per_partition) != limits:
        raise ValueError("insufficient_fixed_metadata_population")
    return selected, dict(work_groups=len(grouped), eligible_works=len(eligible),
        eligible_authors=len({r["author_id"] for r in eligible}), selected_partitions=dict(per_partition),
        selected_authors=len(per_author), exclusions=dict(counts), work_text_accessed=False)


def aozora_paragraphs(raw: bytes) -> tuple[list[str], dict]:
    """Preserve modern text; quarantine markup/gaiji lines rather than guess."""
    if not 0 < len(raw) <= 32 * 1024 * 1024:
        raise ValueError("aozora_text_size_outside_bound")
    text = raw.decode("cp932", errors="strict")
    lines = text.splitlines()
    rules = [i for i, line in enumerate(lines) if re.fullmatch(r"-{20,}", line.strip())]
    if len(rules) < 2 or rules[1] > 100:
        raise ValueError("aozora_header_boundary_unrecognized")
    paragraphs, counts, found_footer = [], Counter(), False
    for line in lines[rules[1] + 1:]:
        if line.startswith("底本："):
            found_footer = True
            break
        line = line.strip()
        if not line:
            continue
        if len(line) > 100_000 or "※" in line or "［＃" in line or "］" in line:
            counts["annotation_or_gaiji_line_quarantined"] += 1
            continue
        if line.count("《") != line.count("》") or re.search(r"《[^》]*《", line):
            counts["malformed_ruby_line_quarantined"] += 1
            continue
        line = re.sub(r"《[^《》]*》", "", line).replace("｜", "")
        if "《" in line or "》" in line:
            counts["malformed_ruby_line_quarantined"] += 1
            continue
        paragraphs.append(line)
    if not found_footer:
        raise ValueError("aozora_footer_boundary_unrecognized")
    counts["paragraphs_retained"] = len(paragraphs)
    return paragraphs, dict(counts)


class GrowthExtractor:
    def __init__(self, dictionary_records: list[dict]):
        self.config = ExtractorConfig(max_records_per_page=128, max_surface_chars=64,
            min_reading_chars=3, max_reading_chars=32)
        self.matcher = SurfaceMatcher(dictionary_records, self.config)
        self.readings = {row["surface"]: row["readings"][0] for row in dictionary_records
                         if len(row["readings"]) == 1}

    def document(self, paragraphs: list[str], corpus: str, source_id: str, revision: str,
                 population: str, maximum: int, counts: Counter) -> list[dict]:
        """Keep bottom-hash targets over the whole document with O(maximum) rows."""
        heap = []
        for pi, paragraph in enumerate(paragraphs):
            for si, (offset, sentence) in enumerate(_sentences(paragraph)):
                if not 4 <= len(sentence) <= 512:
                    counts["sentence_outside_bounds"] += 1
                    continue
                for start, end, surface in self.matcher.matches(sentence, counts):
                    counts["dictionary_matches"] += 1
                    left = paragraph[max(0, offset + start - 64):offset + start]
                    flags = quality_flags(left, surface)
                    if flags:
                        counts["quality_quarantined"] += 1
                        counts.update("quality_" + f for f in flags)
                        continue
                    key = canonical_json_hash([SEED, corpus, source_id, revision, pi, si, start, end, surface])
                    score = int(key, 16)
                    if len(heap) == maximum and score >= -heap[0][0]:
                        continue
                    row = dict(kind="growth_source_exact_target", stable_id="growth-" + key,
                        corpus=corpus, source_id=source_id, source_revision=revision,
                        population=population, left_context=left, reading=self.readings[surface],
                        target=surface, context_origin="synthetic_source_prefix_not_observed_session",
                        label_kind="source_exact_weak_supervision", independent_gold_eligible=False,
                        source=dict(article_id=("jawiki-page-" if corpus == "jawiki" else "aozora-work-") + source_id,
                            paragraph_hash=text_sha256(paragraph), sentence_hash=text_sha256(sentence),
                            sentence_shingle_hashes=sentence_shingle_hashes(sentence), template_cluster_id=None))
                    item = (-score, key, row)
                    if len(heap) < maximum:
                        heapq.heappush(heap, item)
                    else:
                        heapq.heapreplace(heap, item)
        rows = [item[2] for item in sorted(heap, key=lambda item: item[1])]
        counts["targets_retained"] += len(rows)
        return rows
