r"""Extended learning-analytics and robustness analyses. Aggregates only.

  python code/analysis/tlt_la_extended.py

1. Learning-analytics comparison, extended: problem-stratified (Mantel-Haenszel) odds ratios, a logistic model with participant and problem
   fixed effects, bootstrap intervals for the learner-level rho, paired bootstrap of the gap difference (records minus
   detector), Structural GB within length terciles, and agreement of each detector label with the record label.
2. Unmatched submissions: distribution of best-match similarity.
3. Full-U, edited stratum: agreement with the reference.
4. Trace validation, hierarchical scoring: C2-C4 not applicable where no AI material exists.
5. Tier-B detection by provider and stage of the source answer; alias -> stage -> provider model ID.
Inputs: pseudonymised share data (items, scores, rq1 decisions, traces) and, for 5, the private linkage table and the
session records (read locally). Output: results/la_extended.json.
"""
import collections, csv, gzip, json, random, sys, zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT.parent / "data"
PRIV = Path("../private_data/datasets/audit")
ZIP = Path(r"D:\session-records.zip")
OUT = ROOT / "results/la_extended.json"
rng = np.random.default_rng(6321)
res = {}

items = pd.read_csv(SH / "items.csv", dtype={"participant": str})
pck = items[items.set == "pck"].copy()
val_h = items[(items.set == "val") & (items.label == 0)].item_id
S = collections.defaultdict(dict)
with gzip.open(SH / "scores.csv.gz", "rt", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        if r["input"] == "raw" and r["score"] not in ("", "nan", "inf", "-inf") and np.isfinite(float(r["score"])):
            S[(r["method"], r["regime"])][r["item_id"]] = float(r["score"])
DET = {"UniXcoder": ("unixcoder", "ext"), "Qwen + LoRA": ("qwenlora", "ext"), "DroidDetect": ("droid", "offshelf"),
       "Structural GB": ("structgb", "ext")}


def flags(m, rg):
    sc = S[(m, rg)]
    t = float(np.quantile([sc[i] for i in val_h if i in sc], 0.95))
    return {i: int(v >= t) for i, v in sc.items()}


pck["Records"] = ((pck.tier_B == 1) | (pck.b_chain == 1)).astype(int)
for k, (m, rg) in DET.items():
    f = flags(m, rg)
    pck[k] = pck.item_id.map(f)
pck["acc"] = (pck.verdict == "AC").astype(int)
L = ["Records"] + list(DET)
P = sorted(pck.participant.unique())
q1, q2 = np.quantile(pck.lines, [1 / 3, 2 / 3])
pck["terc"] = np.where(pck.lines <= q1, 1, np.where(pck.lines <= q2, 2, 3))


def gap(d, lab):
    a, b = d[d[lab] == 1].acc, d[d[lab] == 0].acc
    return a.mean() - b.mean() if len(a) and len(b) else np.nan


def mh_or(d, lab):
    num = den = 0.0
    for _, g in d.groupby("problem"):
        n = len(g)
        a = ((g[lab] == 1) & (g.acc == 1)).sum(); b = ((g[lab] == 1) & (g.acc == 0)).sum()
        c = ((g[lab] == 0) & (g.acc == 1)).sum(); dd = ((g[lab] == 0) & (g.acc == 0)).sum()
        num += a * dd / n; den += b * c / n
    return num / den if den else np.nan


def rho(d, lab):
    g = d.groupby("participant").agg(s=(lab, "mean"), a=("acc", "mean"))
    return spearmanr(g.s, g.a)[0]


byp = {p: pck[pck.participant == p] for p in P}
B = 2000
boot = collections.defaultdict(list)
for _ in range(B):
    d = pd.concat([byp[P[i]] for i in rng.integers(0, len(P), len(P))], ignore_index=True)
    for lab in L:
        boot[("gap", lab)].append(gap(d, lab)); boot[("rho", lab)].append(rho(d, lab)); boot[("mh", lab)].append(mh_or(d, lab))
    for lab in L[1:]:
        boot[("dgap", lab)].append(gap(d, "Records") - gap(d, lab))
        boot[("drho", lab)].append(rho(d, "Records") - rho(d, lab))


def ci(x):
    x = np.array([v for v in x if np.isfinite(v)])
    return [round(float(np.quantile(x, 0.025)), 3), round(float(np.quantile(x, 0.975)), 3)]


# fixed-effects logistic model (participant and problem dummies); separation-safe through a small ridge penalty
import statsmodels.api as sm
fe = {}
for lab in L:
    X = pd.get_dummies(pck[["participant", "problem"]].astype(str), drop_first=True).astype(float)
    X.insert(0, "lab", pck[lab].astype(float)); X = sm.add_constant(X)
    fit = sm.Logit(pck.acc.astype(float), X).fit_regularized(alpha=0.01, L1_wt=0.0, disp=0)
    fe[lab] = round(float(np.exp(fit.params["lab"])), 3)

t12 = {}
for lab in L:
    t12[lab] = dict(gap=round(float(gap(pck, lab)), 3), gap_ci=ci(boot[("gap", lab)]),
                    mh_or_within_problem=round(float(mh_or(pck, lab)), 3), mh_or_ci=ci(boot[("mh", lab)]),
                    fe_or_participant_problem=fe[lab],
                    rho=round(float(rho(pck, lab)), 3), rho_ci=ci(boot[("rho", lab)]))
    if lab != "Records":
        t12[lab].update(gap_diff_records_minus=round(float(gap(pck, "Records") - gap(pck, lab)), 3),
                        gap_diff_ci=ci(boot[("dgap", lab)]),
                        rho_diff_records_minus=round(float(rho(pck, "Records") - rho(pck, lab)), 3),
                        rho_diff_ci=ci(boot[("drho", lab)]),
                        agreement_with_record_label=round(float((pck[lab] == pck.Records).mean()), 3),
                        flagged_among_record_ai=round(float(pck[pck.Records == 1][lab].mean()), 3),
                        flagged_among_unknown=round(float(pck[pck.Records == 0][lab].mean()), 3))
terc = {}
for t in (1, 2, 3):
    d = pck[pck.terc == t]
    terc[t] = dict(n=int(len(d)), accepted_rate=round(float(d.acc.mean()), 3),
                   **{lab: dict(gap=round(float(gap(d, lab)), 3), flagged=round(float(d[lab].mean()), 3)) for lab in ("Records", "Structural GB")})
res["la_table_extended"] = dict(by_label=t12, by_length_tercile=terc, tercile_cuts=[float(q1), float(q2)],
                                 note="gap = Accepted rate AI-labelled minus other; MH OR stratified by problem; FE OR from "
                                      "logistic regression with participant and problem dummies (ridge alpha 0.01); "
                                      "participant-clustered bootstrap, 2,000 resamples, seed 6321.")

# 2. unmatched similarity
um = pck[pck.stratum == "none"].similarity
res["unmatched_similarity"] = dict(n=int(len(um)), median=round(float(um.median()), 3),
                                   below_0_4=int((um < 0.4).sum()), from_0_4_to_0_6=int(((um >= 0.4) & (um < 0.6)).sum()),
                                   from_0_6_to_0_8=int(((um >= 0.6) & (um < 0.8)).sum()))

# 3. Full-U edited stratum and per-stratum agreement
rq = pd.read_csv(SH / "rq1_decisions.csv")
fu = rq[(rq.configuration == "Full-U") & (rq.reference_decision != "unresolved")]


def agrees(r):
    if r.decision != r.reference_decision:
        return False
    return r.claim != "C3" or r.decision != "supported" or r.mechanism == r.reference_mechanism


res["fullu_by_stratum"] = {s: dict(cases=int(g.case.nunique()), resolved_ref=int(len(g)), agree=int(g.apply(agrees, axis=1).sum()))
                           for s, g in fu.groupby("stratum")}
res["fullu_by_assignment"] = {s: dict(resolved_ref=int(len(g)), agree=int(g.apply(agrees, axis=1).sum()))
                              for s, g in fu.groupby("assignment")}

# 4. trace hierarchical scoring (C2-C4 not applicable without AI material)
sys.path.insert(0, str(ROOT / "tools"))
key = pd.concat([pd.read_csv(SH / "traces" / k) for k in ("key.csv", "key_ext.csv")])
key = key[key.run_ok == True]  # noqa: E712
scen = dict(zip(key.packet_id, key.scenario))
NEG = {"S5", "S8", "S9", "S10", "S11", "S12"}
MECH = {"S1": "proposal_applied", "S2": "editor_insertion", "S3": "incremental", "S4": "proposal_applied",
        "S6": "editor_insertion", "S7": "editor_insertion"}
cnt = collections.Counter()
for coder in (1, 2):
    for f in (f"ref{coder}_trace_01.jsonl", f"ref{coder}_trace_ext_01.jsonl"):
        for line in open(SH / "traces" / "out" / f, encoding="utf-8"):
            r = json.loads(line)
            s = scen.get(r.get("case_id")) if "claim" in r else None
            if s is None:
                continue
            if s in NEG:
                if r["claim"] != "C1":
                    continue
                o = {"contradicted": "correct", "unresolved": "unresolved", "supported": "wrong"}[r["decision"]]
            else:
                d = r["decision"]
                if r["claim"] == "C3" and d == "supported":
                    o = "correct" if r.get("mechanism") == MECH.get(s) else "wrong"
                else:
                    o = {"supported": "correct", "unresolved": "unresolved", "contradicted": "wrong"}[d]
            cnt[o] += 1
res["trace_hierarchical"] = dict(cnt, decisions=sum(cnt.values()),
                                 note="AI-absent scenarios scored on C1 only; mechanism map as in tlt_trace_score.py. "
                                      "Check MECH against tlt_trace_score.py before citing.")

# 5. provider / stage of the source answer for tier-B near-verbatim
lab = pd.read_csv(PRIV / "tlt_labels.csv")
lk = pd.read_csv(PRIV / "submission_linkage.csv", encoding="utf-8-sig")
z = zipfile.ZipFile(ZIP)
req = {}
alias = collections.defaultdict(lambda: dict(stage=collections.Counter(), provider=collections.Counter(), model=collections.Counter()))
with z.open("data/analysis/proxy_calls.jsonl") as f:
    for line in f:
        r = json.loads(line)
        if r.get("operation") or r.get("status") != "success" or not r.get("chat_request_id"):
            continue
        req.setdefault(r["chat_request_id"], (r.get("attempt_provider"), r.get("attempt_selected_stage")))
        a = alias[r.get("model_alias")]
        a["stage"][r.get("attempt_selected_stage")] += 1; a["provider"][r.get("attempt_provider")] += 1
        a["model"][r.get("provider_response_model") or r.get("response_model") or r.get("model")] += 1
m = lab.merge(lk[["submission_id", "best_match_chat_request_id"]], on="submission_id")
m = m[(m.tier_B == 1) & (m.stratum == "near_verbatim")]
m["provider"] = m.best_match_chat_request_id.map(lambda x: req.get(x, (None, None))[0])
m["stage"] = m.best_match_chat_request_id.map(lambda x: req.get(x, (None, None))[1])
# item ids in the share data are pseudonymised; join through the private submission id map used by the export
import random as _r
_lab = {str(r["submission_id"]): r for r in csv.DictReader(open(PRIV / "tlt_labels.csv", encoding="utf-8"))}
_g = _r.Random(20261122)
_parts = sorted({r["participant"] for r in _lab.values()}); _g.shuffle(_parts)
_subs = sorted(_lab, key=int); _g.shuffle(_subs)
idmap = {int(sid): f"pck_S{i + 1:04d}" for i, sid in enumerate(_subs)}   # same derivation as tlt_share_export.py
prov = {}
if idmap:
    for k in L[1:]:
        f = {sid: pck.set_index("item_id")[k].get(iid) for sid, iid in idmap.items()}
        m[k] = m.submission_id.map(f)
    for col in ("provider", "stage"):
        prov[col] = {str(v): dict(n=int(len(g)), **{k: round(float(g[k].mean()), 3) for k in L[1:]})
                     for v, g in m.groupby(col)}
res["tierB_by_source"] = dict(n=int(len(m)), linked=int(m.provider.notna().sum()),
                              provider_counts=m.provider.value_counts().to_dict(),
                              stage_counts={str(k): int(v) for k, v in m.stage.value_counts().sort_index().items()},
                              detection=prov or "item-id map unavailable; see tlt_la_extended notes")
res["alias_stage_model"] = {k: dict(stage=dict(v["stage"]), provider=dict(v["provider"]), model=dict(v["model"]))
                            for k, v in alias.items() if k}
OUT.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
print(json.dumps(res, indent=1, default=str))
