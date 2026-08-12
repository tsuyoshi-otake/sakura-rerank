"""Loopback-only human review server with atomic response persistence."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .human_audit import (
    MAX_NOTE_CHARS,
    RESPONSE_RECORD_TYPE,
    RESPONSE_SCHEMA_VERSION,
    REVIEWER_KINDS,
    VERDICTS,
    publish_audit_responses,
    read_audit_queue,
    read_audit_responses,
    read_queue_manifest,
    validate_audit_responses,
    validate_queue_manifest,
)
from .tier_a import TierAError


MAX_REVIEW_REQUEST_BYTES = 8 * 1024
REVIEW_ORDER_VERSION = "queue-seed-sha256-v1"


def _review_order(seed: int, stable_id: str) -> bytes:
    return hashlib.sha256(f"{seed}\0review\0{stable_id}".encode("utf-8")).digest()


class ReviewStore:
    """Own validated queue state and durable, non-overwritable judgments."""

    def __init__(
        self,
        queue: Sequence[Mapping[str, Any]],
        manifest: Mapping[str, Any],
        response_path: str | Path,
        reviewer_id: str,
        reviewer_kind: str,
        responses: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        validate_queue_manifest(manifest, queue)
        if not reviewer_id or len(reviewer_id) > 128:
            raise TierAError("reviewer_id is outside the identifier bound")
        if any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-" for character in reviewer_id):
            raise TierAError("reviewer_id contains an unsupported character")
        if not reviewer_id[0].isalnum() or not reviewer_id.isascii():
            raise TierAError("reviewer_id must start with an ASCII alphanumeric character")
        if reviewer_kind not in REVIEWER_KINDS:
            raise TierAError("reviewer_kind is unsupported")

        self._queue_by_id = {item["stable_id"]: dict(item) for item in queue}
        if len(self._queue_by_id) != len(queue):
            raise TierAError("audit queue: duplicate stable_id")
        self._order = sorted(
            self._queue_by_id,
            key=lambda stable_id: (_review_order(manifest["seed"], stable_id), stable_id),
        )
        self._response_path = Path(response_path)
        self._reviewer_id = reviewer_id
        self._reviewer_kind = reviewer_kind
        normalized_responses = validate_audit_responses(responses)
        self._responses = {
            response["stable_id"]: dict(response) for response in normalized_responses
        }
        if set(self._responses) - set(self._queue_by_id):
            raise TierAError("audit responses: contains IDs outside the queue")
        self._lock = threading.Lock()

    @classmethod
    def load(
        cls,
        queue_path: str | Path,
        manifest_path: str | Path,
        response_path: str | Path,
        reviewer_id: str,
        reviewer_kind: str,
    ) -> ReviewStore:
        queue = read_audit_queue(queue_path)
        manifest = read_queue_manifest(manifest_path)
        response_file = Path(response_path)
        responses = read_audit_responses(response_file) if response_file.exists() else []
        return cls(queue, manifest, response_file, reviewer_id, reviewer_kind, responses)

    def _next_pending(self) -> Mapping[str, Any] | None:
        for stable_id in self._order:
            if stable_id not in self._responses:
                return self._queue_by_id[stable_id]
        return None

    def state(self) -> dict[str, Any]:
        with self._lock:
            return self._state_unlocked()

    def submit(self, stable_id: str, verdict: str, note: str) -> dict[str, Any]:
        if verdict not in VERDICTS:
            raise TierAError("review verdict is unsupported")
        if not isinstance(note, str) or len(note) > MAX_NOTE_CHARS or "\0" in note:
            raise TierAError("review note is invalid")
        with self._lock:
            if stable_id not in self._queue_by_id:
                raise TierAError("review stable_id is outside the queue")
            if stable_id in self._responses:
                raise TierAError("review stable_id already has an immutable response")
            current = self._next_pending()
            if current is None or stable_id != current["stable_id"]:
                raise TierAError("review stable_id is not the current pending item")
            response = {
                "schema_version": RESPONSE_SCHEMA_VERSION,
                "record_type": RESPONSE_RECORD_TYPE,
                "stable_id": stable_id,
                "verdict": verdict,
                "reviewer_id": self._reviewer_id,
                "reviewer_kind": self._reviewer_kind,
                "reviewed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "note": note,
            }
            proposed = [*self._responses.values(), response]
            publish_audit_responses(self._response_path, proposed)
            self._responses[stable_id] = response
            return self._state_unlocked()

    def _state_unlocked(self) -> dict[str, Any]:
        verdict_counts = Counter(response["verdict"] for response in self._responses.values())
        return {
            "status": "complete" if len(self._responses) == len(self._order) else "reviewing",
            "review_order": REVIEW_ORDER_VERSION,
            "reviewer_kind": self._reviewer_kind,
            "selected_record_count": len(self._order),
            "completed_record_count": len(self._responses),
            "pending_record_count": len(self._order) - len(self._responses),
            "verdict_counts": {verdict: verdict_counts.get(verdict, 0) for verdict in VERDICTS},
            "item": self._next_pending(),
        }


_HTML = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sakura Rerank 教師監査</title><link rel="stylesheet" href="/style.css"></head>
<body><main><header><div><h1>Sakura Rerank 教師監査</h1><p id="progress">読み込み中…</p></div><div id="counts"></div></header>
<section id="review" hidden><div class="context"><h2>左文脈</h2><p id="context"></p></div>
<div class="reading"><span>読み</span><strong id="reading"></strong></div>
<div class="gold"><span>正解候補</span><strong id="gold"></strong><small id="segments"></small></div>
<div><h2>production候補</h2><ol id="candidates"></ol></div>
<label for="note">メモ（任意）</label><textarea id="note" maxlength="2000" rows="3"></textarea>
<div class="buttons" id="buttons"></div><p class="hint">ショートカット: Alt+1〜Alt+6</p></section>
<section id="done" hidden><h2>監査完了</h2><p>すべての回答がatomic response JSONLへ保存されました。</p></section>
<p id="error" role="alert"></p></main><script src="/app.js"></script></body></html>"""

