r"""Scoring of the record-configuration study (claim rubric, section 4). Aggregates only.

  python code/analysis/tlt_rq4_score.py items   # write consensus items (disagreements) for the reference and config stages
  python code/analysis/tlt_rq4_score.py score   # agreement, 3x3 tables, resolution, cost -> results/rq4_main.json (with --main)

**Inputs** (outside Git): private_data/datasets/audit/tlt_rq4/
- key.csv, config_key.csv;
- out/ref1_*.jsonl, ref2_*, cfgA_*, cfgB_*;
- consensus/out_*.jsonl.

**Agreement** is computed on `decision`, plus `mechanism` for C3. Strength is reported separately.
"""
from __future__ import annotations

import collections
import csv
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIV = Path("../private_data/datasets/audit/tlt_rq4")
OUT = ROOT / "results"
CLAIMS = ["C1", "C2", "C3", "C4"]
DEC = ["supported", "contradicted", "unresolved"]
TYPES = {"R-A": "assistant output", "R-U": "free-text prompts and attached source files", "R-P": "proposal events",
         "R-E": "keystroke-level edits, saves and source captures", "R-T": "fine-grained timestamps"}
CONFIGS = {
    "E0": [], "E1": ["R-A"], "E1u": ["R-A", "R-U"], "E1u+P": ["R-A", "R-U", "R-P"], "E1u+T": ["R-A", "R-U", "R-T"],
    "Full-A": ["R-U", "R-P", "R-E", "R-T"], "Full-U": ["R-A", "R-P", "R-E", "R-T"], "Full-P": ["R-A", "R-U", "R-E", "R-T"],
    "Full-E": ["R-A", "R-U", "R-P", "R-T"], "Full-T": ["R-A", "R-U", "R-P", "R-E"], "Full": list(TYPES),
    "E1+E+T": ["R-A", "R-E", "R-T"],
}
if "--main" in sys.argv:   # main study
    PRIV = PRIV.parent / "tlt_rq4_main"
    OUTNAME = "rq4_main.json"
else:
    OUTNAME = "rq4_sample1.json"


