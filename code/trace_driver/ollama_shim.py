r"""Local OpenAI-compatible shim in front of the already-running Ollama (127.0.0.1:11434).

Why: qwen2.5-coder:7b on Ollama writes tool calls as JSON text instead of structured
`tool_calls`. The shim forwards each request to Ollama (non-streaming), turns a JSON-text tool
call of a tool that was offered into a structured `tool_calls` entry, and answers in the format the
client asked for (SSE stream or one JSON body). Nothing else is changed. Localhost only.

  python code/trace_driver/ollama_shim.py --port 11500
"""
import argparse
import json
import re
import sys
import time
import urllib.request
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OLLAMA = "http://127.0.0.1:11434"
LOG = None
NUDGE = ("To change an attached file you MUST call the propose_file_edit tool. Output exactly one line of the form "
         '<tool_call>{"name": "propose_file_edit", "arguments": {"path": ..., "baseContentHash": ..., "edits": [{"search": ..., "replace": ...}], "explanation": ...}}</tool_call>'
         " and nothing else. search must be exact lines copied from the attached file.")


def log(*a):
    if LOG:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")


def find_tool_calls(text, names):
    """Return a list of (name, arguments-dict) if the text is (or wraps) JSON tool calls."""
    cands = re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", text, re.S)
    if not cands:
        cands = [c[c.index("{"):] for c in re.findall(r"```[a-z]*\s*(.*?)```", text, re.S) if "{" in c]
    if not cands:
        s = text.strip()
        if s.startswith("{"):
            cands = [s]
        elif '{"name"' in s:
            cands = [s[s.index('{"name"'):]]
    out = []
    dec = json.JSONDecoder()
    for c in cands:
        c = c.strip()
        i = 0
        while i < len(c):
            try:
                obj, j = dec.raw_decode(c, i)
            except ValueError:
                break
            if isinstance(obj, dict) and obj.get("name") in names:
                args = obj.get("arguments", obj.get("parameters", {}))
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        pass
                out.append((obj["name"], args))
            i = j
            while i < len(c) and c[i] in " \n\r\t,":
                i += 1
    return out


_timer = {"t": None, "model": None}
_lock = threading.Lock()


def _unload(model):
    # release GPU memory while idle (GPU is shared): keep_alive 0 unloads only this model
    try:
        urllib.request.urlopen(urllib.request.Request(OLLAMA + "/api/generate", data=json.dumps({"model": model, "keep_alive": 0}).encode(),
                                                      headers={"Content-Type": "application/json"}), timeout=60).read()
        log("unloaded", model)
    except Exception as e:  # noqa: BLE001
        log("unload failed", e)


def schedule_unload(model, delay=20.0):
    with _lock:
        if _timer["t"]:
            _timer["t"].cancel()
        t = threading.Timer(delay, _unload, args=(model,))
        t.daemon = True
        _timer["t"] = t
        t.start()


def cancel_unload():
    with _lock:
        if _timer["t"]:
            _timer["t"].cancel()
            _timer["t"] = None


