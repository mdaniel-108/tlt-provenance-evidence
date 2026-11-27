r"""PCK reference labels per submission. Private table plus aggregate counts.

  python code/analysis/tlt_pck_labels.py --zip D:\session-records.zip

For every judged submission with an X1 match (containment >= 0.80, 90-minute window), the echo rules are applied to
**both** editing strata (near-verbatim >= 0.99 and edited 0.80-0.99), so every tier can be split by stratum:
- tier_C: matched (>= 0.80);
- tier_B: mostly new under the same-request rule (primary);
- tier_A: mostly new under the broad rule (conservative sensitivity);
- b_chain: not tier B, but the echoed material traces to an earlier AI block that is new in its own request (tlt_echo_chain);
- unknown: everything else (no match, or echo without a chain). Never treated as human.

Private output: private_data/datasets/audit/tlt_labels.csv. Aggregate: results/pck_labels.json.
"""
from __future__ import annotations

import argparse
import collections
import csv
import difflib
import json
import sys
import zipfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_episode_audit import ai_code_blocks, jsonl, tok, ts  # noqa: E402
from tier1_analyses import user_text, matched_positions  # noqa: E402
import tlt_echo_audit as ea  # noqa: E402
from tlt_echo_chain import chain  # noqa: E402

W = timedelta(minutes=90)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, default=Path(r"D:\session-records.zip"))
    a = ap.parse_args()
    z = zipfile.ZipFile(a.zip)
    subs = list(csv.DictReader(open(ea.JUDGE / "submissions.csv", encoding="utf-8-sig")))
    for s in subs:
        s["t"] = ts(s["submitted_at"])
        s["code"] = (ea.JUDGE / s["code_path"]).read_text(encoding="utf-8")
        s["tok"] = tok(s["code"])
    link = {r["submission_id"]: r for r in csv.DictReader(open(ea.LINK, encoding="utf-8-sig"))}
    proxy_all, seen = {}, set()
    blocks, utext = collections.defaultdict(list), collections.defaultdict(list)
    from build_episode_audit import pno
    for r in jsonl(z, "data/analysis/proxy_calls.jsonl"):
        if r.get("operation") or not r.get("created_at") or r.get("status") != "success":
            continue
        t = ts(r["created_at"])
        rid = r.get("chat_request_id")
        if pno(r.get("problem_id")):
            if rid not in seen:
                seen.add(rid)
                u = user_text(r)
                if tok(u):
                    utext[r["participant"]].append((t, tok(u), u, rid))
                proxy_all[rid] = r
            for src, b in ai_code_blocks(r):
                blocks[r["participant"]].append((t, rid, tok(b), b, src))
    rows, cache = [], {}
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
        lk = link[s["submission_id"]]
        row = dict(submission_id=s["submission_id"], participant=s["user_id"], problem_id=s["problem_id"], language=s["language"],
                   verdict=s["verdict"], tokens=len(T), best_similarity=lk["best_ai_similarity"],
                   stratum="near_verbatim" if lk["verbatim_ai"] == "True" else "edited" if float(lk["best_ai_similarity"] or 0) >= 0.80 else "none",
                   tier_C=0, tier_B=0, tier_A=0, b_chain=0, match_src="")
        if top >= 0.80 and ties and row["stratum"] != "none":
            first = min(ties, key=lambda b: b[0])
            row["tier_C"], row["match_src"] = 1, first[4]
            pa, _ = matched_positions(T, first[2])
            same = tok(user_text(proxy_all.get(first[1]) or {}))
            pr = matched_positions(T, same)[0] if same else set()
            row["tier_B"] = int(len(pa - pr) / max(1, len(T)) >= 0.5)
            broad = set(pr)
            for (tu, ut, _, _) in utext.get(s["user_id"], []):
                if first[0] - W <= tu <= first[0]:
                    broad |= matched_positions(T, ut)[0]
            row["tier_A"] = int(len(pa - broad) / max(1, len(T)) >= 0.5)
            if not row["tier_B"]:
                c = chain(dict(s=s, first=first), blocks, proxy_all, cache)
                row["b_chain"] = int(bool(c and "all" in c["found"]))
        row["unknown"] = int(not (row["tier_B"] or row["b_chain"]))
        rows.append(row)
    out = ea.PROJECT / "datasets" / "audit" / "tlt_labels.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    agg = dict(submissions=len(rows), participants=len({r["participant"] for r in rows}))
    for st in ("near_verbatim", "edited", "none"):
        g = [r for r in rows if r["stratum"] == st]
        agg[st] = dict(n=len(g), tier_C=sum(r["tier_C"] for r in g), tier_B=sum(r["tier_B"] for r in g),
                       tier_A=sum(r["tier_A"] for r in g), b_chain=sum(r["b_chain"] for r in g), unknown=sum(r["unknown"] for r in g))
    agg["by_language_tier_B"] = dict(collections.Counter(r["language"] for r in rows if r["tier_B"]))
    agg["note"] = "Tier B primary. Unknown is never treated as human."
    ea.OUT.mkdir(parents=True, exist_ok=True)
    (ea.OUT / "pck_labels.json").write_text(json.dumps(agg, indent=2), encoding="utf-8")
    print(json.dumps(agg, indent=2))


if __name__ == "__main__":
    main()
