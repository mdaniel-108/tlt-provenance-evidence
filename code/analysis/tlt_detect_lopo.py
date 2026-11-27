r"""Checks on the PCK-in-domain regime. Aggregates only.

  python code/analysis/tlt_detect_lopo.py near     # near-duplicates between training blocks and scored submissions
  python code/analysis/tlt_detect_lopo.py eval     # leave-problem-out scores (regimes pcklp<kp><kq>)

near: for every tier-B near-verbatim PCK submission, the highest token similarity (difflib ratio) to any logged AI block
      that was in the training data of the in-domain model that scored it (blocks of participants outside its fold), and
      to such blocks of the same problem.
eval: tier-B near-verbatim, tier-B edited and unknown-group flag rates of the leave-problem-out models (participants and
      problems held out), each at the 5% FPR threshold on CodeNet validation human code of its own model, next to the
      participant-only in-domain models (pck0-2).
Output: results/indomain_checks.json (keys "near" and "lopo").
"""
from __future__ import annotations

import csv
import difflib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from tlt_detect import folds, items, pnum, text  # noqa: E402
from tlt_detect_data import PROJECT, tokens  # noqa: E402

OUT = ROOT / "results" / "indomain_checks.json"
SC = Path(__file__).resolve().parents[1]


def labels():
    lab = {f"pck_{r['submission_id']}": r for r in csv.DictReader(open(PROJECT / "datasets" / "audit" / "tlt_labels.csv", encoding="utf-8"))}
    groups = {}
    for i, r in lab.items():
        if r["tier_B"] == "1":
            groups[i] = "tierB_near" if r["stratum"] == "near_verbatim" else "tierB_edited"
        elif r.get("unknown", "") == "1" or r["stratum"] in ("unmatched",):
            groups[i] = "unknown"
    return lab, groups


def load():
    res = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    return res


def near():
    rows = items()
    fd = folds(rows)
    lab, groups = labels()
    blocks = [(r, tokens(text(r, "raw"))) for r in rows if r["set"] == "pck_ai"]
    sims, same = [], []
    for r in rows:
        if r["set"] != "pck" or groups.get(r["item_id"]) != "tierB_near":
            continue
        T = tokens(text(r, "raw"))
        k = fd.get(r["participant"])
        b_all = b_same = 0.0
        for q, tb in blocks:
            if fd.get(q["participant"], -1) == k or not tb:
                continue
            sm = difflib.SequenceMatcher(None, T, tb, autojunk=False)
            if sm.real_quick_ratio() <= b_all and (pnum(q) != pnum(r) or sm.real_quick_ratio() <= b_same):
                continue
            if sm.quick_ratio() <= b_all and (pnum(q) != pnum(r) or sm.quick_ratio() <= b_same):
                continue
            x = sm.ratio()
            b_all = max(b_all, x)
            if pnum(q) == pnum(r):
                b_same = max(b_same, x)
        sims.append(b_all)
        same.append(b_same)
    sims, same = np.array(sims), np.array(same)
    res = load()
    res["near"] = dict(note="Tier-B near-verbatim submissions vs logged AI blocks in the training data of the in-domain model that scored them (other participant folds).",
                       n=len(sims), median_best_any=round(float(np.median(sims)), 3), median_best_same_problem=round(float(np.median(same)), 3),
                       share_ge_0_80_any=round(float(np.mean(sims >= 0.80)), 3), share_ge_0_99_any=round(float(np.mean(sims >= 0.99)), 3),
                       share_ge_0_80_same_problem=round(float(np.mean(same >= 0.80)), 3), share_ge_0_99_same_problem=round(float(np.mean(same >= 0.99)), 3))
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res["near"], indent=1))


def eval_():
    from tlt_detect_eval import load_scores, thr
    rows = items()
    lab, groups = labels()
    val_h = [r["item_id"] for r in rows if r["set"] == "val" and r["label"] == 0]
    S = load_scores()
    out = {}
    for m in ("tokenlr", "structgb", "unixcoder", "qwenlora"):
        for name, regs in (("participant_out", [f"pck{k}" for k in range(3)]), ("participant_and_problem_out", [f"pcklp{a}{b}" for a in range(3) for b in range(3)])):
            flags = {}
            ok = True
            for reg in regs:
                sc = S.get((m, reg, "raw"))
                if sc is None:
                    ok = False
                    break
                t5 = thr(sc, val_h, 0.05)
                for i, v in sc.items():
                    if i.startswith("pck_"):
                        flags[i] = v >= t5
            if not ok:
                continue
            d = {}
            for g in ("tierB_near", "tierB_edited", "unknown"):
                mem = [flags[i] for i, gg in groups.items() if gg == g and i in flags]
                d[g] = dict(n=len(mem), flagged=round(float(np.mean(mem)), 3) if mem else None)
            out.setdefault(m, {})[name] = d
    res = load()
    res["lopo"] = dict(note="Flag rates at each model's own 5% CodeNet-validation threshold. participant_out = the paper's PCK-in-domain regime; participant_and_problem_out = 9 models with participants and problem groups held out.", methods=out)
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res["lopo"], indent=1))


if __name__ == "__main__":
    {"near": near, "eval": eval_}[sys.argv[1]]()
