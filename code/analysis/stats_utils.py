"""Shared small-sample-aware model fitting for the PCK analyses.

gee_fit() fits a GEE model (participant clusters, exchangeable working correlation) and
reports, for each term, three 95% intervals:
  - robust (sandwich) GEE;
  - bias-reduced (Mancl-DeRouen) sandwich, a small-sample correction for few clusters;
  - participant-cluster bootstrap: resample participants with replacement, refit, percentile.
With about 21 clusters the robust interval can be too narrow, so the bias-reduced and bootstrap
intervals are the primary ones to read. Binomial models are reported as odds ratios.

Fit accounting: every fit is classified. A bootstrap refit is usable
only if it converged and all parameters are finite; a non-converged refit is retried once with
maxiter=200 (documented policy). Failed, non-converged and non-finite refits are counted, never
used. A term's bootstrap interval is reported only if at least 90% of resamples are usable for it;
otherwise it is withheld (null) with the reason, so intervals are not built from a selected subset.
Non-finite values are written as null, never as Infinity.

If the main fit fails its convergence/finite checks, no estimate, interval or p-value is published
for any term (the bootstrap is not run). The |coefficient| > 15 rule is a stability screen, not a
separation test. The 90% rule is a conservative, disclosed reporting rule, not a coverage guarantee.
Bias-reduced (Mancl-DeRouen) SEs correct sandwich bias with few clusters; they do not fix separation.
"""
from __future__ import annotations

import collections
import math
import site
import sys
import warnings

sys.path.append(site.getusersitepackages())
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import statsmodels.api as sm  # noqa: E402
import statsmodels.formula.api as smf  # noqa: E402

BOOT, SEED = 499, 2026
MIN_USABLE = 0.90
EXTREME = 15.0   # stability screen: |coefficient| on a log or logit link beyond this is treated as not estimable.
# This is a disclosed numerical heuristic at the predictor scales used in these analyses (binary contrasts and
# log counts), not a diagnosis of separation; it is scale dependent and has no universal meaning.


def _fit(formula, df, family, cov_type="robust", maxiter=60):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return smf.gee(formula, groups="participant", data=df, family=family,
                       cov_struct=sm.cov_struct.Exchangeable()).fit(cov_type=cov_type, maxiter=maxiter)


def _ok(res) -> bool:
    return bool(getattr(res, "converged", True)) and bool(np.all(np.isfinite(res.params)))


def _fit_checked(formula, df, family):
    """Returns (params or None, status) with status in usable / non_converged / non_finite / failed."""
    try:
        r = _fit(formula, df, family)
        if not getattr(r, "converged", True):
            r = _fit(formula, df, family, maxiter=200)          # one retry, documented
    except Exception:
        return None, "failed"
    if not getattr(r, "converged", True):
        return None, "non_converged"
    if not np.all(np.isfinite(r.params)):
        return None, "non_finite"
    return r.params, "usable"


def _num(v):
    return round(float(v), 3) if v is not None and math.isfinite(v) else None


