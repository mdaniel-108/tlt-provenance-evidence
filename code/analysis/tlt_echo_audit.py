r"""echo audit: build blinded packets (sample mode) and score agreement (score mode).

  python code/analysis/tlt_echo_audit.py sample --zip D:\session-records.zip
  python code/analysis/tlt_echo_audit.py score

Matching (the X1 rules):
- 90-minute window;
- earliest block among equal maxima;
- same-request rule vs broad rule (all user text sent in the 90 minutes before the matched answer);
- mostly new = at least half of the submission's tokens are matched by the answer and not by the discounted user text.

Strata among near-verbatim submissions (verbatim_ai in submission_linkage.csv):
- D: new under same-request, echo under broad (the rules disagree);
- AN: new under both rules;
- AE: echo under both rules.

The sample is 30 D + 15 AN + 15 AE, chosen with seed 63 and spread across participants.

Packets and the case key go to private_data/datasets/audit/tlt_echo/, which is outside Git (participant data). Auditors
never see the stratum or the rules: packets show user text and earlier AI code for 120 minutes before the answer, a wider
window than either rule uses. Only aggregate agreement goes to results/echo_audit.json.
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
PROJECT = Path("../private_data")
sys.path.insert(0, str(ROOT / "tools"))
from build_episode_audit import ai_code_blocks, jsonl, pno, tok, ts, response_text  # noqa: E402
from tier1_analyses import user_text, matched_positions  # noqa: E402

JUDGE = PROJECT / "datasets" / "pck2026_oln2026"
LINK = PROJECT / "datasets" / "audit" / "submission_linkage.csv"
PRIV = PROJECT / "datasets" / "audit" / "tlt_echo"
OUT = ROOT / "results"
W, SHOW = timedelta(minutes=90), timedelta(minutes=120)
SIZES = {"D": 30, "AN": 15, "AE": 15}
ITEMS = ["EQ1", "EQ2", "EQ3", "EQ4", "EQ5"]


def classify(zpath):
    z = zipfile.ZipFile(zpath)
    subs = list(csv.DictReader(open(JUDGE / "submissions.csv", encoding="utf-8-sig")))
    for s in subs:
        s["t"] = ts(s["submitted_at"])
        s["no"] = int(s["problem_id"]) - 794
        s["code"] = (JUDGE / s["code_path"]).read_text(encoding="utf-8")
        s["tok"] = tok(s["code"])
    link = {r["submission_id"]: r for r in csv.DictReader(open(LINK, encoding="utf-8-sig"))}
    proxy_all, seen = {}, set()
    blocks, utext = collections.defaultdict(list), collections.defaultdict(list)
    for r in jsonl(z, "data/analysis/proxy_calls.jsonl"):
        if r.get("operation") or not r.get("created_at") or r.get("status") != "success":
            continue
        t = ts(r["created_at"])
        rid = r.get("chat_request_id")
        if pno(r.get("problem_id")):
            first_rec = rid not in seen
            seen.add(rid)
            if first_rec:
                u = user_text(r)
                if tok(u):
                    utext[r["participant"]].append((t, tok(u), u, rid))
                proxy_all[rid] = r
            for src, b in ai_code_blocks(r):
                blocks[r["participant"]].append((t, rid, tok(b), b, src))
    cases = []
    for s in subs:
        T = s["tok"]
        cand = [b for b in blocks.get(s["user_id"], []) if s["t"] - W <= b[0] <= s["t"]]
        top, ties = -1.0, []
        for b in cand:
            m = difflib.SequenceMatcher(None, T, b[2], autojunk=False)
            if m.quick_ratio() + 1e-9 < top:
                continue
            q = m.ratio()
            if q > top + 1e-12:
                top, ties = q, [b]
            elif abs(q - top) <= 1e-12:
                ties.append(b)
        verb = link[s["submission_id"]]["verbatim_ai"] == "True"
        if top < 0.80 or not ties:
            continue
        first = min(ties, key=lambda b: b[0])
        pa, _ = matched_positions(T, first[2])
        same = tok(user_text(proxy_all.get(first[1]) or {}))
        pr = matched_positions(T, same)[0] if same else set()
        new_same = len(pa - pr) / max(1, len(T)) >= 0.5
        broad = set(pr)
        for (tu, ut, _, _) in utext.get(s["user_id"], []):
            if first[0] - W <= tu <= first[0]:
                broad |= matched_positions(T, ut)[0]
        new_broad = len(pa - broad) / max(1, len(T)) >= 0.5
        if not verb:
            continue
        st = "AN" if new_same and new_broad else "AE" if not new_same and not new_broad else "D" if new_same else "X"
        cases.append(dict(s=s, first=first, stratum=st))
    return cases, blocks, utext, proxy_all


def render(txt, label, prev, level="####"):
    """Show a text in full, or as a line diff against the most similar text already shown (ratio >= 0.6)."""
    L = txt.rstrip().splitlines()
    best, bl, br = None, None, 0.0
    for lab, pl in prev:
        sm = difflib.SequenceMatcher(None, pl, L, autojunk=False)
        if sm.quick_ratio() < max(br, 0.6):
            continue
        r = sm.ratio()
        if r > br:
            best, bl, br = lab, pl, r
    prev.append((label.split(" ")[0], L))
    if best is None:
        return [f"{level} {label}", "```text", chr(10).join(L), "```", ""]
    d = [x for x in difflib.unified_diff(bl, L, lineterm="", n=1)][2:]
    return [f"{level} {label}: same as {best} except (unified diff, - removed, + added)", "```diff", chr(10).join(d) if d else "(identical)", "```", ""]


def minutes(a, b):
    return round((a - b).total_seconds() / 60, 1)


def packet(c, blocks, utext, proxy_all, cid):
    s, (ta, rid, _, _, _) = c["s"], c["first"]
    p = s["user_id"]
    ans = proxy_all.get(rid) or {}
    matched_code = [b for b in blocks[p] if b[1] == rid]
    lines = [f"# Echo-audit packet {cid}", "",
             "Times are minutes relative to the matched answer (negative = before). Record IDs are local to this packet.", "",
             f"## Core", f"- problem: {s['no']}", f"- language: {s.get('language', '')}", f"- verdict: {s['verdict']}",
             f"- submission time: {minutes(s['t'], ta):+} min", "", "### Submitted program", "```", s["code"].rstrip(), "```", "",
             "## Matched answer (ID A0, time 0)", "", "### Answer text", "```text", response_text(ans).rstrip(), "```", ""]
    for i, b in enumerate(matched_code):
        if b[4] == "proposal":
            lines += [f"### Proposed edit in the answer (A0.p{i})", "```", b[3].rstrip(), "```", ""]
    lines += ["## Participant text sent in the 120 minutes before the answer (prompts with any attached files)", ""]
    lines += ["Each request carries its thread's earlier user messages. A message already shown is not repeated, only referenced.", ""]
    ut = [u for u in utext[p] if ta - SHOW <= u[0] <= ta]
    shown, shown_txt = {}, []
    for i, (tu, _, _, urid) in enumerate(sorted(ut, key=lambda u: u[0]), 1):
        tag = " (same request as A0)" if urid == rid else ""
        lines += [f"### U{i} at {minutes(tu, ta):+} min{tag}", ""]
        j = 0
        for m in (proxy_all.get(urid) or {}).get("messages") or []:
            if not (isinstance(m, dict) and m.get("role") == "user"):
                continue
            c_ = m.get("content")
            txt = c_ if isinstance(c_, str) else "\n".join(x.get("text", "") for x in c_ or [] if isinstance(x, dict))
            if not txt.strip():
                continue
            j += 1
            h = hash(txt)
            if h in shown:
                lines += [f"- U{i}.{j}: repeats {shown[h]}", ""]
                continue
            lines += render(txt, f"U{i}.{j}", shown_txt)
            shown[h] = f"U{i}.{j}"
    lines += ["## Earlier AI code in the 120 minutes before the answer (token similarity to the submitted program >= 0.30)", ""]
    eb = [b for b in blocks[p] if ta - SHOW <= b[0] < ta]
    seen, shown_ai = set(), []
    k = omitted = 0
    for b in sorted(eb, key=lambda b: b[0]):
        if b[1] == rid or b[3] in seen:
            continue
        seen.add(b[3])
        if difflib.SequenceMatcher(None, s["tok"], b[2], autojunk=False).ratio() < 0.30:
            omitted += 1
            continue
        k += 1
        lines += render(b[3], f"A{k} ({b[4]}) at {minutes(b[0], ta):+} min", shown_ai, level="###")
    lines += [f"({omitted} earlier AI code blocks with token similarity below 0.30 to the submitted program are omitted.)", ""]
    return "\n".join(lines) + "\n"


def sample(zpath, wave=1):
    global PRIV
    cases, blocks, utext, proxy_all = classify(zpath)
    cnt = collections.Counter(c["stratum"] for c in cases)
    if wave == 2:   # second wave: new cases only (wave-1 cases excluded), same stratum sizes
        done = {r["submission_id"] for r in csv.DictReader(open(PRIV / "key.csv", encoding="utf-8"))}
        cases = [c for c in cases if c["s"]["submission_id"] not in done]
        PRIV = PRIV.parent / "tlt_echo_w2"
    rng = random.Random(63 if wave == 1 else 6302)
    chosen = []
    for st, k in SIZES.items():
        pool = [c for c in cases if c["stratum"] == st]
        rng.shuffle(pool)
        byp = collections.defaultdict(list)
        for c in pool:
            byp[c["s"]["user_id"]].append(c)
        picked = []
        while len(picked) < k and any(byp.values()):     # round-robin over participants
            for p in sorted(byp, key=lambda _: rng.random()):
                if byp[p] and len(picked) < k:
                    picked.append(byp[p].pop())
        chosen += picked
    rng.shuffle(chosen)
    PRIV.mkdir(parents=True, exist_ok=True)
    (PRIV / "packets").mkdir(exist_ok=True)
    key = []
    for i, c in enumerate(chosen, 1):
        cid = f"E{i:03d}"
        (PRIV / "packets" / f"{cid}.md").write_text(packet(c, blocks, utext, proxy_all, cid), encoding="utf-8")
        key.append(dict(case_id=cid, submission_id=c["s"]["submission_id"], participant=c["s"]["user_id"], stratum=c["stratum"]))
    with open(PRIV / "key.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(key[0]))
        w.writeheader()
        w.writerows(key)
    batches, cur, size = [], [], 0                # consecutive batches of at most 300 KB (or one packet)
    for k in key:
        f = PRIV / "packets" / f"{k['case_id']}.md"
        if cur and size + f.stat().st_size > 300 * 1024:
            batches.append(cur)
            cur, size = [], 0
        cur.append(str(f))
        size += f.stat().st_size
    batches.append(cur)
    for n, b in enumerate(batches, 1):
        (PRIV / f"batch_{n:02d}.txt").write_text(chr(10).join(b) + chr(10), encoding="utf-8")
    sizes = [(PRIV / "packets" / f"{k['case_id']}.md").stat().st_size for k in key]
    info = dict(strata_population=dict(cnt), sample=dict(collections.Counter(k["stratum"] for k in key)),
                participants_in_sample=len({k["participant"] for k in key}), batches=len(batches),
                packet_kb=dict(min=round(min(sizes) / 1024, 1), median=round(sorted(sizes)[len(sizes) // 2] / 1024, 1), max=round(max(sizes) / 1024, 1)))
    print(json.dumps(info, indent=2))


def ac1(pairs):
    """Gwet's AC1 for nominal codes."""
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    cats = sorted({x for p in pairs for x in p})
    if len(cats) < 2:
        return 1.0
    pi = {k: (sum(a == k for a, _ in pairs) + sum(b == k for _, b in pairs)) / (2 * n) for k in cats}
    pe = sum(v * (1 - v) for v in pi.values()) / (len(cats) - 1)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def read(path):
    rows = {}
    for line in open(path, encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            v = r["answer"]
            try:
                v = "none" if str(v).strip().lower() == "none" else f"{float(v):.1f}"
            except (TypeError, ValueError):
                v = str(v)
            rows[(r["case_id"], r["item"])] = v
    return rows


def score(wave=1):
    global PRIV
    if wave == 2:
        PRIV = PRIV.parent / "tlt_echo_w2"
    key = {r["case_id"]: r for r in csv.DictReader(open(PRIV / "key.csv", encoding="utf-8"))}
    a, b = read(PRIV / "coder1.jsonl"), read(PRIV / "coder2.jsonl")
    res = dict(cases=len(key), agreement={})
    for it in ITEMS:
        pr = [(a[(c, it)], b[(c, it)]) for c in key if (c, it) in a and (c, it) in b]
        if it == "EQ5":
            pr = [("none" if x == "none" else "t", "none" if y == "none" else "t") for x, y in pr]
        res["agreement"][it] = dict(n=len(pr), raw=round(sum(x == y for x, y in pr) / len(pr), 3) if pr else None, ac1=ac1(pr))
    cons = {}
    for f in sorted((PRIV / "consensus").glob("out_*.jsonl")):
        cons.update(read(f))
    final = {}
    for c in key:
        for it in ITEMS:
            x, y = a.get((c, it)), b.get((c, it))
            final[(c, it)] = x if x == y else cons.get((c, it))
    res["consensus_items"] = sum(1 for c in key for it in ITEMS if a.get((c, it)) != b.get((c, it)))
    tab = collections.defaultdict(collections.Counter)
    eq3 = collections.defaultdict(collections.Counter)
    eq1 = collections.defaultdict(collections.Counter)
    for c, k in key.items():
        tab[k["stratum"]][final.get((c, "EQ4")) or "pending"] += 1
        eq3[k["stratum"]][final.get((c, "EQ3")) or "pending"] += 1
        eq1[k["stratum"]][final.get((c, "EQ1")) or "pending"] += 1
    res["EQ4_by_stratum"] = {k: dict(v) for k, v in tab.items()}
    res["EQ3_by_stratum"] = {k: dict(v) for k, v in eq3.items()}
    res["EQ1_by_stratum"] = {k: dict(v) for k, v in eq1.items()}
    res["note"] = ("Two echo auditors and a consensus coder. Strata: D rules disagree, AN both mostly new, AE both mostly echo.")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ("echo_audit.json" if wave == 1 else "echo_audit_w2.json")).write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps(res, indent=2))


