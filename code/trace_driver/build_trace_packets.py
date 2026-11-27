r"""Convert each controlled-trace run into a full-record packet in the format of
code/analysis/tlt_rq4_packets.py (reference packets: Core, R-A, R-U, R-P, R-E, with times).

Inputs, per run (recorded data only; the ground-truth key is used only to know which participant
belongs to which run and is never written into a packet):
  server records  D:\tlt\trace\export\<participant>\<session>\*.ndjson, proxy\*.json   (export_run.py)
  device records  D:\tlt\trace\vscode\<run>\ud\User\globalStorage\ken-sevenseas.llm-cp-telemetry\
                  (source-capture Git repository; copied to D:\tlt\trace\device\<participant>\)
The submission is the recorded submission_marker event; the submitted program is the main.py body in
the source capture taken for that marker. The verdict is from local tests of that program.

  python code/trace_driver/build_trace_packets.py
"""
import csv
import json
import random
import shutil
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
from build_episode_audit import ai_code_blocks, response_text, tok, ts  # noqa: E402
from tlt_echo_audit import render  # noqa: E402

T = Path(r"D:\tlt\trace")
W = timedelta(minutes=90)
TYPES = ["R-A", "R-U", "R-P", "R-E", "R-T"]
PROBLEMS = json.loads(subprocess.run(["node", "-e", "process.stdout.write(JSON.stringify(require('D:/tlt/trace/scripts/problems.cjs')))"],
                                     capture_output=True, text=True, check=True).stdout)
import difflib  # noqa: E402


def sim(a, b):
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def mins(t, ref):
    return f"{(t - ref).total_seconds() / 60:+.1f} min"


def git(gitdir, *args):
    return subprocess.run(["git", "--git-dir", str(gitdir), *args], capture_output=True, check=True).stdout


def verdict(code, prob):
    for inp, exp in PROBLEMS[str(prob)]["tests"]:
        try:
            r = subprocess.run([sys.executable, "-I", "-c", code], input=inp, capture_output=True, text=True, timeout=10)
        except subprocess.TimeoutExpired:
            return "TLE"
        if r.returncode != 0:
            return "RE"
        if r.stdout.split() != exp.split():
            return "WA"
    return "AC"


