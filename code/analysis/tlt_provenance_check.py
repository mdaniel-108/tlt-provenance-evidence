"""feasibility check: how much AI provenance each evidence channel recovers (aggregates only).

Reads datasets/audit/submission_linkage.csv (built by code/analysis/build_episode_audit.py, outside Git) and the
telemetry event counts from D:\\session-records.zip. Writes results/provenance_coverage.json.
Thresholds follow build_episode_audit.py: derived >= 0.80, verbatim >= 0.99 (token containment).
Echo-adjusted counts are taken from the X1 matching outputs, not recomputed here.
"""
import collections
import csv
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = Path("../private_data")
LINK = PROJECT / "datasets" / "audit" / "submission_linkage.csv"
ZIP = Path(r"D:\session-records.zip")
OUT = ROOT / "results"
DER, VERB = 0.80, 0.99


def num(x):
    return float(x) if x not in ("", None) else 0.0


def groups(rows):
    return dict(submissions=len(rows), participants=len({r["participant"] for r in rows}),
                problems=len({r["problem_no"] for r in rows}),
                trajectories=len({(r["participant"], r["problem_no"]) for r in rows}))


def main():
    r = list(csv.DictReader(open(LINK, encoding="utf-8-sig")))
    full = lambda x: num(x["best_ai_similarity"])
    chat = lambda x: num(x["best_chat_similarity"])
    res = dict(
        submissions=len(r),
        thresholds=dict(derived=DER, verbatim=VERB),
        full_record=dict(derived=sum(full(x) >= DER for x in r), verbatim=sum(full(x) >= VERB for x in r)),
        chat_only=dict(derived=sum(chat(x) >= DER for x in r), verbatim=sum(chat(x) >= VERB for x in r)),
        lost_without_proposals=dict(derived=sum(full(x) >= DER and chat(x) < DER for x in r),
                                    verbatim=sum(full(x) >= VERB and chat(x) < VERB for x in r)),
        label_groups=dict(
            verbatim=groups([x for x in r if full(x) >= VERB]),
            edited_0_80_to_0_99=groups([x for x in r if DER <= full(x) < VERB]),
            no_recorded_match=groups([x for x in r if full(x) < DER])),
        echo_adjusted_from_existing_outputs=dict(
            verbatim_and_mostly_new_same_request_rule=780, verbatim_and_mostly_new_broadest_rule=553,
            verbatim_mostly_echo=115, source="X1 matching"),
    )
    z = zipfile.ZipFile(ZIP)
    nm = next(n for n in z.namelist() if n.endswith("data/analysis/telemetry.jsonl"))
    c = collections.Counter()
    for line in z.open(nm):
        if line.strip():
            e = json.loads(line)
            c[e.get("event_type") or e.get("type") or e.get("event")] += 1
    res["telemetry_event_counts"] = dict(c)
    res["note"] = ("No recorded match is unknown provenance, not human-written. "
                   "3 of 21 participants have server records only (empty device archives).")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "provenance_coverage.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
