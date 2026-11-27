r"""detector evaluation. Aggregates only.

  python code/analysis/tlt_detect_eval.py

**Thresholds** are fixed on CodeNet `val` before PCK is read: the score at which 5% (primary) and 1% of validation human
items are flagged. For the PCK-in-domain regime, each fold uses the threshold from its own model's validation scores.

**CodeNet** (external, presumed-human population): ROC-AUC and PR-AUC on `test` (unseen problems) and `seen_test`
(seen problems); false-positive rate on test human items at the fixed threshold; Brier score of min-max-scaled scores.

**PCK:** sensitivity at the fixed threshold for tier B (primary), tier A, tier C and B-chain, each split by editing
stratum (never pooled across strata); for the unknown group only the share flagged. No PCK ROC-AUC or false-positive rate.
95% intervals: participant-clustered bootstrap, 2,000 resamples, seed 6314.

**Other analyses:** by language and verdict (RQ2, exploratory), by length tercile; leave-one-generator-out AUC (RQ3);
verified transformations (rename, reformat) vs originals; fusion (RQ5): logistic stacking fitted on validation scores
with 5-fold cross-fitting, and a two-stage cascade (Token LR, then the best single method on the uncertain band).

Output: results/detection.json.
"""
from __future__ import annotations

import collections
import csv
import json
import random
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from tlt_detect_data import DET, GENS, PROJECT  # noqa: E402

SC = DET / "scores"
OUT = ROOT / "results" / "detection.json"
B = 2000


DROPPED = {}


def load_scores():
    """Non-finite scores (e.g. a log-likelihood of a near-empty program) are dropped and counted in the output."""
    S = {}
    for f in sorted(SC.glob("*.csv")):
        m, reg, inp = f.stem.split("__")
        d = {r["item_id"]: float(r["score"]) for r in csv.DictReader(open(f, encoding="utf-8"))}
        ok = {k: v for k, v in d.items() if np.isfinite(v)}
        if len(ok) < len(d):
            DROPPED[f.stem] = len(d) - len(ok)
        S[(m, reg, inp)] = ok
    return S


def thr(scores, human_ids, fpr):
    h = np.sort([scores[i] for i in human_ids if i in scores])
    return float(np.quantile(h, 1 - fpr)) if len(h) else None


def auc(scores, rows):
    y = [r["label"] for r in rows if r["item_id"] in scores]
    s = [scores[r["item_id"]] for r in rows if r["item_id"] in scores]
    if len(set(y)) < 2:
        return None, None
    return round(roc_auc_score(y, s), 4), round(average_precision_score(y, s), 4)


def boot_sens(flags, parts, rng):
    """flags: list of 0/1; parts: participant per flag. Participant-clustered bootstrap CI of the mean."""
    if not flags:
        return None
    by = collections.defaultdict(list)
    for f, p in zip(flags, parts):
        by[p].append(f)
    keys = list(by)
    est = float(np.mean(flags))
    bs = []
    for _ in range(B):
        smp = [by[keys[rng.randrange(len(keys))]] for _ in keys]
        v = [x for g in smp for x in g]
        bs.append(np.mean(v))
    return dict(n=len(flags), participants=len(keys), sensitivity=round(est, 3),
                ci95=[round(float(np.quantile(bs, 0.025)), 3), round(float(np.quantile(bs, 0.975)), 3)])


