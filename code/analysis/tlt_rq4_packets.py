r"""Record-configuration study: sample submissions and build reference and configuration packets.

  python code/analysis/tlt_rq4_packets.py --zip D:\session-records.zip

**Sample** (seed 6304, round-robin over participants), by stratum:

| Stratum | Definition | Cases |
|---|---|---|
| AN | Near-verbatim, new under both echo rules | 12 |
| D | Near-verbatim, the rules disagree | 8 |
| AE | Near-verbatim, echo under both rules | 4 |
| ED | Edited, containment 0.80-0.99 | 10 |
| NM | No recorded match (< 0.80) | 6 |

Strata come from tlt_echo_audit.py (the X1 rules) and submission_linkage.csv.

**Window:** 90 minutes before the submission.

**Record types:**

| Code | Contents |
|---|---|
| R-A | Assistant answers: text excerpt plus code blocks; proposal code |
| R-U | User messages, with attached files |
| R-P | Proposal events and outcomes |
| R-E | Edit deltas, file saves and source captures |
| R-T | Times for every included record, plus the submission time; without R-T, records keep their stored order and carry no times |

Requests shown are those on the submission's problem, plus any request whose answer holds AI code with token
similarity >= 0.30 to the submission.

**Configurations:** Full (reference) plus 3 of the 10 restricted configurations per case, drawn at random. Each
configuration packet gets a fresh random ID, so no reviewer can link packets of the same case.

**Batches:** at most 300 KB each; one configuration per batch; no case twice in a batch.

**Outputs:** packets, keys and batches go to private_data/datasets/audit/tlt_rq4/ (outside Git: participant data).
"""
from __future__ import annotations

import argparse
import collections
import csv
import difflib
import json
import random
import sys
import zipfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_episode_audit import ai_code_blocks, jsonl, response_text, tok, ts  # noqa: E402
from tlt_echo_audit import PROJECT, JUDGE, LINK, classify, render  # noqa: E402
from tier1_analyses import user_text  # noqa: E402

PRIV = PROJECT / "datasets" / "audit" / "tlt_rq4"
W = timedelta(minutes=90)
ALLOC = {"AN": 12, "D": 8, "AE": 4, "ED": 10, "NM": 6}
TYPES = ["R-A", "R-U", "R-P", "R-E", "R-T"]
CONFIGS = {
    "E0": [], "E1": ["R-A"], "E1u": ["R-A", "R-U"], "E1u+P": ["R-A", "R-U", "R-P"], "E1u+T": ["R-A", "R-U", "R-T"],
    "Full-A": ["R-U", "R-P", "R-E", "R-T"], "Full-U": ["R-A", "R-P", "R-E", "R-T"], "Full-P": ["R-A", "R-U", "R-E", "R-T"],
    "Full-E": ["R-A", "R-U", "R-P", "R-T"], "Full-T": ["R-A", "R-U", "R-P", "R-E"],
}
PER_CASE = 3

# main study: frozen configuration list, larger stratified sample, first-sample cases excluded
MAIN_ALLOC = {"PR": 30, "AN": 35, "D": 25, "AE": 20, "ED": 57, "NM": 20}
MAIN_CONFIGS = {k: v for k, v in CONFIGS.items() if k != "E1u+T"}
MAIN_CONFIGS["E1+E+T"] = ["R-A", "R-E", "R-T"]


def sim(a, b):
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def mins(t, ref):
    return f"{(t - ref).total_seconds() / 60:+.1f} min"


