"""Reuse analyses on the session records, and the matching helpers shared by the other scripts. Aggregate outputs only.

  python code/analysis/tier1_analyses.py --zip D:\\session-records.zip

Rules fixed before running:
A2  Echo-aware reuse. For each AI-derived submission (best match >= 0.80, audit definition), token positions of the
    submission matched to its best AI block (difflib matching blocks) are split into those also matched to the
    user-role text of the same request (code the participant attached or pasted, and the statement) and the rest.
    "New in the answer" share = matched-to-AI-only positions / submission length. Attached code can itself derive
    from earlier AI answers, so the echoed part is "pre-existing in the request", not "human-written".
A3  Baselines. (a) Cross-participant: best similarity of each submission to AI code that OTHER participants received
    on the same problem (any time). (b) Human-human: for submissions with best AI similarity < 0.5, best similarity to
    other participants' submissions (same rule) on the same problem. Share >= 0.80 under each.
A4  Sensitivity of the AI-derived and verbatim shares: thresholds 0.70-0.95; windows 30 min, 60 min, 90 min, whole
    session before the submission; identifier-normalised tokens (identifiers -> ID, numbers -> NUM); containment
    (matched tokens / submission tokens). Chronological tie-break (earliest block among equal maxima) for the
    source stage of the best match.
A5  Cross-thread use of higher stages. For AI-derived submissions whose best match came from another problem's
    thread: the selected stage of the source call vs the highest stage available in the submission's own problem
    thread at submission time, s_max(a) = min(5, floor(a/5)+1) with a = accepted attempts in that thread before the
    submission.
A6  Stage choice and latency. Accepted attempts in time order per participant: share selecting a stage below the
    unlocked one by the latency of the participant's previous primary call (<5 s, 5-20 s, >20 s) and after a
    gpt-5-low call.
A7  Proposal validation outcomes by selected stage and model, from Proxy proposal_validation / retry fields.
A9  Acceptance by reuse class; A11 per-problem table; A12 reuse at the episode level (index submission).
"""
from __future__ import annotations

import argparse
import collections
import csv
import difflib
import json
import re
import statistics as st
import sys
import zipfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_episode_audit import ai_code_blocks, jsonl, pno, tok, ts  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
JUDGE = ROOT / "datasets" / "pck2026_oln2026"
OUT = ROOT / "research" / "outputs" / "tier1"
START, END = "2026-11-07T13:45:00+09:00", "2026-11-07T17:45:00+09:00"

KW = set("""auto break case char const continue default do double else enum extern float for goto if int long register return
short signed sizeof static struct switch typedef union unsigned void volatile while bool true false class public private
protected new delete this template typename namespace using std include define vector string map set pair queue stack
deque priority_queue unordered_map unordered_set cin cout endl printf scanf main import package final extends implements
interface throws throw try catch boolean byte String System out println Scanner nextInt next nextLine static void args
ArrayList HashMap List Map Integer Long Math max min sort begin end push_back size length""".split())


def norm(tokens):
    out = []
    for t in tokens:
        if re.fullmatch(r"\d+", t):
            out.append("NUM")
        elif re.fullmatch(r"[A-Za-z_]\w*", t) and t not in KW:
            out.append("ID")
        else:
            out.append(t)
    return out


def user_text(r):
    parts = []
    for m in r.get("messages") or []:
        if isinstance(m, dict) and m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, list):
                parts += [x.get("text", "") for x in c if isinstance(x, dict)]
    return "\n".join(parts)


def matched_positions(a, b):
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    pos = set()
    for i, _, n in sm.get_matching_blocks():
        pos.update(range(i, i + n))
    return pos, sm.ratio()