def to_native(msgs):
    out = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        c = m.get("content")
        if isinstance(c, list):
            c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
        n = {"role": m.get("role"), "content": c or ""}
        if m.get("tool_calls"):
            n["tool_calls"] = []
            for tc in m["tool_calls"]:
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                try:
                    args = json.loads(args) if isinstance(args, str) else (args or {})
                except ValueError:
                    args = {}
                n["tool_calls"].append({"function": {"name": fn.get("name"), "arguments": args}})
        out.append(n)
    return out


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        with urllib.request.urlopen(OLLAMA + self.path, timeout=30) as r:
            self._send(r.status, r.read())

    def do_POST(self):
        cancel_unload()
        try:
            self._post()
        finally:
            pass   # keep_alive 0 per request: nothing stays loaded

    def _post(self):
        n = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(n) or b"{}")
        if not self.path.endswith("/chat/completions"):
            self._send(404, json.dumps({"error": "unsupported path"}))
            return
        stream = bool(req.get("stream"))
        include_usage = bool((req.get("stream_options") or {}).get("include_usage"))
        names = {t.get("function", {}).get("name") for t in req.get("tools") or []}
        fwd = {k: v for k, v in req.items() if k not in ("stream", "stream_options", "reasoning_effort", "parallel_tool_calls", "user", "metadata")}
        fwd["stream"] = False
        last_user = next((m for m in reversed(fwd.get("messages") or []) if isinstance(m, dict) and m.get("role") == "user"), {})
        lu = last_user.get("content")
        lu = lu if isinstance(lu, str) else json.dumps(lu)
        if names and "content_hash" not in lu:
            names = set()   # tools offered only because of older attachments: plain answer, no nudge
            fwd.pop("tools", None)
        if names:
            # stand-in model nudge (documented): qwen2.5-coder often answers in prose instead of calling the tool
            fwd["messages"] = list(fwd.get("messages") or []) + [{"role": "system", "content": NUDGE}]
        tcs, content, resp = [], "", None
        nat = {"model": fwd.get("model"), "messages": to_native(fwd.get("messages") or []), "stream": False,
               "keep_alive": 0, "options": {"num_gpu": 0, "num_predict": 700}}   # CPU-only, unload right after (GPU reserved for other jobs)
        if fwd.get("tools"):
            nat["tools"] = fwd["tools"]
        for attempt in range(2 if names else 1):
            if attempt:
                nat["options"]["temperature"] = 0.4
            try:
                r = urllib.request.urlopen(urllib.request.Request(OLLAMA + "/api/chat", data=json.dumps(nat).encode(),
                                                                  headers={"Content-Type": "application/json"}), timeout=1800)
                resp = json.loads(r.read())
            except Exception as e:  # noqa: BLE001
                log("ERROR", e)
                self._send(502, json.dumps({"error": {"message": str(e)}}))
                return
            msg = resp.get("message") or {}
            content = msg.get("content") or ""
            tcs = [{"id": "call_" + uuid.uuid4().hex[:20], "type": "function",
                    "function": {"name": (tc.get("function") or {}).get("name"),
                                 "arguments": json.dumps((tc.get("function") or {}).get("arguments") or {}, ensure_ascii=False)}}
                   for tc in msg.get("tool_calls") or []]
            if not tcs and names:
                found = find_tool_calls(content, names)
                if found:
                    tcs = [{"id": "call_" + uuid.uuid4().hex[:20], "type": "function",
                            "function": {"name": nm, "arguments": json.dumps(a, ensure_ascii=False)}} for nm, a in found]
                    content = ""
            if tcs or not names:
                break
            log("no tool call on attempt", attempt, repr(content[:300]))
        finish = "tool_calls" if tcs else "stop"
        log("req", len(req.get("messages") or []), "msgs; tools", sorted(x for x in names if x), "-> tool_calls", len(tcs), "content", len(content),
            "eval_s", round((resp.get("total_duration") or 0) / 1e9, 1))
        resp["usage"] = {"prompt_tokens": resp.get("prompt_eval_count") or 0, "completion_tokens": resp.get("eval_count") or 0,
                         "total_tokens": (resp.get("prompt_eval_count") or 0) + (resp.get("eval_count") or 0)}
        resp["id"] = "chatcmpl-" + uuid.uuid4().hex[:12]
        rid, created, model = resp.get("id") or "chatcmpl-shim", int(time.time()), req.get("model")
        usage = resp.get("usage")
        if not stream:
            m = {"role": "assistant", "content": content or None}
            if tcs:
                m["tool_calls"] = tcs
            out = {"id": rid, "object": "chat.completion", "created": created, "model": model,
                   "choices": [{"index": 0, "message": m, "finish_reason": finish}], "usage": usage}
            self._send(200, json.dumps(out))
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def ev(delta, fin=None, extra=None):
            ch = {"id": rid, "object": "chat.completion.chunk", "created": created, "model": model,
                  "choices": [{"index": 0, "delta": delta, "finish_reason": fin}]}
            if extra:
                ch.update(extra)
            self.wfile.write(("data: " + json.dumps(ch, ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()

        ev({"role": "assistant", "content": ""})
        # stream the text in small pieces, like a provider would
        step = 40
        for i in range(0, len(content), step):
            ev({"content": content[i:i + step]})
        for k, tc in enumerate(tcs):
            ev({"tool_calls": [{"index": k, "id": tc["id"], "type": "function",
                                "function": {"name": tc["function"]["name"], "arguments": tc["function"]["arguments"]}}]})
        ev({}, finish)
        if include_usage and usage:
            u = {"id": rid, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [], "usage": usage}
            self.wfile.write(("data: " + json.dumps(u) + "\n\n").encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=11500)
    ap.add_argument("--log", default=None)
    a = ap.parse_args()
    LOG = a.log
    # bind on all interfaces so the Docker Desktop VM can reach it via host.docker.internal
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print("shim on", a.port, file=sys.stderr)
    srv.serve_forever()
