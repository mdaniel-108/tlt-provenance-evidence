r"""controlled trace validation: score blind adjudications against the scripted ground truth. Aggregates only.

  python code/analysis/tlt_trace_score.py

**Ground truth by design** (fixed here before reading any coded row):

| Scenario | Actions | C1 AI material in submission | C2 a response supplied it | C3 mechanism | C4 sequence |
|---|---|---|---|---|---|
| S1 | apply an AI proposal | yes | yes | proposal_applied | yes |
| S2 | copy from chat, paste | yes | yes | editor_insertion | yes |
| S3 | retype AI code by hand in small chunks | yes | yes | incremental | yes |
| S4 | apply an AI proposal, then rename identifiers (corrected from the recorded scripted actions: the insertion step is apply_proposal in all three runs; the first table, written before the codes were read, said editor_insertion) | yes | yes | proposal_applied | yes |
| S5 | apply a proposal, undo it, rewrite independently | no | no | (none) | no |
| S6 | paste AI code, edit after the last AI interaction, submit | yes | yes | editor_insertion | yes |
| S7 | reuse code from an earlier AI response | yes | yes | editor_insertion | yes |
| S8 | send own code, accept an echoing answer | no | no | (none) | no |
| S9 | no AI use | no | no | (none) | no |

**Scoring per coder and claim:**
- truth "yes": `supported` = correct, `unresolved` = unresolved, `contradicted` = wrong;
- truth "no": `contradicted` = correct, `unresolved` = unresolved (acceptable), `supported` = **wrong support** (false lineage);
- C3 for truth "yes" is correct only when the mechanism also matches; `not_identifiable` counts as unresolved.
C2's response ID is not checked against the key (the key does not map answers to packet IDs), so C2 "correct" means the
decision only. Inter-coder agreement is reported before any consensus; there is no consensus stage here.

Inputs: D:\tlt\trace\key.csv, D:\tlt\trace\out\ref1_*.jsonl, ref2_*.jsonl (synthetic runs). Output:
results/trace_validation.json.
"""
from __future__ import annotations

import collections
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
T = Path("D:/tlt/trace")
OUT = ROOT / "results" / "trace_validation.json"
YES = {"C1": True, "C2": True, "C4": True}
TRUTH = {s: dict(pos=s not in ("S5", "S8", "S9", "S10", "S11", "S12")) for s in [f"S{i}" for i in range(1, 13)]}
# , all without AI material in the submission:
#   S10 AI answer received but not used, own short solution typed; S11 own code first, assistant explains it, code kept;
#   S12 AI answer received but not used, own longer solution typed. Runs X*, key_ext.csv, packets/ext, out/*trace_ext_*.
MECH = {"S1": "proposal_applied", "S2": "editor_insertion", "S3": "incremental", "S4": "proposal_applied",
        "S6": "editor_insertion", "S7": "editor_insertion"}


def outcome(scen, claim, row):
    pos = TRUTH[scen]["pos"]
    d = (row or {}).get("decision")
    if d is None:
        return "missing"
    if claim == "C3" and pos:
        if d == "supported" and (row.get("mechanism") == MECH[scen]):
            return "correct"
        if d == "supported":
            return "wrong_mechanism"
        return "unresolved" if d == "unresolved" else "wrong"
    if pos:
        return {"supported": "correct", "unresolved": "unresolved", "contradicted": "wrong"}[d]
    return {"contradicted": "correct", "unresolved": "unresolved", "supported": "wrong_support"}[d]


def main():
    res = score_key("key.csv", "trace_[0-9]*")
    ext = T / "key_ext.csv"
    if ext.exists():
        res["extension"] = score_key("key_ext.csv", "trace_ext_*", note=False)
    if (T / "key_s3h.csv").exists() and list((T / "out").glob("ref1_s3h.jsonl")):
        # S3 retyping at human speed (about 2.7 chars/s, pauses, corrected typos;
        # runs H01-H03), same stack, packets and adjudicators; ground truth as S3 (incremental)
        TRUTH["S3H"] = dict(pos=True); MECH["S3H"] = "incremental"
        res["s3_human_speed"] = score_key("key_s3h.csv", "s3h", note=False)
        res["s3_human_speed"]["note"] = ("S3H: S3 retyping at human speed (2.65-2.88 chars/s, look-back pauses, corrected "
                                         "typos), 3 runs on problems 1-3; the original S3 runs typed at about 13.6 chars/s.")
    if (T / "key_s3m.csv").exists() and list((T / "out").glob("ref1_s3m.jsonl")):
        # S3 retyping at mid speed (about 7 chars/s, no long pauses; runs M01-M03)
        TRUTH["S3M"] = dict(pos=True); MECH["S3M"] = "incremental"
        res["s3_mid_speed"] = score_key("key_s3m.csv", "s3m", note=False)
        res["s3_mid_speed"]["note"] = "S3M: S3 retyping at mid speed (typeHuman, 120 ms median gap, no look-back pauses), 3 runs on problems 1-3."
    red = T / "key_reduced.csv"
    if red.exists() and list((T / "out").glob("ref1_trace_red_*.jsonl")):
        res["reduced_E1pEpT"] = reduced(res)
    if (T / "key_reduced_fullu.csv").exists() and list((T / "out").glob("ref1_trace_redU_*.jsonl")):
        res["reduced_FullU"] = reduced(res, "key_reduced_fullu.csv", "trace_redU_*", "Full-U")
    if red.exists() and list((T / "out").glob("ref1_c3abst_trace_red_*.jsonl")):
        res["reduced_E1pEpT_c3abstain"] = reduced(res, "key_reduced.csv", "c3abst_trace_red_*", "E1+E+T with the explicit C3 abstention rule")
    for blk in [res, res.get("extension") or {}, res.get("reduced_E1pEpT") or {}, res.get("reduced_FullU") or {}, res.get("reduced_E1pEpT_c3abstain") or {}]:
        for c, x in (blk.get("coders") or {}).items():       # report "not wrong" (correct + unresolved) too
            t = x["totals"]
            x["not_wrong"] = t.get("correct", 0) + t.get("unresolved", 0)
            x["decisions"] = sum(t.values())
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: (v if k != "coders" else {c: x["totals"] for c, x in v.items()}) for k, v in res.items() if k != "extension"}, indent=1))
    if "extension" in res:
        print("extension:", json.dumps({c: x["totals"] for c, x in res["extension"]["coders"].items()}))


