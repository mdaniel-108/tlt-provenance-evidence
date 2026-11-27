"""Reproduce the detector results (Table VIII, the length, new-token and deduplication checks) from data/.

  python reproduce/detection.py

Inputs: data/items.csv, data/scores.csv.gz. Thresholds: 0.95 quantile of CodeNet validation human scores (Eq. 5).
Intervals: participant-clustered bootstrap, 2,000 resamples (the paper's seed order differs, so intervals can move in
the third decimal). Each value is compared with results/detection.json.
"""
import collections, csv, gzip, json, random
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score

R = Path(__file__).resolve().parents[1]
items = list(csv.DictReader(open(R / "data" / "items.csv", encoding="utf-8")))
S = collections.defaultdict(dict)
with gzip.open(R / "data" / "scores.csv.gz", "rt", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        if r["score"] not in ("", "nan", "inf", "-inf"):
            v = float(r["score"])
            if np.isfinite(v):
                S[(r["method"], r["regime"], r["input"])][r["item_id"]] = v
by = collections.defaultdict(list)
for r in items:
    by[r["set"]].append(r)
pck = by["pck"]
val_h = [r["item_id"] for r in by["val"] if r["label"] == "0"]
G = {"tier_B_near_verbatim": [r for r in pck if r["stratum"] == "near_verbatim" and r["tier_B"] == "1"],
     "tier_A_near_verbatim": [r for r in pck if r["stratum"] == "near_verbatim" and r["tier_A"] == "1"],
     "b_chain_near_verbatim": [r for r in pck if r["stratum"] == "near_verbatim" and r["b_chain"] == "1"],
     "tier_B_edited": [r for r in pck if r["stratum"] == "edited" and r["tier_B"] == "1"],
     "unknown": [r for r in pck if r["unknown"] == "1"]}
REF = json.load(open(R / "results" / "detection.json"))["methods"]
rng = random.Random(6314)


def thr(sc):
    return float(np.quantile(sorted(sc[i] for i in val_h if i in sc), 0.95))


def auc(sc, rows):
    y = [int(r["label"]) for r in rows if r["item_id"] in sc]
    return roc_auc_score(y, [sc[r["item_id"]] for r in rows if r["item_id"] in sc])


def boot(flags, parts):
    g = collections.defaultdict(list)
    for f, p in zip(flags, parts):
        g[p].append(f)
    k = list(g)
    bs = [np.mean([x for _ in k for x in g[k[rng.randrange(len(k))]]]) for _ in range(2000)]
    return np.quantile(bs, 0.025), np.quantile(bs, 0.975)


def flags(m, regs, inp, rows):
    out, pp = [], []
    for r in rows:
        for rg in regs:
            sc = S.get((m, rg, inp), {})
            if r["item_id"] in sc:
                out.append(int(sc[r["item_id"]] >= thr(sc)))
                pp.append(r["participant"])
    return out, pp


ROWS = [("Token LR", "tokenlr", "ext"), ("Structural GB", "structgb", "ext"), ("Log-likelihood", "loglik", "zeroshot"),
        ("Log-rank", "logrank", "zeroshot"), ("Binoculars", "binoculars", "zeroshot"), ("DroidDetect", "droid", "offshelf"),
        ("UniXcoder", "unixcoder", "ext"), ("Qwen + LoRA", "qwenlora", "ext"), ("Dolos", "dolos", "refs"),
        ("Token LR (in-domain)", "tokenlr", "pck0"), ("Structural GB (in-domain)", "structgb", "pck0"),
        ("UniXcoder (in-domain)", "unixcoder", "pck0"), ("Qwen + LoRA (in-domain)", "qwenlora", "pck0")]
print(f"{'Method':27s} {'AUC unseen':>10s} {'seen':>6s} {'hum.FPR':>7s} {'tierB NV [95% CI]':>22s} {'tierA':>6s} {'Bchain':>6s} {'B edit':>6s} {'unknown':>7s}  check")
bad = 0
for name, m, reg in ROWS:
    regs = ["pck0", "pck1", "pck2"] if reg.startswith("pck") else [reg]
    base = S[(m, regs[0], "raw")]
    t = thr(base)
    a_u, a_s = auc(base, by["test"]), auc(base, by["seen_test"])
    fpr = np.mean([base[r["item_id"]] >= t for r in by["test"] if r["label"] == "0" and r["item_id"] in base])
    v = {g: flags(m, regs, "raw", rows) for g, rows in G.items()}
    sens = {g: np.mean(f) for g, (f, _) in v.items()}
    lo, hi = boot(*v["tier_B_near_verbatim"])
    ref = REF[f"{m}__{regs[0]}__raw"]
    ok = (abs(a_u - ref["codenet_test_unseen_problems"]["roc_auc"]) < 1e-3
          and abs(sens['tier_B_near_verbatim'] - ref["pck"]["tier_B|near_verbatim|fpr5"]["sensitivity"]) < 1e-3
          and abs(sens['unknown'] - ref["pck"]["unknown|all|fpr5"]["sensitivity"]) < 1e-3)
    bad += not ok
    print(f"{name:27s} {a_u:10.3f} {a_s:6.3f} {fpr:7.3f} {sens['tier_B_near_verbatim']:8.3f} [{lo:.3f}, {hi:.3f}]"
          f" {sens['tier_A_near_verbatim']:6.3f} {sens['b_chain_near_verbatim']:6.3f} {sens['tier_B_edited']:6.3f} {sens['unknown']:7.3f}  {'OK' if ok else 'DIFF'}")

# length terciles, new-token bands and deduplicated units for the four strongest external detectors
tb = G["tier_B_near_verbatim"]
q1, q2 = np.quantile([int(r["lines"]) for r in tb], [1 / 3, 2 / 3])
print(f"\nTier-B near-verbatim (n={len(tb)}); tercile cut points {q1:.0f} and {q2:.0f} lines")
bands = [("0.5-0.7", 0.5, 0.7), ("0.7-0.9", 0.7, 0.9), ("0.9-1.0", 0.9, 1.01)]
print(f"{'Method':15s} {'short':>6s} {'medium':>6s} {'long':>6s} | " + " ".join(f"{b:>8s}" for b, _, _ in bands) + " | per unit")
for name, m, reg in [("Structural GB", "structgb", "ext"), ("DroidDetect", "droid", "offshelf"), ("UniXcoder", "unixcoder", "ext"), ("Qwen + LoRA", "qwenlora", "ext")]:
    sc = S[(m, reg, "raw")]
    t = thr(sc)
    f = {r["item_id"]: int(sc[r["item_id"]] >= t) for r in tb if r["item_id"] in sc}
    ln = {r["item_id"]: int(r["lines"]) for r in tb}
    ns = {r["item_id"]: float(r["new_share"]) for r in tb if r["new_share"]}
    terc = [np.mean([f[i] for i in f if lo < ln[i] <= hi]) for lo, hi in ((-1, q1), (q1, q2), (q2, 1e9))]
    bs = [np.mean([f[i] for i in f if i in ns and lo <= ns[i] < hi]) for _, lo, hi in bands]
    units = collections.defaultdict(list)
    for r in tb:
        if r["item_id"] in f and r["dedup_unit"]:
            units[r["dedup_unit"]].append(f[r["item_id"]])
    per_unit = np.mean([max(v) for v in units.values()])
    print(f"{name:15s} {terc[0]:6.2f} {terc[1]:6.2f} {terc[2]:6.2f} | " + " ".join(f"{b:8.2f}" for b in bs) + f" | {per_unit:.3f} ({len(units)} units)")
print("\nAll rows match results/detection.json." if not bad else f"\n{bad} row(s) differ from results/detection.json.")