def main():
    rows = list(csv.DictReader(open(DET / "items.csv", encoding="utf-8")))
    for r in rows:
        r["label"] = int(r["label"])
    byset = collections.defaultdict(list)
    for r in rows:
        byset[r["set"]].append(r)
    lab = {f"pck_{r['submission_id']}": r for r in csv.DictReader(open(PROJECT / "datasets" / "audit" / "tlt_labels.csv", encoding="utf-8"))}
    S = load_scores()
    rng = random.Random(6314)
    res = dict(note="Thresholds fixed on CodeNet validation human code (5% and 1% flagged). PCK: sensitivity only, by tier and "
                    "editing stratum; unknown provenance is never treated as human. CodeNet human code is a historical, presumed-human population.",
               methods={})
    val_h = [r["item_id"] for r in byset["val"] if r["label"] == 0]
    pck = byset["pck"]
    groups = {}
    for st in ("near_verbatim", "edited"):
        for t in ("tier_B", "tier_A", "tier_C", "b_chain"):
            groups[f"{t}|{st}"] = [r for r in pck if lab[r["item_id"]]["stratum"] == st and lab[r["item_id"]][t] == "1"]
    groups["unknown|all"] = [r for r in pck if lab[r["item_id"]]["unknown"] == "1"]
    for key, sc in sorted(S.items()):
        m, reg, inp = key
        if reg.startswith("logo"):
            continue
        out = {}
        if reg.startswith("pck") and reg != "pck0":
            continue
        regs = [reg] if not reg.startswith("pck") else ["pck0", "pck1", "pck2"]
        th = {}
        for rg in regs:
            s2 = S.get((m, rg, inp), {})
            th[rg] = {f: thr(s2, val_h, f) for f in (0.05, 0.01)}
        base = S[(m, regs[0], inp)]
        out["codenet_test_unseen_problems"] = dict(zip(("roc_auc", "pr_auc"), auc(base, byset["test"])))
        out["codenet_test_seen_problems"] = dict(zip(("roc_auc", "pr_auc"), auc(base, byset["seen_test"])))
        t5 = th[regs[0]][0.05]
        th_h = [base[r["item_id"]] for r in byset["test"] if r["label"] == 0 and r["item_id"] in base]
        out["codenet_test_human_fpr_at_val5"] = round(float(np.mean([x >= t5 for x in th_h])), 3) if th_h else None
        for lang in ("C", "C++", "Java"):
            out[f"codenet_test_auc_{lang}"] = auc(base, [r for r in byset["test"] if r["language"] == lang])[0]
        for tname in ("rename", "reformat"):
            tr = byset[f"test_{tname}"]
            orig = {r["item_id"].split("__")[0] for r in tr}
            out[f"codenet_auc_{tname}"] = dict(transformed=auc(base, tr)[0],
                                               original_same_items=auc(base, [r for r in byset["test"] if r["item_id"] in orig])[0])
        pk = {}
        for g, members in groups.items():
            for f in (0.05, 0.01):
                flags, parts = [], []
                for r in members:
                    for rg in regs:
                        s2 = S.get((m, rg, inp), {})
                        if r["item_id"] in s2 and th[rg][f] is not None:
                            flags.append(int(s2[r["item_id"]] >= th[rg][f]))
                            parts.append(r["participant"])
                pk[f"{g}|fpr{int(f * 100)}"] = boot_sens(flags, parts, rng)
        out["pck"] = pk
        lb = {}
        tb = groups["tier_B|near_verbatim"]
        for dim in ("language", "status"):
            for v in sorted({r[dim] for r in tb}):
                mem = [r for r in tb if r[dim] == v]
                fl = [int(base.get(r["item_id"], -1e9) >= t5) for r in mem if r["item_id"] in base]
                if len(fl) >= 10:
                    lb[f"{dim}={v}"] = dict(n=len(fl), sensitivity=round(float(np.mean(fl)), 3))
        ln = sorted(int(r["lines"]) for r in tb)
        if ln:
            q1, q2 = np.quantile(ln, [1 / 3, 2 / 3])
            for name, lo, hi in (("short", -1, q1), ("medium", q1, q2), ("long", q2, 1e9)):
                mem = [r for r in tb if lo < int(r["lines"]) <= hi and r["item_id"] in base]
                if mem:
                    lb[f"length={name}"] = dict(n=len(mem), sensitivity=round(float(np.mean([base[r["item_id"]] >= t5 for r in mem])), 3))
        out["tier_B_near_verbatim_breakdown_fpr5"] = lb
        res["methods"]["__".join(key)] = out
    # leave-one-generator-out
    logo = {}
    for (m, reg, inp), sc in S.items():
        if reg.startswith("logo"):
            g = reg.split("_")[1]
            tst = [r for r in byset["test"] if r["label"] == 0 or r["generator"] == g]
            seen = S.get((m, "ext", inp), {})
            logo[f"{m}__{inp}__heldout_{g}"] = dict(unseen_generator=auc(sc, tst)[0], seen_generator_ext=auc(seen, tst)[0])
    res["leave_one_generator_out"] = logo
    # fusion on ext / zero-shot / off-the-shelf raw scores
    cand = [(m, reg, "raw") for (m, reg, inp) in S if inp == "raw" and reg in ("ext", "zeroshot", "offshelf")]
    cand = sorted(set(cand))
    if len(cand) >= 2:
        vrows = [r for r in byset["val"] if all(r["item_id"] in S[c] for c in cand)]
        X = np.array([[S[c][r["item_id"]] for c in cand] for r in vrows])
        y = np.array([r["label"] for r in vrows])
        oof = np.zeros(len(y))
        for trn, tst in StratifiedKFold(5, shuffle=True, random_state=6314).split(X, y):
            oof[tst] = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(X[trn], y[trn]).predict_proba(X[tst])[:, 1]
        stack = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)).fit(X, y)
        h_oof = np.sort(oof[y == 0])
        t5 = float(np.quantile(h_oof, 0.95))
        trows = [r for r in byset["test"] if all(r["item_id"] in S[c] for c in cand)]
        Xt = np.array([[S[c][r["item_id"]] for c in cand] for r in trows])
        pt = stack.predict_proba(Xt)[:, 1]
        fus = dict(inputs=["__".join(c) for c in cand], codenet_test_roc_auc=round(roc_auc_score([r["label"] for r in trows], pt), 4))
        prow = [r for r in groups["tier_B|near_verbatim"] if all(r["item_id"] in S[c] for c in cand)]
        if prow:
            pp = stack.predict_proba(np.array([[S[c][r["item_id"]] for c in cand] for r in prow]))[:, 1]
            fus["pck_tier_B_near_verbatim_fpr5"] = boot_sens([int(x >= t5) for x in pp], [r["participant"] for r in prow], rng)
        res["fusion_stacking"] = fus
        # cascade: Token LR decides outside its uncertain band; the best single method (val AUC) decides inside it
        s1 = ("tokenlr", "ext", "raw")
        others = [c for c in cand if c != s1]
        if s1 in S and others:
            vb = {c: auc(S[c], byset["val"])[0] or 0 for c in others}
            s2 = max(vb, key=vb.get)
            v1 = S[s1]
            lo = float(np.quantile([v1[r["item_id"]] for r in byset["val"] if r["label"] == 1 and r["item_id"] in v1], 0.05))
            hi = thr(v1, val_h, 0.05)
            t2 = thr(S[s2], val_h, 0.05)

            def casc(i):
                a = v1.get(i)
                if a is None:
                    return None, False
                if a >= hi:
                    return 1, False
                if a < lo or i not in S[s2]:
                    return 0, False
                return int(S[s2][i] >= t2), True
            tt = [(r, *casc(r["item_id"])) for r in byset["test"]]
            tt = [x for x in tt if x[1] is not None]
            pr = [(r, *casc(r["item_id"])) for r in groups["tier_B|near_verbatim"]]
            pr = [x for x in pr if x[1] is not None]
            res["fusion_cascade"] = dict(stage1="__".join(s1), stage2="__".join(s2), band=[round(lo, 4), round(hi, 4)],
                                         codenet_test_escalated_share=round(float(np.mean([e for _, _, e in tt])), 3),
                                         codenet_test_human_fpr=round(float(np.mean([d for r, d, _ in tt if r["label"] == 0])), 3),
                                         codenet_test_ai_sensitivity=round(float(np.mean([d for r, d, _ in tt if r["label"] == 1])), 3),
                                         pck_tier_B_near_verbatim=boot_sens([d for _, d, _ in pr], [r["participant"] for r, _, _ in pr], rng),
                                         pck_escalated_share=round(float(np.mean([e for _, _, e in pr])), 3) if pr else None)
    res["non_finite_scores_dropped"] = DROPPED
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print("wrote", OUT, len(res["methods"]), "method configurations")


if __name__ == "__main__":
    main()
