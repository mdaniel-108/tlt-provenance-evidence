r"""chaining rule. Aggregates only.

  python code/analysis/tlt_echo_chain.py --zip D:\session-records.zip

**Population:** near-verbatim submissions whose best match (X1 matching, via tlt_echo_audit.classify) is **not** mostly new
under the same-request rule, so they are outside tier B.

**Echoed material E:** submission tokens matched by the matched answer *and* by the user text of its request.

**Chain link:** an earlier AI code block e qualifies when:
1. it was received before the matched answer, in another request of the same participant;
2. its own contribution is **new in its request**: we use only the submission tokens that e matches and that the user text
   of e's own request does not match, so an earlier AI echo of the participant's code does not count as AI origin;
3. with that contribution, the AI-derived share reaches one half:
   (|answer-new| + |E ∩ e-new|) / |T| >= 0.5, where answer-new = tokens matched by the answer and not by its request text.

The case is attributed to the **earliest** qualifying block. One link only: chains of several echoes are not followed.

Lookback windows reported: 90 and 180 minutes before the matched answer, and the whole record.

If the private audit key and consensus exist (private_data/datasets/audit/tlt_echo/), the rule is compared with the
coded EQ3 of the audited cases, as an aggregate table.

Output: results/echo_chain.json.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_episode_audit import tok  # noqa: E402
from tier1_analyses import user_text, matched_positions  # noqa: E402
import tlt_echo_audit as ea  # noqa: E402

WINDOWS = {"90min": timedelta(minutes=90), "180min": timedelta(minutes=180), "all": None}


def chain(c, blocks, proxy_all, req_tok_cache):
    s, first = c["s"], c["first"]
    T = s["tok"]
    pa, _ = matched_positions(T, first[2])
    same = tok(user_text(proxy_all.get(first[1]) or {}))
    pr = matched_positions(T, same)[0] if same else set()
    new = pa - pr
    if len(new) / max(1, len(T)) >= 0.5:
        return None                                  # mostly new under the same-request rule: tier B, not a candidate
    E = pa & pr
    need = 0.5 * len(T) - len(new)
    found = {}
    for b in sorted(blocks.get(s["user_id"], []), key=lambda b: b[0]):
        if b[0] >= first[0] or b[1] == first[1]:
            continue
        pe = matched_positions(T, b[2])[0]
        if not pe & E:
            continue
        if b[1] not in req_tok_cache:
            req_tok_cache[b[1]] = tok(user_text(proxy_all.get(b[1]) or {}))
        rt = req_tok_cache[b[1]]
        pe_new = pe - (matched_positions(T, rt)[0] if rt else set())
        if len(E & pe_new) >= need:
            lag = first[0] - b[0]
            for w, d in WINDOWS.items():
                if w not in found and (d is None or lag <= d):
                    found[w] = lag
    return dict(E=len(E), T=len(T), found=found)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, default=Path(r"D:\session-records.zip"))
    a = ap.parse_args()
    cases, blocks, _, proxy_all = ea.classify(a.zip)
    cache, res_rows = {}, []
    for c in cases:
        r = chain(c, blocks, proxy_all, cache)
        if r is not None:
            res_rows.append((c, r))
    n = len(res_rows)
    out = dict(
        note=("Automatic chaining rule, one link, earliest qualifying earlier AI block whose own contribution is new in its "
              "request. Population: near-verbatim submissions outside tier B (not mostly new under the same-request rule)."),
        candidates=n, candidate_participants=len({c["s"]["user_id"] for c, _ in res_rows}),
        candidates_by_stratum=dict(collections.Counter(c["stratum"] for c, _ in res_rows)),
        b_chain={}, )
    for w in WINDOWS:
        hit = [(c, r) for c, r in res_rows if w in r["found"]]
        lags = sorted(r["found"][w].total_seconds() / 60 for _, r in hit)
        out["b_chain"][w] = dict(n=len(hit), of=n, share=round(len(hit) / n, 3) if n else None,
                                 participants=len({c["s"]["user_id"] for c, _ in hit}),
                                 median_lag_min=round(lags[len(lags) // 2], 1) if lags else None)
    # comparison with the coded audit (aggregate only)
    key_p = ea.PRIV / "key.csv"
    if key_p.exists():
        key = {r["submission_id"]: r["case_id"] for r in csv.DictReader(open(key_p, encoding="utf-8"))}
        a1, a2 = ea.read(ea.PRIV / "coder1.jsonl"), ea.read(ea.PRIV / "coder2.jsonl")
        cons = {}
        for f in sorted((ea.PRIV / "consensus").glob("out_*.jsonl")):
            cons.update(ea.read(f))
        tab = collections.Counter()
        for c, r in res_rows:
            cid = key.get(c["s"]["submission_id"])
            if not cid:
                continue
            x, y = a1.get((cid, "EQ3")), a2.get((cid, "EQ3"))
            eq3 = x if x == y else cons.get((cid, "EQ3"), "pending")
            tab[f"rule_{'chain' if 'all' in r['found'] else 'no_chain'}|EQ3_{eq3}"] += 1
        out["audit_comparison_all_window"] = dict(audited_candidates=sum(tab.values()), table=dict(sorted(tab.items())),
                                                  note="Coded EQ3 of the audited cases.")
    ea.OUT.mkdir(parents=True, exist_ok=True)
    (ea.OUT / "echo_chain.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
