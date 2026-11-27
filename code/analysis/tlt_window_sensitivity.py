r"""echo-window sensitivity: tier A (broad rule) at 30, 60, 90 and 180 minutes. Aggregates only.

  python code/analysis/tlt_window_sensitivity.py --zip D:\session-records.zip

Matching is X1 (via tlt_echo_audit.classify, 90-minute candidate window before the submission, unchanged). Only the broad
rule's lookback before the matched answer varies. Tier B (same-request rule) uses no window and is shown for reference.
Output: results/window_sensitivity.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_episode_audit import tok  # noqa: E402
from tier1_analyses import user_text, matched_positions  # noqa: E402
import tlt_echo_audit as ea  # noqa: E402

MINUTES = [30, 60, 90, 180]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, default=Path(r"D:\session-records.zip"))
    a = ap.parse_args()
    cases, _, utext, proxy_all = ea.classify(a.zip)
    n = len(cases)
    counts = {m: 0 for m in MINUTES}
    tier_b = 0
    parts = {m: set() for m in MINUTES}
    for c in cases:
        s, first = c["s"], c["first"]
        T = s["tok"]
        pa, _ = matched_positions(T, first[2])
        same = tok(user_text(proxy_all.get(first[1]) or {}))
        pr = matched_positions(T, same)[0] if same else set()
        if len(pa - pr) / max(1, len(T)) >= 0.5:
            tier_b += 1
        prior = [(first[0] - tu, ut) for (tu, ut, _, _) in utext.get(s["user_id"], []) if tu <= first[0]]
        for m in MINUTES:
            broad = set(pr)
            for lag, ut in prior:
                if lag <= timedelta(minutes=m):
                    broad |= matched_positions(T, ut)[0]
            if len(pa - broad) / max(1, len(T)) >= 0.5:
                counts[m] += 1
                parts[m].add(s["user_id"])
    out = dict(note="Near-verbatim submissions with an X1 match (containment >= 0.99 per submission_linkage). Broad-rule lookback varied; matching fixed.",
               near_verbatim_matched=n, tier_B_same_request=tier_b,
               tier_A_broad={f"{m}min": dict(n=counts[m], of=n, share=round(counts[m] / n, 3), participants=len(parts[m])) for m in MINUTES})
    ea.OUT.mkdir(parents=True, exist_ok=True)
    (ea.OUT / "window_sensitivity.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
