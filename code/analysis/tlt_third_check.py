r"""independent third adjudication of the decisions that the reduced packet (E1+E+T) made where
the full-record reference was unresolved (9 decisions). Aggregates only.

  python code/analysis/tlt_third_check.py build    # blind batch: disputed cases + decoys
  python code/analysis/tlt_third_check.py score    # after the third adjudicator has written its codes

Design: every case with at least one such decision is put, with random decoy cases (other main-study cases, half with
any unresolved reference claim), into one shuffled batch of full-record reference packets, copied under new random IDs.
A third adjudicator (not one of the reference adjudicators, configuration reviewers or the consensus coder)
decides C1-C4 on each packet with rubric v0.3, without knowing which cases or claims are in question. Its decisions on
the disputed claims are compared with the reference (unresolved) and the reduced-packet decision.
Private files: datasets/audit/tlt_rq4_main/third_check/ (packets, batch, key). Output (aggregate):
results/third_check.json.
"""
from __future__ import annotations

import collections
import csv
import json
import random
import shutil
import sys
from pathlib import Path

CFG = sys.argv[sys.argv.index("--config") + 1] if "--config" in sys.argv else "E1+E+T"   # also Full-U
sys.argv = [sys.argv[0], *[a for a in sys.argv[1:] if a not in ("--config", CFG)], "--main", "--ext"]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tlt_rq4_score as s  # noqa: E402

D = s.PRIV / ("third_check" if CFG == "E1+E+T" else f"third_check_{CFG.replace('-', '')}")
OUT = s.OUT / ("third_check.json" if CFG == "E1+E+T" else f"third_check_{CFG.replace('-', '')}.json")
N_DECOY = 10


def disputed():
    key, ck_all, r1, r2, ca, cb, cons = s.load()
    ref = {(k["case"], cl): (s.final(r1, r2, cons, k["reference_id"], cl) or {}) for k in key for cl in s.CLAIMS}
    rows = []
    for c in ck_all:
        if c["config"] != CFG:
            continue
        for cl in s.CLAIMS:
            rd = ref[(c["case"], cl)].get("decision")
            f = s.final(ca, cb, cons, c["packet_id"], cl) or {}
            if rd == "unresolved" and f.get("decision") in ("supported", "contradicted"):
                rows.append(dict(case=c["case"], claim=cl, reduced=f.get("decision"), reduced_mechanism=f.get("mechanism") or ""))
    return key, ref, rows


def build():
    key, ref, rows = disputed()
    cases = sorted({r["case"] for r in rows})
    rng = random.Random(6421 if CFG == "E1+E+T" else 6422)
    others = [k for k in key if k["case"] not in cases]
    unres = [k for k in others if any(ref[(k["case"], cl)].get("decision") == "unresolved" for cl in s.CLAIMS)]
    res_ = [k for k in others if k not in unres]
    decoys = rng.sample(unres, N_DECOY // 2) + rng.sample(res_, N_DECOY - N_DECOY // 2)
    kb = {k["case"]: k for k in key}
    sel = [kb[c] for c in cases] + decoys
    rng.shuffle(sel)
    if D.exists():
        shutil.rmtree(D)
    (D / "packets").mkdir(parents=True)
    used, kk = set(), []
    for k in sel:
        while True:
            nid = f"X{rng.getrandbits(24):06x}"
            if nid not in used:
                used.add(nid)
                break
        src = (s.PRIV / "reference" / f"{k['reference_id']}.md").read_text(encoding="utf-8")
        first, rest = src.split("\n", 1)
        (D / "packets" / f"{nid}.md").write_text(f"# Reference packet (full record) {nid}\n{rest}", encoding="utf-8")
        kk.append(dict(packet_id=nid, case=k["case"], disputed=int(k["case"] in cases)))
    with open(D / "key.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(kk[0]))
        w.writeheader()
        w.writerows(kk)
    with open(D / "disputed.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (D / "batch.txt").write_text("".join(str(D / "packets" / f"{k['packet_id']}.md") + "\n" for k in kk), encoding="utf-8")
    print(json.dumps(dict(disputed_decisions=len(rows), disputed_cases=len(cases), decoys=len(decoys), packets=len(kk),
                          by_claim=dict(collections.Counter(f"{r['claim']}:{r['reduced']}" for r in rows)))))


def score():
    key, ref, rows = disputed()
    kk = list(csv.DictReader(open(D / "key.csv", encoding="utf-8")))
    case_of = {k["packet_id"]: k["case"] for k in kk}
    third = {}
    for line in open(D / "third.jsonl", encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            if r.get("claim"):
                third[(case_of[r["case_id"]], r["claim"])] = r
    out = collections.Counter()
    detail = []
    for r in rows:
        t = third.get((r["case"], r["claim"])) or {}
        td = t.get("decision", "missing")
        same = td == r["reduced"] and (r["claim"] != "C3" or r["reduced"] != "supported" or t.get("mechanism") == r["reduced_mechanism"])
        verdict = "agrees_with_reduced" if same else ("agrees_with_reference_unresolved" if td == "unresolved" else "other")
        out[verdict] += 1
        detail.append(dict(claim=r["claim"], reduced=r["reduced"], third=td, verdict=verdict))
    # decoys: agreement of the third adjudicator with the reference (decision, mechanism for C3)
    dec = collections.Counter()
    for k in kk:
        if k["disputed"] == "1":
            continue
        for cl in s.CLAIMS:
            rf, t = ref[(k["case"], cl)], third.get((k["case"], cl)) or {}
            ok = rf.get("decision") == t.get("decision") and (cl != "C3" or rf.get("decision") != "supported" or rf.get("mechanism") == t.get("mechanism"))
            dec["agree" if ok else "differ"] += 1
    res = dict(note=("Independent third adjudication (blind to which cases and claims were disputed, "
                     "with decoys) of the decisions that E1+E+T reviewers made where the full-record reference was unresolved."),
               disputed_decisions=len(rows), outcome=dict(out), by_decision=detail, decoy_agreement_with_reference=dict(dec))
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    {"build": build, "score": score}[sys.argv[1]]()