_CSS = """*{box-sizing:border-box}body{margin:0;background:#f6f5f2;color:#24211d;font:16px/1.6 system-ui,sans-serif}main{max-width:960px;margin:auto;padding:28px}header{display:flex;justify-content:space-between;gap:24px;align-items:start}h1{margin:0;font-size:1.6rem}h2{font-size:1rem;margin:0 0 8px;color:#625b52}.context,.reading,.gold,section>div{margin:18px 0}.context p{white-space:pre-wrap;background:white;padding:18px;border-left:4px solid #bd4b34}.reading,.gold{display:grid;grid-template-columns:110px 1fr;gap:8px}.reading strong,.gold strong{font-size:1.35rem}.gold small{grid-column:2;color:#625b52;white-space:pre-wrap}ol{background:white;padding:14px 14px 14px 48px}textarea{width:100%;padding:10px}.buttons{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.buttons button{padding:13px;border:1px solid #8e8275;background:white;border-radius:6px;cursor:pointer}.buttons button:first-child{background:#315c47;color:white}.hint,#counts{color:#625b52;font-size:.9rem}#error{color:#a12424;font-weight:600}@media(max-width:700px){header{display:block}.buttons{grid-template-columns:1fr}.reading,.gold{grid-template-columns:1fr}.gold small{grid-column:1}}"""