def score_key(keyname, outglob, note=True):
    key = [r for r in csv.DictReader(open(T / keyname, encoding="utf-8")) if r.get("packet_id")]
    scen = {r["packet_id"]: r["scenario"] for r in key}
    codes = {}
    for c in ("ref1", "ref2"):
        rows = {}
        for f in sorted((T / "out").glob(f"{c}_{outglob}.jsonl")):
            for line in open(f, encoding="utf-8"):
                if line.strip():
                    r = json.loads(line)
                    if r.get("claim"):
                        rows[(r["case_id"], r["claim"])] = r
        codes[c] = rows
    res = dict(note=("Controlled trace validation: 27 scripted runs (S1-S9 x 3) on a local copy of the system, one scripted "
                     "operator, local qwen2.5-coder:7b as the assistant. Blind adjudication by the "
                     "two reference adjudicators, rubric v0.3."),
               packets=len(scen), by_scenario=dict(collections.Counter(scen.values())), coders={})
    for c, rows in codes.items():
        tab = collections.defaultdict(collections.Counter)
        for pid, s in scen.items():
            for cl in ("C1", "C2", "C3", "C4"):
                tab[f"{s}|{cl}"][outcome(s, cl, rows.get((pid, cl)))] += 1
        tot = collections.Counter()
        for k, v in tab.items():
            tot.update(v)
        res["coders"][c] = dict(by_scenario_claim={k: dict(v) for k, v in sorted(tab.items())}, totals=dict(tot),
                                wrong_supports=sum(v.get("wrong_support", 0) for v in tab.values()))
    agree = collections.Counter()
    for pid in scen:
        for cl in ("C1", "C2", "C3", "C4"):
            a, b = codes["ref1"].get((pid, cl)), codes["ref2"].get((pid, cl))
            if a and b:
                ka = (a["decision"], a.get("mechanism") if cl == "C3" else None)
                kb = (b["decision"], b.get("mechanism") if cl == "C3" else None)
                agree[cl] += int(ka == kb)
    res["corrections"] = ["S4 expected mechanism changed from editor_insertion to proposal_applied after the codes were read, "
                          "because the recorded scripted actions (key.csv) show apply_proposal as the insertion step in all S4 runs."]
    res["agreement_raw"] = {cl: round(agree[cl] / len(scen), 3) for cl in ("C1", "C2", "C3", "C4")}
    if not note:
        res["note"] = "Extension: S10-S12 x 3 runs (no AI material in the submission), same stack, operator and adjudicators."
        res.pop("corrections", None)
    return res


def reduced(res, keyname="key_reduced.csv", glob_="trace_red_*", cfg="E1+E+T"):
    """E1+E+T packets of all 36 runs (key_reduced.csv; coded by configuration reviewers A and B,
    out/ref{1,2}_trace_red_*.jsonl), scored against the scripted actions, and paired with
    the full-record decision of the same run and coder position (ref1 = claim by claim, ref2 = timeline first)."""
    r = score_key(keyname, glob_, note=False)
    r["note"] = (f"Reduced configuration {cfg} for all 36 trace runs, coded blind by "
                 "configuration reviewers A and B, scored against the scripted actions.")
    key = [x for x in csv.DictReader(open(T / keyname, encoding="utf-8"))]
    scen = {x["packet_id"]: x["scenario"] for x in key}
    full_of = {x["packet_id"]: x["full_packet_id"] for x in key}

    def rows(c, glob):
        out = {}
        for f in sorted((T / "out").glob(f"{c}_{glob}.jsonl")):
            for line in open(f, encoding="utf-8"):
                if line.strip():
                    z = json.loads(line)
                    if z.get("claim"):
                        out[(z["case_id"], z["claim"])] = z
        return out

    pair = {}
    for c in ("ref1", "ref2"):
        fr = {**rows(c, "trace_[0-9]*"), **rows(c, "trace_ext_*")}
        rr = rows(c, glob_)
        tab = collections.Counter()
        for pid, s in scen.items():
            for cl in ("C1", "C2", "C3", "C4"):
                a = outcome(s, cl, fr.get((full_of[pid], cl)))
                b = outcome(s, cl, rr.get((pid, cl)))
                tab[f"full_{a}->reduced_{b}"] += 1
        pair[c] = dict(sorted(tab.items()))
    r["paired_full_to_reduced"] = pair
    return r


if __name__ == "__main__":
    main()