def items(wave=1):
    """Merge coder outputs (out/c1_*, out/c2_*) and write consensus items for disagreements (<= 300 KB of packets per batch)."""
    global PRIV
    if wave == 2:
        PRIV = PRIV.parent / "tlt_echo_w2"
    for c in ("1", "2"):
        rows = [l for f in sorted((PRIV / "out").glob(f"c{c}_*.jsonl")) for l in open(f, encoding="utf-8") if l.strip()]
        (PRIV / f"coder{c}.jsonl").write_text("".join(r if r.endswith(chr(10)) else r + chr(10) for r in rows), encoding="utf-8")
    raw = {}
    for c in ("1", "2"):
        for line in open(PRIV / f"coder{c}.jsonl", encoding="utf-8"):
            r = json.loads(line)
            raw[(c, r["case_id"], r["item"])] = r
    a, b = read(PRIV / "coder1.jsonl"), read(PRIV / "coder2.jsonl")
    rng = random.Random(6303)
    out = []
    for k in sorted({(cid, it) for (_, cid, it) in raw}):
        if k in a and k in b and a[k] != b[k]:
            x, y = raw[("1",) + k], raw[("2",) + k]
            if rng.random() < 0.5:
                x, y = y, x
            keep = lambda r: {f: r.get(f) for f in ("answer", "confidence", "evidence_ref")}
            out.append(dict(case_id=k[0], stage="echo", config="", item=k[1], packet=str(PRIV / "packets" / f"{k[0]}.md"),
                            code_x=keep(x), code_y=keep(y)))
    (PRIV / "consensus").mkdir(exist_ok=True)
    n, cur, size, seen = 0, [], 0, set()
    for it in out:
        s_ = 0 if it["case_id"] in seen else Path(it["packet"]).stat().st_size
        if cur and it["case_id"] not in seen and size + s_ > 300 * 1024:
            n += 1
            (PRIV / "consensus" / f"items_{n:02d}.jsonl").write_text("".join(json.dumps(i) + chr(10) for i in cur), encoding="utf-8")
            cur, size, seen = [], 0, set()
        cur.append(it)
        size += s_
        seen.add(it["case_id"])
    if cur:
        n += 1
        (PRIV / "consensus" / f"items_{n:02d}.jsonl").write_text("".join(json.dumps(i) + chr(10) for i in cur), encoding="utf-8")
    print(len(out), "disagreement items in", n, "batches")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["sample", "items", "score"])
    ap.add_argument("--zip", type=Path, default=Path(r"D:\session-records.zip"))
    ap.add_argument("--wave", type=int, default=1, choices=[1, 2])
    x = ap.parse_args()
    {"sample": lambda: sample(x.zip, x.wave), "items": lambda: items(x.wave), "score": lambda: score(x.wave)}[x.mode]()