def load(run):
    p = run["participant"]
    ex = T / "export" / p
    events, proxy = [], []
    for sess in ex.iterdir():
        for f in sorted(sess.glob("*.ndjson")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    e = json.loads(line)
                    e.setdefault("participant", p)
                    e.setdefault("session_id", sess.name)
                    events.append(e)
        for f in (sess / "proxy").glob("*.json"):
            proxy.append(json.loads(f.read_text(encoding="utf-8")))
    gs = T / "vscode" / run["run_id"] / "ud" / "User" / "globalStorage" / "ken-sevenseas.llm-cp-telemetry"
    dev_copy = T / "device" / p
    if gs.exists() and not dev_copy.exists():
        shutil.copytree(gs, dev_copy)
    repos = {}
    for rj in dev_copy.glob("source/*/*/repository.json"):
        repos[rj.parent.name] = rj.parent / "git"
    return events, proxy, repos


def capture_files(repos, pl):
    """{path: text} of a source capture, read from the device's source Git repository."""
    g = repos.get(pl.get("repository_id"))
    sha = pl.get("commit_sha")
    if not g or not sha:
        return None
    out = {}
    try:
        for line in git(g, "ls-tree", "-r", sha).decode().splitlines():
            meta, path = line.split("\t", 1)
            out[path] = git(g, "cat-file", "-p", meta.split()[2]).decode("utf-8", "replace")
    except subprocess.CalledProcessError:
        return None
    return out


def build(run, rng, used):
    events, proxy, repos = load(run)
    offs = {e["session_id"]: (e.get("payload") or {}).get("clock_offset_ms") or 0 for e in events if e["type"] == "session_start"}
    dev = lambda e: ts(e["client_ts"]) + timedelta(milliseconds=offs.get(e["session_id"], 0))  # noqa: E731
    marks = [e for e in events if e["type"] == "submission_marker"]
    if not marks:
        return None, "no submission_marker recorded"
    mk = max(marks, key=dev)
    ref = dev(mk)
    capid = (mk.get("payload") or {}).get("source_capture_id")
    caps = {(e.get("payload") or {}).get("capture_id"): e for e in events if e["type"] == "source_capture"}
    files = capture_files(repos, caps[capid]["payload"]) if capid in caps else None
    if not files:
        return None, "submission capture not readable"
    code_path = next((k for k in files if k.endswith("main.py")), None)
    code = files[code_path]
    prob = int(mk["payload"]["problem_id"][-2:])
    Tk = tok(code)

    reqs, seen = [], {}
    for r in sorted(proxy, key=lambda r: r["created_at"]):
        if r.get("operation") or r.get("status") != "success":
            continue
        seen[r.get("chat_request_id")] = r          # keep the final call of each request (what was shown)
    for rid, r in seen.items():
        t = ts(r["created_at"])
        if not (ref - W <= t <= ref):
            continue
        no = int((r.get("problem_id") or "x-00")[-2:])
        bl = ai_code_blocks(r)
        best = max((sim(Tk, tok(b)) for _, b in bl), default=0.0)
        if no == prob or best >= 0.30:
            reqs.append((t, rid, no, r, bl))
    reqs.sort(key=lambda x: x[0])
    rmap = {rid: f"Q{i}" for i, (_, rid, _, _, _) in enumerate(reqs, 1)}
    msg_to_q = {r.get("message_id"): rmap[rid] for (_, rid, _, r, _) in reqs if r.get("message_id")}

    def stamp(t, on):
        return f" at {mins(t, ref)}" if on else ""

    def sec_A(on):
        L, prev = [], []
        for (t, rid, no, r, bl) in reqs:
            thread = "this problem" if no == prob else "another problem"
            txt = response_text(r) or ""
            L += [f"### Answer to {rmap[rid]} ({thread}){stamp(t, on)}", "```text", txt[:1500].rstrip()
                  + ("\n[... answer text truncated]" if len(txt) > 1500 else ""), "```", ""]
            for j, (src, b) in enumerate(bl, 1):
                if sim(Tk, tok(b)) >= 0.30 or no == prob:
                    L += render(b, f"{rmap[rid]}.{src}{j}", prev)
        return L

    def sec_U(on):
        L, prev, shown = [], [], {}
        for (t, rid, no, r, _) in reqs:
            L += [f"### Request {rmap[rid]}{stamp(t, on)}", ""]
            j = 0
            for m in r.get("messages") or []:
                if not (isinstance(m, dict) and m.get("role") == "user"):
                    continue
                c = m.get("content")
                txt = c if isinstance(c, str) else "\n".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
                if not txt.strip():
                    continue
                j += 1
                if txt in shown:
                    L += [f"- {rmap[rid]}.u{j}: repeats {shown[txt]}", ""]
                    continue
                L += render(txt, f"{rmap[rid]}.u{j}", prev)
                shown[txt] = f"{rmap[rid]}.u{j}"
        return L

    evs = sorted([e for e in events if ref - W <= dev(e) <= ref], key=dev)

    def sec_P(on):
        L, k = [], 0
        for e in evs:
            if e["type"] != "edit_proposal":
                continue
            pl = e.get("payload") or {}
            q = msg_to_q.get(pl.get("message_id"))
            if not q and (e.get("problem_id") or "") != f"provisional-problem-{prob:02d}":
                continue
            k += 1
            L.append(f"- P{k}{stamp(dev(e), on)}: from {q or 'an answer not shown'}, proposal {pl.get('proposal_index')}, "
                     f"outcome {pl.get('outcome')}, file {Path(pl.get('uri') or '').name}, versions {pl.get('version_before')}->{pl.get('version_after')}")
        return L + [""] if L else ["(no proposal events)", ""]

    def sec_E(on):
        L, k = [], 0
        for e in evs:
            pl = e.get("payload") or {}
            if e["type"] == "edit_delta":
                ch = pl.get("changes") if isinstance(pl.get("changes"), list) else []
                text = "".join(c.get("text") or "" for c in ch if isinstance(c, dict))
                if not text.strip():
                    continue
                k += 1
                ex = text[:400] + (f" [... {len(text) - 400} more characters]" if len(text) > 400 else "")
                L += [f"- D{k}{stamp(dev(e), on)}: insertion of {len(text)} characters into {Path(pl.get('uri') or '').name}, version {pl.get('version')}",
                      "```", ex, "```"]
            elif e["type"] == "file_save":
                L.append(f"- save{stamp(dev(e), on)}: {Path(pl.get('uri') or '').name}")
        if len(L) > 160:
            L = L[:40] + [f"[... {len(L) - 120} lines of editor events omitted ...]"] + L[-80:]
        cl = []
        for e in evs:
            if e["type"] != "source_capture":
                continue
            fs = capture_files(repos, e.get("payload") or {})
            best = None
            for pth, b in (fs or {}).items():
                if not pth.endswith(".py"):
                    continue
                r_ = sim(tok(b), Tk)
                if not best or r_ > best[0]:
                    best = (r_, b.replace("\r\n", "\n").rstrip() == code.replace("\r\n", "\n").rstrip(), Path(pth).name)
            if best:
                cl.append(f"- capture{stamp(dev(e), on)}: best same-language file {best[2]}, token similarity to the submitted program "
                          f"{best[0]:.3f}, identical: {best[1]}")
        if len(cl) > 20:
            cl = cl[:5] + [f"[... {len(cl) - 15} captures omitted ...]"] + cl[-10:]
        return (L or ["(no editor events)"]) + ["", "Source captures (state of the participant's files):"] + (cl or ["(no captures)"]) + [""]

    while True:
        cid = f"T{rng.getrandbits(24):06x}"
        if cid not in used:
            used.add(cid)
            break
    on = True
    L = [f"# Reference packet (full record) {cid}", "", f"Record types present: {', '.join(TYPES)}.", "withheld: []", "",
         "## Core", f"- problem: {prob}", "- language: Python", f"- verdict: {verdict(code, prob)}",
         "- submission time: 0 min (all times are minutes relative to the submission; device and judge clocks are separate and uncalibrated)",
         "", "### Submitted program", "```", code.rstrip(), "```", ""]
    for name, fn in (("Assistant answers (R-A)", sec_A), ("User messages and attached files (R-U)", sec_U),
                     ("Proposal events (R-P)", sec_P), ("Editor events and source captures (R-E)", sec_E)):
        L += [f"## {name}", ""] + fn(on)
    out = (T / "packets" / TAG if TAG else T / "packets") / f"{cid}.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    return dict(packet_id=cid, recorded_submission_time=ref.isoformat(), recorded_program_sha=__import__("hashlib").sha256(code.encode()).hexdigest()[:16],
                requests_shown=len(reqs), proposal_events=sum(e["type"] == "edit_proposal" for e in evs)), None


