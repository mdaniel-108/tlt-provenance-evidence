"""Reproduce the record-configuration results (Tables VI and VII) from data/rq1_decisions.csv.

  python reproduce/records.py

Agreement A_c and coverage C_c as in Eq. (4); a C3 decision agrees only if the mechanism also matches. Exact
(Clopper-Pearson) 95% intervals. Compared with results/rq4_main.json.
"""
import collections, csv, json
from pathlib import Path

from scipy.stats import beta

R = Path(__file__).resolve().parents[1]
rows = list(csv.DictReader(open(R / "data" / "rq1_decisions.csv", encoding="utf-8")))
REF = json.load(open(R / "results" / "rq4_main.json"))["mechanism_check"]
RES = lambda d: d in ("supported", "contradicted")


def key(d, mech, claim):
    return f"{d}:{mech}" if claim == "C3" and d == "supported" else d


def cp(k, n):
    lo = 0.0 if k == 0 else beta.ppf(0.025, k, n - k + 1)
    hi = 1.0 if k == n else beta.ppf(0.975, k + 1, n - k)
    return lo, hi


def table(sel):
    t = collections.Counter()
    cases = set()
    for r in sel:
        cases.add(r["case"])
        ref = key(r["reference_decision"], r["reference_mechanism"], r["claim"])
        dec = key(r["decision"], r["mechanism"], r["claim"])
        t["decisions"] += 1
        t["resolved_here"] += RES(r["decision"])
        if RES(r["reference_decision"]):
            t["ref_resolved"] += 1
            t["agree"] += dec == ref
            t["lost"] += r["decision"] == "unresolved"
            t["wrong_mech"] += RES(r["decision"]) and dec != ref
        else:
            t["ref_unresolved"] += 1
            t["stayed"] += r["decision"] == "unresolved"
            t["new_support"] += r["decision"] == "supported"
            t["new_contra"] += r["decision"] == "contradicted"
    t["cases"] = len(cases)
    return t


print(f"{'Configuration':16s} {'cases':>5s} {'A_c agree [95% CI]':>24s} {'lost':>4s} {'wrong':>5s} {'stayed':>8s} {'new +/-':>7s} {'C_c':>9s}  check")
bad = 0
cfgs = sorted({r["configuration"] for r in rows})
for c in cfgs:
    for label, sel in ((c, [r for r in rows if r["configuration"] == c and r["assignment"] == "randomized"]),
                       (c + " (all 177)", [r for r in rows if r["configuration"] == c])):
        if label.endswith("(all 177)") and not any(r["assignment"] == "followup" for r in rows if r["configuration"] == c):
            continue
        t = table(sel)
        lo, hi = cp(t["agree"], t["ref_resolved"])
        refkey = c if not label.endswith("(all 177)") else f"{c}_all_cases"
        pr = REF[refkey]["pooled_resolved"]
        ok = pr["agree"] == t["agree"] and pr["of"] == t["ref_resolved"]
        bad += not ok
        print(f"{label:16s} {t['cases']:5d} {t['agree']:5d}/{t['ref_resolved']:<4d} [{lo:.2f}, {hi:.2f}] {t['lost']:4d} {t['wrong_mech']:5d}"
              f" {t['stayed']:4d}/{t['ref_unresolved']:<3d} {t['new_support']:3d}/{t['new_contra']:<3d} {t['resolved_here']:4d}/{t['decisions']:<4d}  {'OK' if ok else 'DIFF'}")
print("\nAll configurations match results/rq4_main.json." if not bad else f"\n{bad} configuration(s) differ.")