def build(zpath, main=False, extend=None):
    """extend: a configuration name. build packets of that configuration for every
    main-study case that was not assigned to it, into config_ext/, with config_key_ext.csv and batches_ext/. The
    existing key, reference and configuration packets are not touched."""
    global PRIV, ALLOC, CONFIGS
    first_ids = set()
    if main:
        first_ids = {r["submission_id"] for r in csv.DictReader(open(PRIV / "key.csv", encoding="utf-8"))}
        PRIV, ALLOC, CONFIGS = PROJECT / "datasets" / "audit" / "tlt_rq4_main", MAIN_ALLOC, MAIN_CONFIGS
    z = zipfile.ZipFile(zpath)
    cases, _, _, _ = classify(zpath)
    strat = {c["s"]["submission_id"]: c["stratum"] for c in cases}
    echo = dict(strat)
    if main:   # over-sample near-verbatim cases whose best match is a proposal's code
        for c in cases:
            if c["first"][4] == "proposal":
                strat[c["s"]["submission_id"]] = "PR"
    link = {r["submission_id"]: r for r in csv.DictReader(open(LINK, encoding="utf-8-sig"))}
    subs = list(csv.DictReader(open(JUDGE / "submissions.csv", encoding="utf-8-sig")))
    for s in subs:
        s["t"] = ts(s["submitted_at"])
        s["no"] = int(s["problem_id"]) - 794
        sid = s["submission_id"]
        b = float(link[sid]["best_ai_similarity"] or 0)
        s["stratum"] = strat.get(sid) or ("ED" if b >= 0.80 else "NM")
        s["echo"] = echo.get(sid) or s["stratum"]
    subs = [s for s in subs if s["submission_id"] not in first_ids]
    rng = random.Random(6305 if main else 6304)
    chosen = []
    for st, k in ALLOC.items():
        pool = [s for s in subs if s["stratum"] == st]
        rng.shuffle(pool)
        byp = collections.defaultdict(list)
        for s in pool:
            byp[s["user_id"]].append(s)
        got = []
        while len(got) < k and any(byp.values()):
            for p in sorted(byp, key=lambda _: rng.random()):
                if byp[p] and len(got) < k:
                    got.append(byp[p].pop())
        chosen += got
    rng.shuffle(chosen)
    if extend:
        old_key = list(csv.DictReader(open(PRIV / "key.csv", encoding="utf-8")))
        old_cfg = list(csv.DictReader(open(PRIV / "config_key.csv", encoding="utf-8")))
        bysid = {s["submission_id"]: s for s in subs}
        ext_cases = [k for k in old_key if extend not in k["configs"].split(";")]
        chosen = [bysid[k["submission_id"]] for k in ext_cases]
        case_of = {k["submission_id"]: k["case"] for k in ext_cases}
        rng = random.Random(6399)
    parts = {s["user_id"] for s in chosen}

    # records
    reqs = collections.defaultdict(list)          # participant -> [(t, rid, problem_no, record)]
    seen = set()
    for r in jsonl(z, "data/analysis/proxy_calls.jsonl"):
        p = r.get("participant")
        pid = r.get("problem_id") or ""
        if p not in parts or r.get("operation") or r.get("status") != "success" or not pid.startswith("provisional-problem-"):
            continue
        rid = r.get("chat_request_id")
        if rid in seen:
            continue
        seen.add(rid)
        reqs[p].append((ts(r["created_at"]), rid, int(pid[-2:]), r))
    events = [e for e in jsonl(z, "data/analysis/telemetry.jsonl") if e.get("participant") in parts]
    offs = {(e["participant"], e["session_id"]): (e.get("payload") or {}).get("clock_offset_ms") or 0 for e in events if e["type"] == "session_start"}
    dev = lambda e: ts(e["client_ts"]) + timedelta(milliseconds=offs.get((e["participant"], e["session_id"]), 0))
    tel = collections.defaultdict(list)
    for e in events:
        tel[e["participant"]].append(e)
    snaps = collections.defaultdict(list)
    for s in jsonl(z, "data/analysis/source_snapshots.jsonl"):
        if s.get("participant") in parts:
            snaps[s["participant"]].append(s)
    with_dev = {r.get("participant") for r in jsonl(z, "data/analysis/local_chat_messages.jsonl")}

    def blob(sha):
        try:
            return z.read(f"data/blobs/{sha}").decode("utf-8", "replace")
        except KeyError:
            return None

    PRIV.mkdir(parents=True, exist_ok=True)
    for d in ("reference", "config"):
        (PRIV / d).mkdir(exist_ok=True)
    key, cfg_rows = [], []
    used_ids = set()
    if extend:
        used_ids |= {k["reference_id"] for k in old_key} | {r["packet_id"] for r in old_cfg}
        (PRIV / "config_ext").mkdir(exist_ok=True)
        # a second extended configuration keeps the rows and IDs of earlier extensions
        prev_ext = list(csv.DictReader(open(PRIV / "config_key_ext.csv", encoding="utf-8"))) if (PRIV / "config_key_ext.csv").exists() else []
        if any(r["config"] == extend for r in prev_ext):
            raise SystemExit(f"{extend} already extended; refusing to rebuild")
        used_ids |= {r["packet_id"] for r in prev_ext}

    def newid(prefix):
        while True:
            x = f"{prefix}{rng.getrandbits(24):06x}"
            if x not in used_ids:
                used_ids.add(x)
                return x

    for n, s in enumerate(chosen, 1):
        p, ref = s["user_id"], s["t"]
        code = (JUDGE / s["code_path"]).read_text(encoding="utf-8")
        T = tok(code)
        # requests in window: same problem, or holding AI code similar to the submission
        rq = []
        for (t, rid, no, r) in sorted(reqs[p], key=lambda x: x[0]):
            if not (ref - W <= t <= ref):
                continue
            bl = ai_code_blocks(r)
            best = max((sim(T, tok(b)) for _, b in bl), default=0.0)
            if no == s["no"] or best >= 0.30:
                rq.append((t, rid, no, r, bl))
        rmap = {rid: f"Q{i}" for i, (_, rid, _, _, _) in enumerate(rq, 1)}
        sec = {}

        def stamp(t, on):
            return f" at {mins(t, ref)}" if on else ""

        def sec_A(on):
            L, prev = [], []
            for (t, rid, no, r, bl) in rq:
                thread = "this problem" if no == s["no"] else "another problem"
                L += [f"### Answer to {rmap[rid]} ({thread}){stamp(t, on)}", "```text", (response_text(r) or "")[:1500].rstrip()
                      + ("\n[... answer text truncated]" if len(response_text(r) or "") > 1500 else ""), "```", ""]
                for j, (src, b) in enumerate(bl, 1):
                    if sim(T, tok(b)) >= 0.30 or no == s["no"]:
                        L += render(b, f"{rmap[rid]}.{src}{j}", prev)
            return L

        def sec_U(on):
            L, prev, shown = [], [], {}
            for (t, rid, no, r, _) in rq:
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
                    h = hash(txt)
                    if h in shown:
                        L += [f"- {rmap[rid]}.u{j}: repeats {shown[h]}", ""]
                        continue
                    L += render(txt, f"{rmap[rid]}.u{j}", prev)
                    shown[h] = f"{rmap[rid]}.u{j}"
            return L

        evs = sorted([e for e in tel[p] if ref - W <= dev(e) <= ref], key=dev)
        msg_to_q = {}
        for (t, rid, no, r, _) in rq:
            mid = r.get("message_id")
            if mid:
                msg_to_q[mid] = rmap[rid]

        def sec_P(on):
            L = []
            k = 0
            for e in evs:
                if e["type"] != "edit_proposal":
                    continue
                pl = e.get("payload") or {}
                q = msg_to_q.get(pl.get("message_id"))
                if not q and (e.get("problem_id") or "") != f"provisional-problem-{s['no']:02d}":
                    continue
                k += 1
                L.append(f"- P{k}{stamp(dev(e), on)}: from {q or 'an answer not shown'}, proposal {pl.get('proposal_index')}, "
                         f"outcome {pl.get('outcome')}, file {Path(pl.get('uri') or '').name}, versions {pl.get('version_before')}->{pl.get('version_after')}")
            return L + [""] if L else ["(no proposal events)", ""]

        def sec_E(on):
            L = []
            k = 0
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
            caps = []
            for sn in sorted(snaps[p], key=lambda x: x["requested_at"]):
                t = ts(sn["requested_at"])
                if not (ref - W <= t <= ref):
                    continue
                best = None
                for f in sn.get("files") or []:
                    if Path(f.get("path") or "").suffix != Path(s["code_path"]).suffix:
                        continue
                    b = blob(f.get("sha256"))
                    if b is None:
                        continue
                    r_ = sim(tok(b), T)
                    if not best or r_ > best[0]:
                        best = (r_, b.replace("\r\n", "\n").rstrip() == code.replace("\r\n", "\n").rstrip(), Path(f["path"]).name)
                if best:
                    caps.append(f"- capture{stamp(t, on)}: best same-language file {best[2]}, token similarity to the submitted program "
                                f"{best[0]:.3f}, identical: {best[1]}")
            if len(caps) > 20:
                caps = caps[:5] + [f"[... {len(caps) - 15} captures omitted ...]"] + caps[-10:]
            out = (L or ["(no editor events)"]) + ["", "Source captures (state of the participant's files):"] + (caps or ["(no captures)"]) + [""]
            if p not in with_dev:
                out = ["(This participant's device archive is empty: editor events, proposals and captures were not recorded.)", ""] + out
            return out

        def body(types, cid, title):
            on = "R-T" in types
            L = [f"# {title} {cid}", "", f"Record types present: {', '.join(types) or 'none (core only)'}.",
                 f"withheld: [{', '.join(t for t in TYPES if t not in types)}]", "",
                 "## Core", f"- problem: {s['no']}", f"- language: {s['language']}", f"- verdict: {s['verdict']}"]
            if on:
                L += ["- submission time: 0 min (all times are minutes relative to the submission; device and judge clocks are separate and uncalibrated)"]
            L += ["", "### Submitted program", "```", code.rstrip(), "```", ""]
            for t_, name, f in (("R-A", "Assistant answers (R-A)", sec_A), ("R-U", "User messages and attached files (R-U)", sec_U),
                                ("R-P", "Proposal events (R-P)", sec_P), ("R-E", "Editor events and source captures (R-E)", sec_E)):
                if t_ in types:
                    L += [f"## {name}", ""] + f(on)
            if not on:
                L += ["(Chronology withheld: no times are shown; records within each section are in stored order.)", ""]
            return "\n".join(L) + "\n"

        if extend:
            cid = newid("C")
            (PRIV / "config_ext" / f"{cid}.md").write_text(body(CONFIGS[extend], cid, f"Configuration packet ({extend})"), encoding="utf-8")
            cfg_rows.append(dict(case=case_of[s["submission_id"]], config=extend, packet_id=cid))
            continue
        rid_ = newid("R")
        (PRIV / "reference" / f"{rid_}.md").write_text(body(TYPES, rid_, "Reference packet (full record)"), encoding="utf-8")
        cfgs = rng.sample(sorted(CONFIGS), PER_CASE)
        key.append(dict(case=f"K{n:03d}" if main else f"K{n:02d}", submission_id=s["submission_id"], participant=p, stratum=s["stratum"], echo_label=s["echo"],
                        device_archive=p in with_dev, reference_id=rid_, configs=";".join(cfgs)))
        for c in cfgs:
            cid = newid("C")
            (PRIV / "config" / f"{cid}.md").write_text(body(CONFIGS[c], cid, f"Configuration packet ({c})"), encoding="utf-8")
            cfg_rows.append(dict(case=key[-1]["case"], config=c, packet_id=cid))

    if extend:
        with open(PRIV / "config_key_ext.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["case", "config", "packet_id"])
            w.writeheader()
            w.writerows(prev_ext + cfg_rows)
        (PRIV / "batches_ext").mkdir(exist_ok=True)
        paths = [PRIV / "config_ext" / f"{r['packet_id']}.md" for r in cfg_rows]
        out, cur, size = [], [], 0
        for f in paths:
            if cur and size + f.stat().st_size > 300 * 1024:
                out.append(cur)
                cur, size = [], 0
            cur.append(f)
            size += f.stat().st_size
        if cur:
            out.append(cur)
        for i, b in enumerate(out, 1):
            (PRIV / "batches_ext" / f"cfg_{extend.replace('+', 'p')}_ext_{i:02d}.txt").write_text("".join(str(x) + chr(10) for x in b), encoding="utf-8")
        print(json.dumps(dict(extended_config=extend, packets=len(cfg_rows), batches=len(out),
                              participants=len({s["user_id"] for s in chosen})), indent=1))
        return
    for name, rows in (("key.csv", key), ("config_key.csv", cfg_rows)):
        with open(PRIV / name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    def batches(paths, prefix):
        out, cur, size = [], [], 0
        for f in paths:
            if cur and size + f.stat().st_size > 300 * 1024:
                out.append(cur)
                cur, size = [], 0
            cur.append(f)
            size += f.stat().st_size
        if cur:
            out.append(cur)
        for i, b in enumerate(out, 1):
            (PRIV / "batches" / f"{prefix}_{i:02d}.txt").write_text("".join(str(x) + chr(10) for x in b), encoding="utf-8")
        return len(out)

    (PRIV / "batches").mkdir(exist_ok=True)
    nref = batches([PRIV / "reference" / f"{k['reference_id']}.md" for k in key], "ref")
    ncfg = {}
    for c in sorted(CONFIGS):
        ps = [PRIV / "config" / f"{r['packet_id']}.md" for r in cfg_rows if r["config"] == c]
        if ps:
            ncfg[c] = batches(ps, f"cfg_{c.replace('+', 'p')}")
    sz = sorted(f.stat().st_size for f in (PRIV / "reference").glob("*.md"))
    print(json.dumps(dict(cases=len(key), strata=dict(collections.Counter(k["stratum"] for k in key)),
                          participants=len({k["participant"] for k in key}), without_device_archive=sum(not k["device_archive"] for k in key),
                          config_packets=dict(collections.Counter(r["config"] for r in cfg_rows)), ref_batches=nref, cfg_batches=ncfg,
                          ref_packet_kb=dict(median=round(sz[len(sz) // 2] / 1024, 1), max=round(sz[-1] / 1024, 1))), indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, default=Path(r"D:\session-records.zip"))
    ap.add_argument("--main", action="store_true", help="main study: writes to tlt_rq4_main/")
    ap.add_argument("--extend", help="build this configuration for all main cases not assigned to it")
    x = ap.parse_args()
    build(x.zip, x.main or bool(x.extend), x.extend)