def rows(pattern):
    out = {}
    for f in sorted((PRIV / "out").glob(pattern)):
        for line in open(f, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("claim") in CLAIMS:
                out[(r["case_id"], r["claim"])] = r
            elif "effort" in r:
                out[(r["case_id"], "effort")] = r
    return out


def code(r):
    if r is None:
        return None
    d = str(r.get("decision", "")).strip().lower()
    return (d, str(r.get("mechanism", "")).strip().lower()) if r.get("claim") == "C3" else (d,)


def ac1(pairs):
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    cats = sorted({x for p in pairs for x in p})
    if len(cats) < 2:
        return 1.0
    pi = {k: (sum(a == k for a, _ in pairs) + sum(b == k for _, b in pairs)) / (2 * n) for k in cats}
    pe = sum(v * (1 - v) for v in pi.values()) / (len(cats) - 1)
    return round((po - pe) / (1 - pe), 3) if pe < 1 else 1.0


def cpath(c):
    return PRIV / c.get("dir", "config") / f"{c['packet_id']}.md"


def load():
    key = list(csv.DictReader(open(PRIV / "key.csv", encoding="utf-8")))
    ck = list(csv.DictReader(open(PRIV / "config_key.csv", encoding="utf-8")))
    ext = PRIV / "config_key_ext.csv"
    if ext.exists() and "--ext" in sys.argv:   # E1+E+T for all main cases (scored separately)
        ck += [dict(r, dir="config_ext", ext="1") for r in csv.DictReader(open(ext, encoding="utf-8"))]
    r1, r2, ca, cb = rows("ref1_*.jsonl"), rows("ref2_*.jsonl"), rows("cfgA_*.jsonl"), rows("cfgB_*.jsonl")
    cons = {}
    for f in sorted((PRIV / "consensus").glob("out_*.jsonl")):
        for line in open(f, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                cons[(r["case_id"], r.get("claim") or r.get("item"))] = r
    return key, ck, r1, r2, ca, cb, cons


def items():
    key, ck, r1, r2, ca, cb, _ = load()
    rng = random.Random(64)
    units = [] if "--ext" in sys.argv else [(k["reference_id"], "reference", "Full", PRIV / "reference" / f"{k['reference_id']}.md", r1, r2) for k in key]
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None   # a second extension (Full-U)
    units += [(c["packet_id"], "config", c["config"], cpath(c), ca, cb) for c in ck
              if ("--ext" not in sys.argv or c.get("ext")) and (only is None or c["config"] == only)]
    (PRIV / "consensus").mkdir(exist_ok=True)
    out = []
    pre = "items_ext_" if "--ext" in sys.argv else "items_"
    if only:
        pre = f"items_ext_{only.replace('+', 'p').replace('-', '')}_"
        _, _, _, _, _, _, cons_ = load()
        units = [u for u in units if not any((u[0], cl) in cons_ for cl in CLAIMS)]
    for pid, stage, cfg, path, a, b in units:
        for cl in CLAIMS:
            x, y = a.get((pid, cl)), b.get((pid, cl))
            if x and y and code(x) != code(y):
                if rng.random() < 0.5:
                    x, y = y, x
                keep = lambda r: {k: r.get(k) for k in ("decision", "strength", "mechanism", "edit_lineage", "confidence", "evidence_ref") if k in r}
                out.append(dict(case_id=pid, stage=stage, config=cfg, item=cl, packet=str(path), code_x=keep(x), code_y=keep(y)))
    # batches of at most 300 KB of distinct packets, one configuration per batch
    by = collections.defaultdict(list)
    for it in out:
        by[it["config"]].append(it)
    n = 0
    for cfg, its in sorted(by.items()):
        cur, size, seen = [], 0, set()
        for it in sorted(its, key=lambda i: i["case_id"]):
            s = 0 if it["case_id"] in seen else Path(it["packet"]).stat().st_size
            if cur and size + s > 300 * 1024 and it["case_id"] not in seen:
                n += 1
                (PRIV / "consensus" / f"{pre}{n:02d}.jsonl").write_text("".join(json.dumps(i) + "\n" for i in cur), encoding="utf-8")
                cur, size, seen = [], 0, set()
                s = Path(it["packet"]).stat().st_size
            cur.append(it)
            size += s
            seen.add(it["case_id"])
        if cur:
            n += 1
            (PRIV / "consensus" / f"{pre}{n:02d}.jsonl").write_text("".join(json.dumps(i) + "\n" for i in cur), encoding="utf-8")
    print(len(out), "disagreement items in", n, "batches")


def final(a, b, cons, pid, cl):
    x, y = a.get((pid, cl)), b.get((pid, cl))
    if x and y and code(x) == code(y):
        return x
    return cons.get((pid, cl))


def clopper_pearson(k, n, a=0.05):
    from scipy.stats import beta
    lo = 0.0 if k == 0 else beta.ppf(a / 2, k, n - k + 1)
    hi = 1.0 if k == n else beta.ppf(1 - a / 2, k + 1, n - k)
    return [round(float(lo), 3), round(float(hi), 3)]


def coverage(key, ck, ref, ca, cb, cons, mech=False):
    """Absolute coverage, transitions from unresolved reference decisions,
    abstention-error, exact and participant-clustered intervals, paired packet sizes, device-archive effect."""
    # mech=True (a supported C3 decision counts as agreeing only when the mechanism also matches;
    # a supported C3 with another mechanism counts as "opposite" (wrong mechanism).
    def dk(r, cl):
        r = r or {}
        d = r.get("decision", "pending")
        return f"supported:{r.get('mechanism')}" if (mech and cl == "C3" and d == "supported") else d
    RES = lambda x: x == "contradicted" or str(x).startswith("supported")
    kb = {k["case"]: k for k in key}
    out = {"configurations": {}}
    rng = random.Random(6399)
    for cfg in sorted({c["config"] for c in ck}):
        pk = [c for c in ck if c["config"] == cfg]
        d = {}
        pooled = []          # (participant, agree?) over reference-resolved decisions
        for cl in CLAIMS:
            n = len(pk)
            cd = [(dk(ref[(c["case"], cl)], cl), dk(final(ca, cb, cons, c["packet_id"], cl), cl), kb[c["case"]]["participant"]) for c in pk]
            res_here = sum(1 for _, x, _ in cd if RES(x))
            agree = sum(1 for r, x, _ in cd if RES(r) and x == r)
            opposite = sum(1 for r, x, _ in cd if RES(r) and RES(x) and x != r)
            lost = sum(1 for r, x, _ in cd if RES(r) and x == "unresolved")
            ru = [x.split(":")[0] for r, x, _ in cd if r == "unresolved"]
            pooled += [(pt, x == r) for r, x, pt in cd if RES(r)]
            d[cl] = dict(cases=n, resolved_here=res_here, resolved_here_share=round(res_here / n, 3) if n else None,
                         reference_resolved=agree + opposite + lost, agree=agree, opposite=opposite, lost_to_unresolved=lost,
                         reference_unresolved=len(ru), from_unresolved=dict(collections.Counter(ru)),
                         new_support_when_reference_unresolved=sum(x == "supported" for x in ru),
                         new_contradiction_when_reference_unresolved=sum(x == "contradicted" for x in ru))
        k, n = sum(a for _, a in pooled), len(pooled)
        parts = sorted({p for p, _ in pooled})
        boots = []
        for _ in range(2000):
            smp = [rng.choice(parts) for _ in parts]
            xs = [a for p in smp for q, a in pooled if q == p]
            if xs:
                boots.append(sum(xs) / len(xs))
        boots.sort()
        d["pooled_resolved"] = dict(agree=k, of=n, share=round(k / n, 3) if n else None,
                                    exact_95=clopper_pearson(k, n) if n else None,
                                    one_sided_95_lower=clopper_pearson(k, n, 0.10)[0] if n else None,
                                    participant_bootstrap_95=[round(boots[int(0.025 * len(boots))], 3), round(boots[int(0.975 * len(boots)) - 1], 3)] if boots else None,
                                    participants=len(parts))
        # paired size against the full-record packet of the same case
        ratios, cs, rs = [], [], []
        for c in pk:
            a_ = cpath(c).stat().st_size
            b_ = (PRIV / "reference" / f"{kb[c['case']]['reference_id']}.md").stat().st_size
            cs.append(a_); rs.append(b_); ratios.append(a_ / b_)
        med = lambda v: sorted(v)[len(v) // 2]
        d["paired_size"] = dict(n=len(pk), median_config_kb=round(med(cs) / 1024, 1), median_full_kb_same_cases=round(med(rs) / 1024, 1),
                                median_ratio=round(med(ratios), 3))
        out["configurations"][cfg] = d
    # reference decisions by device archive
    dev = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for k in key:
        g = "with_device_archive" if k["device_archive"] in ("True", "true", "1") else "without_device_archive"
        for cl in CLAIMS:
            dev[g][cl][(ref[(k["case"], cl)] or {}).get("decision", "pending")] += 1
    out["reference_by_device_archive"] = {g: {cl: dict(c) for cl, c in v.items()} for g, v in dev.items()}
    out["cases_by_device_archive"] = dict(collections.Counter("with" if k["device_archive"] in ("True", "true", "1") else "without" for k in key))
    return out


def score():
    key, ck_all, r1, r2, ca, cb, cons = load()
    ck = [c for c in ck_all if not c.get("ext")]
    main = OUTNAME == "rq4_main.json"
    res = {"note": (("Main study: reference adjudicators 1 and 2; configuration "
                     "reviewers A and B; consensus coder. Stratified sample, so rates are not "
                     "population estimates.") if main else
                    ("First sample: reference adjudicators 1 and 2; configuration reviewers A and B; "
                     "consensus coder; "
                     "40 cases.")),
           "cases": len(key), "strata": dict(collections.Counter(k["stratum"] for k in key))}
    # agreement before consensus
    agr = {}
    for stage, a, b, ids in (("reference", r1, r2, [(k["reference_id"], "Full") for k in key]),
                             ("config", ca, cb, [(c["packet_id"], c["config"]) for c in ck])):
        for cl in CLAIMS:
            pr = [(code(a[(p, cl)]), code(b[(p, cl)])) for p, _ in ids if (p, cl) in a and (p, cl) in b]
            ps = [(a[(p, cl)].get("strength"), b[(p, cl)].get("strength")) for p, _ in ids if (p, cl) in a and (p, cl) in b]
            agr[f"{stage}_{cl}"] = dict(n=len(pr), raw=round(sum(x == y for x, y in pr) / len(pr), 3) if pr else None, ac1=ac1(pr),
                                        strength_raw=round(sum(x == y for x, y in ps) / len(ps), 3) if ps else None)
    res["agreement_before_consensus"] = agr
    # reference decisions
    ref = {}
    for k in key:
        for cl in CLAIMS:
            ref[(k["case"], cl)] = final(r1, r2, cons, k["reference_id"], cl)
    res["reference"] = {cl: dict(collections.Counter((ref[(k["case"], cl)] or {}).get("decision", "pending") for k in key)) for cl in CLAIMS}
    res["reference_strength"] = {cl: dict(collections.Counter((ref[(k["case"], cl)] or {}).get("strength", "pending") for k in key
                                                              if (ref[(k["case"], cl)] or {}).get("decision") in ("supported", "contradicted"))) for cl in CLAIMS}
    res["reference_C3_mechanism"] = dict(collections.Counter((ref[(k["case"], "C3")] or {}).get("mechanism", "pending") for k in key))
    by_stratum = collections.defaultdict(collections.Counter)
    for k in key:
        by_stratum[k["stratum"]][(ref[(k["case"], "C1")] or {}).get("decision", "pending")] += 1
    res["reference_C1_by_stratum"] = {s: dict(c) for s, c in by_stratum.items()}
    # configuration tables
    tabs = {}
    for cfg in sorted({c["config"] for c in ck}):
        pk = [c for c in ck if c["config"] == cfg]
        t = {}
        for cl in CLAIMS:
            m = collections.Counter()
            strength = collections.Counter()
            for c in pk:
                rd = (ref[(c["case"], cl)] or {}).get("decision", "pending")
                f = final(ca, cb, cons, c["packet_id"], cl) or {}
                cd = f.get("decision", "pending")
                m[f"{rd}->{cd}"] += 1
                if cd in ("supported", "contradicted"):
                    strength[f.get("strength", "none")] += 1
            resolved = [c for c in pk if (ref[(c["case"], cl)] or {}).get("decision") in ("supported", "contradicted")]
            agree = sum(1 for c in resolved if ((final(ca, cb, cons, c["packet_id"], cl) or {}).get("decision") == ref[(c["case"], cl)]["decision"]))
            lost = sum(1 for c in resolved if (final(ca, cb, cons, c["packet_id"], cl) or {}).get("decision") == "unresolved")
            wrong = len(resolved) - agree - lost
            t[cl] = dict(n=len(pk), table=dict(m), strength_of_resolved_decisions=dict(strength),
                         reference_resolved=len(resolved), agree_with_reference=agree, unresolved_here_resolved_by_full=lost,
                         opposite_or_pending=wrong,
                         reference_unresolved_cases=sum(1 for c in pk if (ref[(c["case"], cl)] or {}).get("decision") == "unresolved"))
        sizes = sorted(cpath(c).stat().st_size for c in pk)
        t["cost"] = dict(median_packet_kb=round(sizes[len(sizes) // 2] / 1024, 1),
                         records_retained=CONFIGS[cfg], privacy_indicators=[TYPES[x] for x in CONFIGS[cfg]] + ["submitted source code (core)"])
        eff = collections.Counter()
        for c in pk:
            for src in (ca, cb):
                e = src.get((c["packet_id"], "effort"))
                if e:
                    eff[e.get("effort")] += 1
        t["self_reported_effort"] = dict(eff)
        tabs[cfg] = t
    res["configurations"] = tabs
    res["coverage_checks"] = coverage(key, ck, ref, ca, cb, cons)
    res["mechanism_check"] = coverage(key, ck, ref, ca, cb, cons, mech=True)["configurations"]
    # extended configurations (E1+E+T, then Full-U) on all 177 cases
    for xc in sorted({c["config"] for c in ck_all if c.get("ext")}):
        ext = [c for c in ck_all if c.get("ext") and c["config"] == xc]
        allc = [c for c in ck if c["config"] == xc] + ext
        r = coverage(key, allc, ref, ca, cb, cons)["configurations"][xc]
        miss = sum(1 for c in ext for cl in CLAIMS if final(ca, cb, cons, c["packet_id"], cl) is None)
        pr = [(code(ca[(c["packet_id"], cl)]), code(cb[(c["packet_id"], cl)])) for c in ext for cl in CLAIMS
              if (c["packet_id"], cl) in ca and (c["packet_id"], cl) in cb]
        r["extension_packets"] = len(ext)
        r["extension_missing_decisions"] = miss
        r["extension_agreement_before_consensus"] = dict(n=len(pr), raw=round(sum(x == y for x, y in pr) / len(pr), 3) if pr else None, ac1=ac1(pr))
        res["coverage_checks"][f"{xc}_all_cases"] = r
        rm = coverage(key, allc, ref, ca, cb, cons, mech=True)["configurations"][xc]
        rm["followup_only"] = coverage(key, ext, ref, ca, cb, cons, mech=True)["configurations"][xc]["pooled_resolved"]
        # follow-up agreement split by whether the case's randomized configurations had shown its prompts
        withU = {"E1u", "E1u+P", "Full-A", "Full-P", "Full-E", "Full-T"}
        kcase = {k["case"]: k for k in key}
        seen = lambda c: bool(set(kcase[c["case"]]["configs"].split(";")) & withU)
        rm["followup_by_prior_prompt_exposure"] = {
            g: dict(cases=len(sub), **coverage(key, sub, ref, ca, cb, cons, mech=True)["configurations"][xc]["pooled_resolved"])
            for g, sub in (("seen_with_prompts", [c for c in ext if seen(c)]), ("never_seen_with_prompts", [c for c in ext if not seen(c)])) if sub}
        res["mechanism_check"][f"{xc}_all_cases"] = rm
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / OUTNAME).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    {"items": items, "score": score}[sys.argv[1]]()  # add --main for the main study
