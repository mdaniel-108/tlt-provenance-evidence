r"""E1+E+T C3 re-coded with an explicit abstention rule (proposal records withheld -> mechanism
not identifiable unless the records positively exclude a proposal). Aggregates only.

  python code/analysis/tlt_c3_abstain_score.py

Inputs: datasets/audit/tlt_rq4_main/c3_abstain/out/cfg{A,B}_c3_*.jsonl (configuration reviewers A and B, C3 only, all
177 E1+E+T packets). Compared with the full-record reference C3 (decision and mechanism) and with the original E1+E+T C3.
Output: results/c3_abstain.json
"""
import collections
import glob
import json
import sys
from pathlib import Path

sys.argv = ["x", "score", "--main", "--ext"]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tlt_rq4_score as s  # noqa: E402

OUT = s.OUT / "c3_abstain.json"


def lab(r):
    r = r or {}
    d = r.get("decision", "missing")
    return f"supported:{r.get('mechanism')}" if d == "supported" else d


def main():
    key, ck_all, r1, r2, ca, cb, cons = s.load()
    ref = {k["case"]: s.final(r1, r2, cons, k["reference_id"], "C3") for k in key}
    pk = {c["packet_id"]: c for c in ck_all if c["config"] == "E1+E+T"}
    new = {}
    for who in "AB":
        d = {}
        for f in glob.glob(str(s.PRIV / "c3_abstain" / "out" / f"cfg{who}_c3_*.jsonl")):
            for line in open(f, encoding="utf-8"):
                if line.strip():
                    r = json.loads(line)
                    if r.get("claim") == "C3":
                        d[r["case_id"]] = r
        new[who] = d
    res = dict(note="E1+E+T C3 re-coded under an explicit abstention rule by configuration reviewers A and B.",
               packets=len(pk), coded={w: len(set(new[w]) & set(pk)) for w in "AB"})
    for who in ("A", "B", "agreed"):
        tab = collections.Counter()
        for pid, c in pk.items():
            rf = lab(ref[c["case"]])
            if who == "agreed":
                a, b = lab(new["A"].get(pid)), lab(new["B"].get(pid))
                x = a if a == b else "disagree"
            else:
                x = lab(new[who].get(pid))
            if rf.startswith("supported"):
                tab["ref_resolved|" + ("agree" if x == rf else "lost" if x in ("unresolved", "disagree") else "wrong")] += 1
            elif rf == "contradicted":
                tab["ref_contradicted|" + x] += 1
            else:
                tab["ref_unresolved|" + ("stayed" if x in ("unresolved", "disagree") else "new:" + x)] += 1
        res[who] = dict(sorted(tab.items()))
    pairs = [(lab(new["A"].get(p)), lab(new["B"].get(p))) for p in pk]
    res["agreement_A_B"] = dict(raw=round(sum(a == b for a, b in pairs) / len(pairs), 3), ac1=s.ac1(pairs))
    res["original_E1pEpT_C3_for_comparison"] = "30 of 86 reference mechanisms matched, 56 proposal applications read as editor insertions (rq4_main.json mechanism_check)"
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
