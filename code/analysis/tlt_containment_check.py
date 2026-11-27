r"""partial reuse outside the symmetric-ratio labels. Aggregates only.

  python code/analysis/tlt_containment_check.py

For every judged submission s and every AI code block b of the same participant from the 90 minutes before it (the
candidate set of tlt_pck_labels.py), with M = tokens in difflib SequenceMatcher matching blocks (autojunk off):
- ratio            2M / (|s| + |b|)              (the label measure; reproduces the 952 linked submissions at 0.80)
- sub_containment  M / |s|   share of the submission covered by one block
- blk_containment  M / |b|   share of one block (of at least MIN_BLOCK tokens) found in the submission
Unlike the earlier tier1 sensitivity, no block is skipped by a ratio pre-filter: a block is skipped only when an upper
bound on M (multiset token overlap) cannot beat the current maximum of the measure in question.
Output: results/containment_check.json
"""
from __future__ import annotations

import collections
import csv
import difflib
import json
import sys
import zipfile
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_episode_audit import ai_code_blocks, jsonl, pno, tok, ts  # noqa: E402
import tlt_echo_audit as ea  # noqa: E402

W = timedelta(minutes=90)
MIN_BLOCK = 20
OUT = ROOT / "results" / "containment_check.json"


def main():
    z = zipfile.ZipFile(Path(r"D:\session-records.zip"))
    subs = list(csv.DictReader(open(ea.JUDGE / "submissions.csv", encoding="utf-8-sig")))
    for s in subs:
        s["t"] = ts(s["submitted_at"])
        s["tok"] = tok((ea.JUDGE / s["code_path"]).read_text(encoding="utf-8"))
    blocks = collections.defaultdict(list)
    for r in jsonl(z, "data/analysis/proxy_calls.jsonl"):
        if r.get("operation") or not r.get("created_at") or r.get("status") != "success" or not pno(r.get("problem_id")):
            continue
        t = ts(r["created_at"])
        for _, b in ai_code_blocks(r):
            tb = tok(b)
            if tb:
                blocks[r["participant"]].append((t, tb, collections.Counter(tb)))
    rows = []
    for s in subs:
        T = s["tok"]
        if not T:
            continue
        cT = collections.Counter(T)
        best_r = best_s = best_b = best_rev = 0.0
        for t, tb, cb in blocks.get(s["user_id"], []):
            if not (s["t"] - W <= t <= s["t"]):
                continue
            ub = sum((cT & cb).values())                  # upper bound on M
            need = (ub * 2 / (len(T) + len(tb)) > min(best_r, best_rev) or ub / len(T) > best_s
                    or (len(tb) >= MIN_BLOCK and ub / len(tb) > best_b))
            if not need:
                continue
            M = sum(m.size for m in difflib.SequenceMatcher(None, T, tb, autojunk=False).get_matching_blocks())
            best_r = max(best_r, 2 * M / (len(T) + len(tb)))
            # SequenceMatcher is order-dependent; the labels pass the submission first. Reversed order:
            Mr = sum(m.size for m in difflib.SequenceMatcher(None, tb, T, autojunk=False).get_matching_blocks())
            best_rev = max(best_rev, 2 * Mr / (len(T) + len(tb)))
            best_s = max(best_s, M / len(T))
            if len(tb) >= MIN_BLOCK:
                best_b = max(best_b, M / len(tb))
        rows.append((best_r, best_s, best_b, best_rev))
    n = len(rows)
    linked = [r for r in rows if r[0] >= 0.80]
    unl = [r for r in rows if r[0] < 0.80]
    res = dict(
        note="Partial-reuse check: containment measures without a ratio pre-filter, same candidate blocks and window as the labels.",
        submissions=n, linked_ratio_ge_0_80=len(linked), unlinked=len(unl),
        unlinked_sub_containment_ge_0_80=sum(r[1] >= 0.80 for r in unl),
        unlinked_sub_containment_ge_0_50=sum(r[1] >= 0.50 for r in unl),
        unlinked_blk_containment_ge_0_80=sum(r[2] >= 0.80 for r in unl),
        unlinked_either_ge_0_80=sum(r[1] >= 0.80 or r[2] >= 0.80 for r in unl),
        all_sub_containment_ge_0_80=sum(r[1] >= 0.80 for r in rows),
        min_block_tokens=MIN_BLOCK,
        argument_order=dict(note="ratio with the block as the first argument instead of the submission",
                            linked_ge_0_80_reversed=sum(r[3] >= 0.80 for r in rows), near_verbatim_ge_0_99_forward=sum(r[0] >= 0.99 for r in rows),
                            near_verbatim_ge_0_99_reversed=sum(r[3] >= 0.99 for r in rows),
                            linked_status_changes=sum((r[0] >= 0.80) != (r[3] >= 0.80) for r in rows),
                            near_verbatim_status_changes=sum((r[0] >= 0.99) != (r[3] >= 0.99) for r in rows),
                            max_abs_difference=round(max(abs(r[0] - r[3]) for r in rows), 4)))
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
