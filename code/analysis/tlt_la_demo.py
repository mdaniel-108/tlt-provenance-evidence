r"""Learning-analytics demonstration (Table X): does the answer to a typical analytics question change when
AI use is labelled by a code-only detector instead of by the records?

  python code/analysis/tlt_la_demo.py

Input: data/items.csv and data/scores.csv.gz. Output: aggregates only,
results/la_demo.json. Thresholds as in the paper: 0.95 quantile of CodeNet validation human scores.
Record labels: AI-derived = tier B or B-chain (linked, mostly new or traced to an earlier answer); unknown otherwise.
"""
import collections, csv, gzip, json, os, random
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

SH = Path(__file__).resolve().parents[2] / "data"
OUT = Path(os.environ.get("LA_OUT", Path(__file__).resolve().parents[2] / "results" / "la_demo.json"))
items = list(csv.DictReader(open(SH / "items.csv", encoding="utf-8")))
S = collections.defaultdict(dict)
with gzip.open(SH / "scores.csv.gz", "rt", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        if r["input"] == "raw" and r["score"] not in ("", "nan", "inf", "-inf") and np.isfinite(float(r["score"])):
            S[(r["method"], r["regime"])][r["item_id"]] = float(r["score"])
val_h = [r["item_id"] for r in items if r["set"] == "val" and r["label"] == "0"]
pck = [r for r in items if r["set"] == "pck"]
rng = random.Random(6320)

DET = {"UniXcoder": ("unixcoder", "ext"), "Qwen + LoRA": ("qwenlora", "ext"), "DroidDetect": ("droid", "offshelf"),
       "Structural GB": ("structgb", "ext"), "Log-likelihood": ("loglik", "zeroshot")}


def flags(m, rg):
    sc = S[(m, rg)]
    t = float(np.quantile([sc[i] for i in val_h if i in sc], 0.95))
    return {i: int(v >= t) for i, v in sc.items()}


labels = {"Records": {r["item_id"]: int(r["tier_B"] == "1" or r["b_chain"] == "1") for r in pck}}
for k, (m, rg) in DET.items():
    f = flags(m, rg)
    labels[k] = {r["item_id"]: f[r["item_id"]] for r in pck if r["item_id"] in f}
acc = {r["item_id"]: int(r["verdict"] == "AC") for r in pck}
part = {r["item_id"]: r["participant"] for r in pck}
P = sorted(set(part.values()))


def acc_gap(lab, ids):
    a = [acc[i] for i in ids if lab.get(i) == 1]
    b = [acc[i] for i in ids if lab.get(i) == 0]
    return (np.mean(a) if a else np.nan), (np.mean(b) if b else np.nan), len(a), len(b)


def boot_gap(lab):
    byp = collections.defaultdict(list)
    for i in lab:
        byp[part[i]].append(i)
    out = []
    for _ in range(2000):
        ids = [i for _ in P for i in byp[P[rng.randrange(len(P))]]]
        a, b, _, _ = acc_gap(lab, ids)
        out.append(a - b)
    out = [x for x in out if np.isfinite(x)]
    return float(np.quantile(out, 0.025)), float(np.quantile(out, 0.975))


res = {"submission_level": {}, "participant_level": {}}
for k, lab in labels.items():
    a, b, na, nb = acc_gap(lab, list(lab))
    lo, hi = boot_gap(lab)
    res["submission_level"][k] = dict(accepted_rate_ai=round(a, 3), n_ai=na, accepted_rate_not=round(b, 3), n_not=nb,
                                      difference=round(a - b, 4), ci95=[round(lo, 4), round(hi, 4)])

# participant level: AI share and Accepted rate per participant
share = {k: {p: np.mean([lab[i] for i in lab if part[i] == p]) for p in P} for k, lab in labels.items()}
accr = {p: np.mean([acc[i] for i in acc if part[i] == p]) for p in P}
for k in labels:
    rho, pv = spearmanr([share[k][p] for p in P], [accr[p] for p in P])
    rr, _ = spearmanr([share[k][p] for p in P], [share["Records"][p] for p in P])
    res["participant_level"][k] = dict(
        rho_share_vs_accepted=round(float(rho), 2), p=round(float(pv), 3),
        rho_with_record_share=round(float(rr), 2),
        mean_abs_share_diff_vs_records=round(float(np.mean([abs(share[k][p] - share["Records"][p]) for p in P])), 3),
        share_range=[round(min(share[k].values()), 2), round(max(share[k].values()), 2)])

# per-learner profile from the records: near-verbatim / edited / unmatched, and Accepted rate within each
prof = []
for p in P:
    rows = [r for r in pck if r["participant"] == p]
    c = collections.Counter(r["stratum"] for r in rows)
    prof.append(dict(n=len(rows), near_verbatim=c["near_verbatim"], edited=c["edited"], unmatched=c["none"]))
nv = [x["near_verbatim"] / x["n"] for x in prof]
res["learner_profiles"] = dict(
    participants=len(P), submissions_per_participant=[min(x["n"] for x in prof), int(np.median([x["n"] for x in prof])), max(x["n"] for x in prof)],
    near_verbatim_share=dict(min=round(min(nv), 2), median=round(float(np.median(nv)), 2), max=round(max(nv), 2)),
    participants_with_any_edited=sum(x["edited"] > 0 for x in prof),
    participants_with_any_unmatched=sum(x["unmatched"] > 0 for x in prof),
    sorted_profiles=sorted([[x["near_verbatim"], x["edited"], x["unmatched"]] for x in prof], key=lambda v: -v[0] / sum(v)))
st = collections.defaultdict(list)
for r in pck:
    st[r["stratum"]].append(acc[r["item_id"]])
res["accepted_by_stratum"] = {k: dict(n=len(v), accepted_rate=round(float(np.mean(v)), 3)) for k, v in st.items()}
res["note"] = ("Aggregates only. Associations within one session; no causal or learning claim. Record label: tier B or "
               "B-chain = AI-derived. Detector label: flagged at the CodeNet-validation 5% threshold. Participant-clustered "
               "bootstrap, 2,000 resamples, seed 6320.")
OUT.write_text(json.dumps(res, indent=1))
print(json.dumps({k: v for k, v in res.items() if k != "learner_profiles"}, indent=1))
print(json.dumps({k: v for k, v in res["learner_profiles"].items() if k != "sorted_profiles"}, indent=1))