def gee_fit(formula: str, df: pd.DataFrame, family, boot: int = BOOT, seed: int = SEED) -> dict:
    m = _fit(formula, df, family)
    if not getattr(m, "converged", True):
        m = _fit(formula, df, family, maxiter=200)
    main_ok = _ok(m)
    if not main_ok:                                   # never publish output from a failed main fit
        expo0 = isinstance(family, sm.families.Binomial)
        terms = [{"term": t, "estimate": None, "robust_ci": [None, None], "robust_p": None,
                  "non_estimable": "main fit did not converge or has non-finite estimates",
                  "bootstrap_ci": None, "bootstrap_usable": 0} for t in m.params.index if t != "Intercept"]
        return {"formula": formula, "n": int(m.nobs), "clusters": int(df["participant"].nunique()),
                "main_fit_converged": False, "scale": "odds ratio" if expo0 else "coefficient",
                "bootstrap_requested": 0, "bootstrap_status": {}, "bootstrap_resamples": 0,
                "bootstrap_failed": 0, "terms": terms,
                "note": "Main fit failed its convergence/finite checks; all inferential output withheld."}
    try:
        mb = _fit(formula, df, family, cov_type="bias_reduced", maxiter=200)
        mb = mb if _ok(mb) else None
    except Exception:
        mb = None
    rng = np.random.default_rng(seed)
    parts = df["participant"].unique()
    groups = {p: df[df["participant"] == p] for p in parts}
    loglink = not isinstance(family, sm.families.Gaussian)
    draws, status = [], {"usable": 0, "non_converged": 0, "non_finite": 0, "failed": 0}
    extreme_draws = collections.Counter()
    for _ in range(boot):
        pick = rng.choice(parts, size=len(parts), replace=True)
        bd = pd.concat([groups[p].assign(participant=f"{p}#{i}") for i, p in enumerate(pick)], ignore_index=True)
        params, st = _fit_checked(formula, bd, family)
        status[st] += 1
        if params is not None:
            if loglink:
                bad = params.abs() > EXTREME
                for t in params.index[bad]:
                    extreme_draws[t] += 1
                params = params.mask(bad)               # that term is not estimable in this resample
            draws.append(params)
    bdf = pd.DataFrame(draws)
    expo = isinstance(family, sm.families.Binomial)

    def f(v):
        v = float(v)
        if not math.isfinite(v):
            return None
        if not expo:
            return v
        return math.exp(v) if v < 700 else None                 # overflow: not estimable, reported as null
    terms = []
    for t in m.params.index:
        if t == "Intercept":
            continue
        b, se = m.params[t], m.bse[t]
        fx = lambda v: _num(f(v))
        if loglink and abs(b) > EXTREME:
            terms.append({"term": t, "estimate": None, "robust_ci": [None, None], "robust_p": None,
                          "non_estimable": f"unstable estimate: |coefficient| {abs(b):.1f} > {EXTREME:.0f} (stability screen; possible separation)",
                          "bootstrap_ci": None, "bootstrap_usable": 0})
            continue
        row = {"term": t, "estimate": fx(b),
               "robust_ci": [fx(b - 1.96 * se), fx(b + 1.96 * se)], "robust_p": _num(m.pvalues[t])}
        if mb is not None:
            seb = mb.bse[t]
            row["bias_reduced_ci"] = [fx(b - 1.96 * seb), fx(b + 1.96 * seb)]
            row["bias_reduced_p"] = round(float(mb.pvalues[t]), 4) if math.isfinite(mb.pvalues[t]) else None
        usable = int(bdf[t].notna().sum()) if t in bdf else 0
        row["bootstrap_usable"] = usable
        if usable >= MIN_USABLE * boot:
            q = np.percentile(bdf[t].dropna(), [2.5, 97.5])
            row["bootstrap_ci"] = [fx(q[0]), fx(q[1])]
        else:
            row["bootstrap_ci"] = None
            row["bootstrap_note"] = (f"withheld: {usable}/{boot} usable resamples (< {MIN_USABLE:.0%}); "
                                     f"{extreme_draws.get(t, 0)} non-estimable for this term")
        terms.append(row)
    return {"formula": formula, "n": int(m.nobs), "clusters": int(df["participant"].nunique()),
            "main_fit_converged": main_ok, "scale": "odds ratio" if expo else "coefficient",
            "bootstrap_requested": boot, "bootstrap_status": status, "bootstrap_resamples": status["usable"],
            "bootstrap_failed": boot - status["usable"], "terms": terms,
            "note": "Read bias-reduced and bootstrap intervals first (few clusters). Bootstrap uses converged, finite refits only."}


def flat_terms(name: str, res: dict) -> list[dict]:
    out = []
    for t in res["terms"]:
        out.append({"model": name, "term": t["term"], "scale": res["scale"], "estimate": t["estimate"],
                    "robust_ci_low": t["robust_ci"][0], "robust_ci_high": t["robust_ci"][1], "robust_p": t["robust_p"],
                    "bias_reduced_ci_low": (t.get("bias_reduced_ci") or [None, None])[0],
                    "bias_reduced_ci_high": (t.get("bias_reduced_ci") or [None, None])[1],
                    "bias_reduced_p": t.get("bias_reduced_p"),
                    "bootstrap_ci_low": (t.get("bootstrap_ci") or [None, None])[0],
                    "bootstrap_ci_high": (t.get("bootstrap_ci") or [None, None])[1],
                    "bootstrap_usable": t.get("bootstrap_usable"), "bootstrap_requested": res.get("bootstrap_requested"),
                    "bootstrap_fits_converged_finite": (res.get("bootstrap_status") or {}).get("usable"),
                    "n": res["n"], "clusters": res["clusters"]})
    return out