_JS = """'use strict';
const token=location.hash.slice(1);
const labels=[['valid','正しい'],['wrong_reading','読みが誤り'],['wrong_segmentation','分割が誤り'],['wrong_gold_surface','正解表記が誤り'],['ambiguous','曖昧'],['extraction_noise','抽出ノイズ']];
let state=null,submitting=false;
const q=id=>document.getElementById(id);
async function api(path,options={}){const headers={'X-Review-Token':token,...(options.headers||{})};const r=await fetch(path,{...options,headers,cache:'no-store'});const body=await r.json();if(!r.ok)throw new Error(body.error||'request failed');return body}
function render(s){state=s;q('progress').textContent=`${s.completed_record_count} / ${s.selected_record_count} 完了（残り ${s.pending_record_count}）`;q('counts').textContent=labels.map(([k,v])=>`${v}: ${s.verdict_counts[k]}`).join(' · ');const item=s.item;q('review').hidden=!item;q('done').hidden=!!item;if(!item)return;q('context').textContent=item.left_context;q('reading').textContent=item.reading;q('gold').textContent=item.gold_surface;q('segments').textContent=item.gold_segments.map(x=>`${x.text_start}-${x.text_end}: ${x.source_category}`).join('\\n');const list=q('candidates');list.replaceChildren(...item.production_candidates.map(x=>{const li=document.createElement('li');li.textContent=`${x.rank}: ${x.surface}`;return li}));q('note').value='';q('error').textContent=''}
async function submit(verdict){if(submitting||!state?.item)return;submitting=true;try{state=await api('/api/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stable_id:state.item.stable_id,verdict,note:q('note').value})});render(state)}catch(e){q('error').textContent=e.message}finally{submitting=false}}
for(const [index,[verdict,label]] of labels.entries()){const b=document.createElement('button');b.type='button';b.textContent=`${index+1}. ${label}`;b.onclick=()=>submit(verdict);q('buttons').appendChild(b)}
addEventListener('keydown',e=>{if(e.altKey&&e.key>='1'&&e.key<='6'){e.preventDefault();submit(labels[Number(e.key)-1][0])}});
if(!token){q('error').textContent='session tokenがありません'}else{api('/api/state').then(s=>{state=s;render(s)}).catch(e=>q('error').textContent=e.message)}
"""


class _ReviewHandler(BaseHTTPRequestHandler):
    server: ReviewHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def _security_headers(self, content_type: str) -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )

    def _send_bytes(self, status: HTTPStatus, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self._security_headers(content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status: HTTPStatus, value: Mapping[str, Any]) -> None:
        payload = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self._send_bytes(status, payload, "application/json; charset=utf-8")

    def _authorized(self) -> bool:
        return secrets.compare_digest(
            self.headers.get("X-Review-Token", ""), self.server.session_token
        )

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/":
            self._send_bytes(HTTPStatus.OK, _HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/app.js":
            self._send_bytes(HTTPStatus.OK, _JS.encode("utf-8"), "text/javascript; charset=utf-8")
            return
        if path == "/style.css":
            self._send_bytes(HTTPStatus.OK, _CSS.encode("utf-8"), "text/css; charset=utf-8")
            return
        if path == "/api/state":
            if not self._authorized():
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            self._send_json(HTTPStatus.OK, self.server.store.state())
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/review":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return
        if self.headers.get_content_type() != "application/json":
            self._send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "JSON required"})
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if not 1 <= length <= MAX_REVIEW_REQUEST_BYTES:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "request outside byte bound"})
            return
        try:
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, Mapping) or set(value) != {"stable_id", "verdict", "note"}:
                raise TierAError("review request fields do not match schema")
            state = self.server.store.submit(value["stable_id"], value["verdict"], value["note"])
        except (json.JSONDecodeError, KeyError, TypeError, TierAError) as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        except OSError:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "response publication failed"})
            return
        self._send_json(HTTPStatus.OK, state)


class ReviewHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, port: int, store: ReviewStore, session_token: str | None = None) -> None:
        if not 0 <= port <= 65535:
            raise TierAError("review server port is outside the bound")
        self.store = store
        self.session_token = session_token or secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), _ReviewHandler)

    @property
    def review_url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/#{self.session_token}"


def run_review_server(
    queue_path: str | Path,
    manifest_path: str | Path,
    response_path: str | Path,
    reviewer_id: str,
    reviewer_kind: str,
    *,
    port: int,
) -> None:
    store = ReviewStore.load(
        queue_path, manifest_path, response_path, reviewer_id, reviewer_kind
    )
    with ReviewHTTPServer(port, store) as server:
        print(
            json.dumps(
                {
                    "status": "review_server_ready",
                    "url": server.review_url,
                    "completed_record_count": store.state()["completed_record_count"],
                    "selected_record_count": store.state()["selected_record_count"],
                    "reviewer_kind": reviewer_kind,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            pass
        finally:
            state = store.state()
            print(
                json.dumps(
                    {
                        "status": "review_server_stopped",
                        "completed_record_count": state["completed_record_count"],
                        "pending_record_count": state["pending_record_count"],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
