r"""Sensitivity analyses. Aggregates only; participant code and records stay local.

  python code/analysis/tlt_sensitivity.py --zip D:\session-records.zip

1. Matching-window sensitivity: submissions whose best AI block (same matcher as tlt_pck_labels: difflib ratio on
   tokens, autojunk off) reaches 0.80 / 0.99 within 60, 90, 120 and 240 minutes before the submission.
2. Tier-B near-verbatim flag rates by the share of submission tokens that are new under the same-request rule
   (|P_b \ P_u| / |s|: 0.5-0.7, 0.7-0.9, >= 0.9), for the four strongest external detectors.
3. Deduplicated detector rates: tier-B near-verbatim submissions collapsed to (participant, problem, matched block)
   units; a unit counts as flagged if any of its submissions is flagged (and, separately, by the share flagged).
Thresholds: 5% of CodeNet validation human code per score file, as in the paper.
Output: results/sensitivity.json
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

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_episode_audit import ai_code_blocks, jsonl, pno, tok, ts  # noqa: E402
from tier1_analyses import user_text, matched_positions  # noqa: E402
import tlt_echo_audit as ea  # noqa: E402
from tlt_detect_data import DET, PROJECT  # noqa: E402
from tlt_detect_eval import boot_sens, load_scores, thr  # noqa: E402

MIN = [60, 90, 120, 240]
METHODS = [("structgb", "ext"), ("droid", "offshelf"), ("unixcoder", "ext"), ("qwenlora", "ext")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, default=Path(r"D:\session-records.zip"))
    a = ap.parse_args()
    z = zipfile.ZipFile(a.zip)
    subs = list(csv.DictReader(open(ea.JUDGE / "submissions.csv", encoding="utf-8-sig")))
    for s in subs:
        s["t"] = ts(s["submitted_at"])
        s["tok"] = tok((ea.JUDGE / s["code_path"]).read_text(encoding="utf-8"))
    proxy_all, seen = {}, set()
    blocks = collections.defaultdict(list)
    for r in jsonl(z, "data/analysis/proxy_calls.jsonl"):
        if r.get("operation") or not r.get("created_at") or r.get("status") != "success":
            continue
        rid = r.get("chat_request_id")
        if pno(r.get("problem_id")):
            if rid not in seen:
                seen.add(rid)
                proxy_all[rid] = r
            for i, (src, b) in enumerate(ai_code_blocks(r)):
                blocks[r["participant"]].append((ts(r["created_at"]), rid, tok(b), i))
    lab = {r["submission_id"]: r for r in csv.DictReader(open(PROJECT / "datasets" / "audit" / "tlt_labels.csv", encoding="utf-8"))}
    win = {m: collections.Counter() for m in MIN}
    newshare, unit = {}, {}
    for s in subs:
        T = s["tok"]
        cand = [b for b in blocks.get(s["user_id"], []) if s["t"] - timedelta(minutes=max(MIN)) <= b[0] <= s["t"]]
        best = {m: (-1.0, None) for m in MIN}
        for b in cand:
            q = difflib.SequenceMatcher(None, T, b[2], autojunk=False).ratio()
            lag = s["t"] - b[0]
            for m in MIN:
                if lag <= timedelta(minutes=m):
                    if q > best[m][0] + 1e-12 or (abs(q - best[m][0]) <= 1e-12 and b[0] < best[m][1][0]):
                        best[m] = (q, b)
        for m in MIN:
            q = best[m][0]
            win[m]["linked_080"] += int(q >= 0.80)
            win[m]["near_verbatim_099"] += int(q >= 0.99)
        L = lab[s["submission_id"]]
        if L["stratum"] == "near_verbatim" and L["tier_B"] == "1" and best[90][1] is not None:
            first = best[90][1]
            pa, _ = matched_positions(T, first[2])
            same = tok(user_text(proxy_all.get(first[1]) or {}))
            pr = matched_positions(T, same)[0] if same else set()
            newshare[s["submission_id"]] = len(pa - pr) / max(1, len(T))
            unit[s["submission_id"]] = (s["user_id"], s["problem_id"], first[1], first[3])
    res = dict(note="Aggregates only. Window counts use the labels' matcher; at 90 minutes they "
                    "should equal the paper's 952 linked and 895 near-verbatim submissions.",
               matching_window={f"{m}min": dict(win[m]) for m in MIN})
    rows = list(csv.DictReader(open(DET / "items.csv", encoding="utf-8")))
    val_h = [r["item_id"] for r in rows if r["set"] == "val" and r["label"] == "0"]
    S = load_scores()
    bins = [("0.5-0.7", 0.5, 0.7), ("0.7-0.9", 0.7, 0.9), ("0.9-1.0", 0.9, 1.01)]
    tb = sorted(newshare)
    res["tier_B_near_verbatim"] = len(tb)
    res["new_share_bins_n"] = {nm: sum(lo <= newshare[x] < hi for x in tb) for nm, lo, hi in bins}
    units = collections.defaultdict(list)
    for x in tb:
        units[unit[x]].append(x)
    res["dedup_units"] = dict(units=len(units), participants=len({u[0] for u in units}),
                              submissions_per_unit_median=float(np.median([len(v) for v in units.values()])),
                              submissions_per_unit_max=max(len(v) for v in units.values()))
    lines = {r["item_id"][4:]: int(r["lines"]) for r in rows if r["set"] == "pck"}
    q1, q2 = np.quantile([lines[x] for x in tb], [1 / 3, 2 / 3])
    from scipy.stats import spearmanr
    rho = spearmanr([newshare[x] for x in tb], [lines[x] for x in tb])
    res["new_share_vs_lines_spearman"] = dict(rho=round(float(rho.correlation), 3), p=float(rho.pvalue), tercile_cuts=[float(q1), float(q2)])
    rng = random.Random(6414)
    for m, reg in METHODS:
        sc = S[(m, reg, "raw")]
        t = thr(sc, val_h, 0.05)
        f = {x: int(sc[f"pck_{x}"] >= t) for x in tb if f"pck_{x}" in sc}
        by = {nm: round(float(np.mean([f[x] for x in f if lo <= newshare[x] < hi])), 3) for nm, lo, hi in bins}
        ul = [(k[0], max(f[x] for x in v if x in f)) for k, v in units.items() if any(x in f for x in v)]
        um = [(k[0], float(np.mean([f[x] for x in v if x in f]))) for k, v in units.items() if any(x in f for x in v)]
        # the same bands within line-count terciles (cut points of the tier-B lines)
        within = {}
        for tn, lo_l, hi_l in (("short", -1, q1), ("medium", q1, q2), ("long", q2, 1e9)):
            within[tn] = {nm: (round(float(np.mean(v)), 3), len(v)) for nm, lo, hi in bins
                          for v in [[f[x] for x in f if lo <= newshare[x] < hi and lo_l < lines[x] <= hi_l]] if v}
        res[f"{m}__{reg}"] = dict(per_submission=round(float(np.mean(list(f.values()))), 3), by_new_share=by,
                                  by_new_share_within_tercile=within,
                                  per_unit_any=boot_sens([v for _, v in ul], [p for p, _ in ul], rng),
                                  per_unit_mean_share=round(float(np.mean([v for _, v in um])), 3))
    out = ROOT / "results" / "sensitivity.json"
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