def share(n, d):
    return round(n / d, 4) if d else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True, type=Path)
    a = ap.parse_args()
    z = zipfile.ZipFile(a.zip)
    OUT.mkdir(parents=True, exist_ok=True)
    t0, t1 = ts(START), ts(END)

    subs = list(csv.DictReader(open(JUDGE / "submissions.csv", encoding="utf-8-sig")))
    for s in subs:
        s["t"] = ts(s["submitted_at"])
        s["no"] = int(s["problem_id"]) - 794
        s["tok"] = tok((JUDGE / s["code_path"]).read_text(encoding="utf-8"))
    link = {r["submission_id"]: r for r in csv.DictReader(open(ROOT / "datasets" / "audit" / "submission_linkage.csv", encoding="utf-8-sig"))}

    threads = {r["thread_id"]: pno(r["problem_id"]) for r in jsonl(z, "data/ledger/2026-11-07/attempt_threads.jsonl")}
    ledger = collections.defaultdict(list)
    attempts = []
    for r in jsonl(z, "data/ledger/2026-11-07/attempt_requests.jsonl"):
        no = threads.get(r["thread_id"])
        r["t"] = ts(r["accepted_at"])
        if no and t0 <= r["t"] <= t1:
            ledger[(r["participant"], no)].append(r)
            attempts.append(r)
    for v in ledger.values():
        v.sort(key=lambda x: x["t"])

    proxy = {}
    blocks = collections.defaultdict(list)          # participant -> (t, no, rid, tokens, src, stage, ntokens)
    blocks_by_problem = collections.defaultdict(list)
    primary_latency = {}
    validation = collections.Counter()
    for r in jsonl(z, "data/analysis/proxy_calls.jsonl"):
        no = pno(r.get("problem_id"))
        if not no or not r.get("created_at") or r.get("operation"):
            continue
        t = ts(r["created_at"])
        rid = r.get("chat_request_id")
        if r.get("status") == "success":
            if rid and r.get("call_index") in ("primary", 0, None) and rid not in primary_latency:
                primary_latency[rid] = (r.get("latency_ms"), r.get("model_alias"))
            proxy.setdefault(rid, r)
            for src, b in ai_code_blocks(r):
                tb = tok(b)
                rec = (t, no, rid, tb, src, r.get("attempt_selected_stage"), norm(tb))
                blocks[r["participant"]].append(rec)
                blocks_by_problem[no].append((r["participant"], tb))
        pv = r.get("proposal_validation")
        if pv:
            key = (r.get("attempt_selected_stage"), r.get("model_alias"), json.dumps(pv, sort_keys=True)[:120] if not isinstance(pv, str) else pv)
            validation[key] += 1
    res = {}

    # ---- A9 / A12 / A11 ------------------------------------------------------------------------------
    cls = collections.defaultdict(lambda: [0, 0, set()])
    for s in subs:
        L = link[s["submission_id"]]
        c = "verbatim" if L["verbatim_ai"] == "True" else ("derived_not_verbatim" if L["derived_from_ai"] == "True" else "low_or_no_match")
        cls[c][0] += 1
        cls[c][1] += s["verdict"] == "AC"
        cls[c][2].add(s["user_id"])
    res["A9_acceptance_by_class"] = {k: {"submissions": v[0], "accepted": v[1], "accepted_share": share(v[1], v[0]), "participants": len(v[2])}
                                     for k, v in cls.items()}
    eps = collections.defaultdict(list)
    for s in subs:
        eps[(s["user_id"], s["no"])].append(s)
    idx = {}
    for k, v in eps.items():
        v.sort(key=lambda x: x["t"])
        ac = [x for x in v if x["verdict"] == "AC"]
        idx[k] = ac[0] if ac else v[-1]
    n_ep = len(idx)
    der = sum(link[x["submission_id"]]["derived_from_ai"] == "True" for x in idx.values())
    verb = sum(link[x["submission_id"]]["verbatim_ai"] == "True" for x in idx.values())
    res["A12_episode_level"] = {"episodes_with_submissions": n_ep, "index_ai_derived": der, "index_ai_derived_share": share(der, n_ep),
                                "index_verbatim": verb, "index_verbatim_share": share(verb, n_ep),
                                "submission_level_ai_derived_share": share(sum(l["derived_from_ai"] == "True" for l in link.values()), len(link))}
    per = []
    for no in range(1, 14):
        e = {k: v for k, v in eps.items() if k[1] == no}
        solved = sum(any(x["verdict"] == "AC" for x in v) for v in e.values())
        ss = [x for v in e.values() for x in v]
        hi = [max(r["unlocked_stage"] for r in ledger[(p, no)]) for p in {k[0] for k in e} if ledger.get((p, no))]
        per.append({"problem": no, "judge_id": 794 + no, "episodes_with_submissions": len(e), "solved": solved,
                    "solved_share": share(solved, len(e)), "submissions": len(ss),
                    "ai_derived_share": share(sum(link[x["submission_id"]]["derived_from_ai"] == "True" for x in ss), len(ss)),
                    "verbatim_share": share(sum(link[x["submission_id"]]["verbatim_ai"] == "True" for x in ss), len(ss)),
                    "threads_with_requests": len(hi), "median_highest_recorded_stage": st.median(hi) if hi else None,
                    "threads_stage1_only": sum(h == 1 for h in hi)})
    res["A11_per_problem"] = per

    # ---- A5 cross-thread use of higher stages -------------------------------------------------------
    cross = collections.Counter()
    for s in subs:
        L = link[s["submission_id"]]
        if L["derived_from_ai"] != "True" or not L["best_match_problem_no"]:
            continue
        src_no = int(L["best_match_problem_no"])
        if src_no == s["no"]:
            cross["same_thread"] += 1
            continue
        cross["cross_thread"] += 1
        src = proxy.get(L["best_match_chat_request_id"]) or {}
        s_src = src.get("attempt_selected_stage")
        acc = sum(r["t"] < s["t"] for r in ledger.get((s["user_id"], s["no"]), []))
        s_tgt = min(5, acc // 5 + 1)
        if s_src is None:
            cross["source_stage_unknown"] += 1
        elif s_src > s_tgt:
            cross["source_stage_above_target_available"] += 1
            cross[f"gap_{s_src - s_tgt}"] += 1
            if s["verdict"] == "AC":
                cross["above_and_accepted"] += 1
        else:
            cross["source_stage_within_target_available"] += 1
    res["A5_cross_thread"] = dict(cross)

    # ---- A6 stage choice vs previous latency -------------------------------------------------------
    byp = collections.defaultdict(list)
    for r in attempts:
        byp[r["participant"]].append(r)
    bins = collections.defaultdict(lambda: [0, 0])
    after_gpt5 = [0, 0]
    switch_from_gpt5 = [0, 0]
    for p, v in byp.items():
        v.sort(key=lambda x: x["t"])
        for prev, cur in zip(v, v[1:]):
            lat, alias = primary_latency.get(prev["chat_request_id"], (None, None))
            below = cur["selected_stage"] < cur["unlocked_stage"]
            if lat is not None:
                b = "<5s" if lat < 5000 else ("5-20s" if lat <= 20000 else ">20s")
                bins[b][0] += 1
                bins[b][1] += below
            if prev.get("model_alias") == "gpt-5-low":
                after_gpt5[0] += 1
                after_gpt5[1] += below
                switch_from_gpt5[0] += 1
                switch_from_gpt5[1] += cur.get("model_alias") != "gpt-5-low"
    res["A6_stage_choice_vs_latency"] = {"by_previous_latency": {k: {"attempts": v[0], "below_unlocked": v[1], "share": share(v[1], v[0])} for k, v in bins.items()},
                                         "after_gpt5_low": {"attempts": after_gpt5[0], "below_unlocked_share": share(after_gpt5[1], after_gpt5[0]),
                                                            "switched_model_share": share(switch_from_gpt5[1], switch_from_gpt5[0])},
                                         "overall_below_share": share(sum(r["selected_stage"] < r["unlocked_stage"] for r in attempts), len(attempts))}

    # ---- A7 proposal validation ---------------------------------------------------------------------
    res["A7_proposal_validation"] = [{"stage": k[0], "model": k[1], "validation": k[2], "calls": n} for k, n in validation.most_common(40)]

    # ---- A4 sensitivity, A2 echo, A3 baselines -----------------------------------------------------
    windows = {"30min": timedelta(minutes=30), "60min": timedelta(minutes=60), "90min": timedelta(minutes=90), "session": timedelta(hours=6)}
    best = {w: [] for w in windows}
    best_norm, best_cont, chrono_stage, echo = [], [], collections.Counter(), []
    for s in subs:
        p, T = s["user_id"], s["tok"]
        cand = [b for b in blocks.get(p, []) if b[0] <= s["t"]]
        for w, dt in windows.items():
            m = 0.0
            for b in cand:
                if b[0] < s["t"] - dt:
                    continue
                sm = difflib.SequenceMatcher(None, T, b[3], autojunk=False)
                if sm.real_quick_ratio() <= m or sm.quick_ratio() <= m:
                    continue
                m = max(m, sm.ratio())
            best[w].append(m)
        c90 = [b for b in cand if b[0] >= s["t"] - windows["90min"]]
        nT = norm(T)
        mn, mc, ties, top = 0.0, 0.0, [], -1.0
        for b in c90:
            smn = difflib.SequenceMatcher(None, nT, b[6], autojunk=False)
            if smn.quick_ratio() > mn:
                mn = max(mn, smn.ratio())
            sm = difflib.SequenceMatcher(None, T, b[3], autojunk=False)
            if sm.quick_ratio() + 1e-9 < top:
                continue
            r = sm.ratio()
            cont = sum(n for _, _, n in sm.get_matching_blocks()) / max(1, len(T))
            mc = max(mc, cont)
            if r > top + 1e-12:
                top, ties = r, [b]
            elif abs(r - top) <= 1e-12:
                ties.append(b)
        best_norm.append(mn)
        best_cont.append(mc)
        if top >= 0.80 and ties:
            first = min(ties, key=lambda b: b[0])
            chrono_stage[str(first[5])] += 1
            req = proxy.get(first[2]) or {}
            ut = tok(user_text(req))
            pa, _ = matched_positions(T, first[3])
            pr, _ = matched_positions(T, ut) if ut else (set(), 0)
            new = len(pa - pr) / max(1, len(T))
            echo.append((top, new, bool(ut)))
    n = len(subs)
    res["A4_sensitivity"] = {
        "n_submissions": n,
        "thresholds_90min": {f"{th:.2f}": share(sum(x >= th for x in best["90min"]), n) for th in (0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 0.99)},
        "windows_at_0.80": {w: share(sum(x >= 0.80 for x in v), n) for w, v in best.items()},
        "windows_at_0.99": {w: share(sum(x >= 0.99 for x in v), n) for w, v in best.items()},
        "identifier_normalised_at_0.80": share(sum(x >= 0.80 for x in best_norm), n),
        "identifier_normalised_at_0.99": share(sum(x >= 0.99 for x in best_norm), n),
        "containment_at_0.80": share(sum(x >= 0.80 for x in best_cont), n),
        "containment_at_0.99": share(sum(x >= 0.99 for x in best_cont), n),
        "chronological_tiebreak_source_stage": dict(chrono_stage),
    }
    E = [e for e in echo if e[2]]
    res["A2_echo_aware"] = {
        "ai_derived_with_request_text": len(E), "ai_derived_total": len(echo),
        "median_new_in_answer_share": round(st.median([e[1] for e in E]), 3) if E else None,
        "new_share_ge_0.80": share(sum(e[1] >= 0.80 for e in E), len(E)),
        "new_share_ge_0.50": share(sum(e[1] >= 0.50 for e in E), len(E)),
        "new_share_lt_0.20": share(sum(e[1] < 0.20 for e in E), len(E)),
        "submissions_mostly_new_ai_code_share_of_all": share(sum(e[1] >= 0.50 for e in echo), n),
        "note": "Echoed part = submission tokens also matched to user-role text of the same request (attached or pasted code, statement); it may itself derive from earlier AI answers.",
    }
    cross_best, human_best = [], []
    lowai = [s for s in subs if float(link[s["submission_id"]]["best_ai_similarity"] or 0) < 0.5]
    for s in subs:
        m = 0.0
        for q, tb in blocks_by_problem.get(s["no"], []):
            if q == s["user_id"]:
                continue
            sm = difflib.SequenceMatcher(None, s["tok"], tb, autojunk=False)
            if sm.real_quick_ratio() <= m or sm.quick_ratio() <= m:
                continue
            m = max(m, sm.ratio())
        cross_best.append(m)
    for s in lowai:
        m = 0.0
        for o in subs:
            if o["no"] != s["no"] or o["user_id"] == s["user_id"]:
                continue
            if float(link[o["submission_id"]]["best_ai_similarity"] or 0) >= 0.5:
                continue
            sm = difflib.SequenceMatcher(None, s["tok"], o["tok"], autojunk=False)
            if sm.real_quick_ratio() <= m or sm.quick_ratio() <= m:
                continue
            m = max(m, sm.ratio())
        human_best.append(m)
    res["A3_baselines"] = {
        "cross_participant_ai_code_ge_0.80": share(sum(x >= 0.80 for x in cross_best), n),
        "cross_participant_ai_code_median": round(st.median(cross_best), 3),
        "own_ai_code_ge_0.80": share(sum(x >= 0.80 for x in best["90min"]), n),
        "human_human_low_ai_submissions": len(human_best),
        "human_human_ge_0.80": share(sum(x >= 0.80 for x in human_best), len(human_best)),
        "human_human_median": round(st.median(human_best), 3) if human_best else None,
    }
    (OUT / "tier1_results.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("A11_per_problem", "A7_proposal_validation")}, indent=1))


if __name__ == "__main__":
    main()