EXT = "--ext" in sys.argv     # packets/ext, key_ext.csv, batches trace_ext_*; the 27 original packets are untouched
S3H = "--s3h" in sys.argv     # S3 at human typing speed (runs H*): packets/s3h, key_s3h.csv, batches trace_s3h_*
S3M = "--s3m" in sys.argv     # S3 at mid typing speed (runs M*): packets/s3m, key_s3m.csv, batches trace_s3m_*
TAG = "s3m" if S3M else ("s3h" if S3H else ("ext" if EXT else ""))


def main():
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((T / "runs").glob("M*.json" if S3M else ("H*.json" if S3H else ("X*.json" if EXT else "R*.json"))))]
    pdir = T / "packets" / TAG if TAG else T / "packets"
    pdir.mkdir(parents=True, exist_ok=True)
    (T / "batches").mkdir(exist_ok=True)
    for old in list(pdir.glob("T*.md")) + list((T / "batches").glob(f"trace_{TAG}_*.txt" if TAG else "trace_[0-9]*.txt")):
        old.unlink()
    rng = random.Random()        # packet IDs are random (not derived from run order)
    used, rows = set(), []
    if TAG:   # never reuse an ID of the original or extension packets
        used |= {p.stem for p in (T / "packets").glob("T*.md")} | {p.stem for sub in ("ext", "s3h", "s3m") if sub != TAG for p in (T / "packets" / sub).glob("T*.md")}
    for run in runs:
        info, err = build(run, rng, used) if run["ok"] else (None, "run failed: " + (run.get("error") or "")[:120])
        acts = "; ".join(f"{a['t']} {a['action']}" for a in run["actions"])
        rows.append(dict(run_id=run["run_id"], scenario=run["scenario"], problem=run["problem"], participant=run["participant"],
                         run_ok=run["ok"], packet_id=(info or {}).get("packet_id", ""), packet_error=err or "",
                         key_submission_time=run["submission_time"] or "", recorded_submission_time=(info or {}).get("recorded_submission_time", ""),
                         final_file_sha=__import__("hashlib").sha256((run["final_code"] or "").encode()).hexdigest()[:16],
                         recorded_program_sha=(info or {}).get("recorded_program_sha", ""), requests_shown=(info or {}).get("requests_shown", ""),
                         proposal_events=(info or {}).get("proposal_events", ""), actions=acts))
        print(run["run_id"], run["scenario"], (info or {}).get("packet_id"), err or "")
    with open(T / (f"key_{TAG}.csv" if TAG else "key.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    paths = [pdir / f"{r['packet_id']}.md" for r in rows if r["packet_id"]]
    rng.shuffle(paths)
    out, cur, size = [], [], 0
    for p in paths:
        if cur and size + p.stat().st_size > 300 * 1024:
            out.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += p.stat().st_size
    if cur:
        out.append(cur)
    for i, b in enumerate(out, 1):
        (T / "batches" / (f"trace_{TAG}_{i:02d}.txt" if TAG else f"trace_{i:02d}.txt")).write_text("".join(str(x) + "\n" for x in b), encoding="utf-8")
    print(json.dumps(dict(runs=len(runs), packets=len(paths), batches=len(out))))


if __name__ == "__main__":
    main()
