"""Data-feasibility audit: join the session records with the judge dataset.

Reads the session-records ZIP directly (never an extracted copy) and the judge
dataset, and writes to datasets/audit/:

  submission_linkage.csv   one row per judge submission: closest AI code block,
                           its thread, similarity, lag, chat activity before it
  episode_audit.csv        one row per participant x problem (13 problems):
                           judge outcome, attempts and stages, proxy calls,
                           proposal outcomes, linkage indicators
  participant_audit.csv    one row per participant: session-level evidence that
                           is not attributed to problems (edits, saves, captures)
  mapping_check.csv        judge problem x thread of best-matching AI code
  audit_summary.json       headline counts

Problem mapping: session thread `provisional-problem-NN` <-> judge problem 794+NN.
It is validated here (mapping_check.csv), not assumed.

Usage: python code/analysis/build_episode_audit.py --zip D:\\session-records.zip
"""
from __future__ import annotations

import argparse
import bisect
import collections
import csv
import difflib
import json
import re
import statistics as st
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JUDGE = ROOT / "datasets" / "pck2026_oln2026"
OUT = ROOT / "datasets" / "audit"
MATCH_WINDOW = timedelta(minutes=90)     # AI responses considered before a submission
CHAT_WINDOW = timedelta(minutes=15)      # "recent chat" window before a submission
MATCH_MIN = 0.80                         # similarity treated as "derived from AI code"
VERBATIM = 0.99                          # similarity treated as "verbatim"
CODE_RE = re.compile(r"```[A-Za-z0-9+#]*\s*\n(.*?)```", re.S)
PROPOSAL_FINAL = ["applied", "rejected", "conflict", "invalid", "failed", "save-failed", "undone", "shown"]


def tok(s: str) -> list[str]:
    return re.findall(r"\w+|[^\w\s]", s)


def ts(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def pno(problem_id: str | None) -> int | None:
    if problem_id and problem_id.startswith("provisional-problem-"):
        return int(problem_id[-2:])
    return None


def jsonl(z: zipfile.ZipFile, name: str):
    with z.open(name) as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def response_text(r: dict) -> str:
    """Answer text from either response format.

    Chat Completions: choices[].message.content.
    Responses API (used by gpt-6-luna / gpt-6-sol): output[type=message].content[type=output_text].text.
    """
    x = r.get("response") or {}
    try:
        text = "".join((ch.get("message") or {}).get("content") or "" for ch in x.get("choices", []) or [] if isinstance(ch, dict))
    except (AttributeError, TypeError):
        text = ""
    for it in x.get("output") or []:
        if isinstance(it, dict) and it.get("type") == "message":
            text += "".join(c.get("text") or "" for c in it.get("content") or [] if isinstance(c, dict) and c.get("type") == "output_text")
    return text


def _tool_arguments(r: dict) -> list[str]:
    """Arguments of propose_file_edit calls, from either response format."""
    x = r.get("response") or {}
    args = []
    for ch in x.get("choices", []) or []:
        for tc in ((ch or {}).get("message") or {}).get("tool_calls") or []:
            f = (tc or {}).get("function") or {}
            if f.get("name") in (None, "propose_file_edit"):
                args.append(f.get("arguments") or "{}")
    for it in x.get("output") or []:
        if isinstance(it, dict) and it.get("type") == "function_call" and it.get("name") == "propose_file_edit":
            args.append(it.get("arguments") or "{}")
    return args


def ai_code_blocks(r: dict) -> list[tuple[str, str]]:
    """AI code in one Proxy record, as (source, text).

    'chat': fenced code blocks in the answer text.
    'proposal': the replacement text of a propose_file_edit tool call (all edits joined).
    Proposals arrive as tool calls, not answer text, so they must be read separately.
    """
    out = [("chat", b) for b in CODE_RE.findall(response_text(r))]
    for raw in _tool_arguments(r):
        try:
            args = json.loads(raw)
        except (TypeError, ValueError):
            continue
        rep = "\n".join(e.get("replace") or "" for e in args.get("edits") or [] if isinstance(e, dict))
        if rep.strip():
            out.append(("proposal", rep))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True, type=Path)
    a = ap.parse_args()
    z = zipfile.ZipFile(a.zip)
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- judge data -------------------------------------------------------
    subs = list(csv.DictReader(open(JUDGE / "submissions.csv", encoding="utf-8-sig")))
    titles = {}
    for s in subs:
        s["t"] = ts(s["submitted_at"])
        s["no"] = int(s["problem_id"]) - 794
        titles[s["no"]] = s["problem_title"]
    participants = sorted({s["user_id"] for s in subs})

    # ---- session records: ledger, proxy, telemetry ----------------------------------
    threads = {r["thread_id"]: pno(r["problem_id"]) for r in jsonl(z, "data/ledger/2026-11-07/attempt_threads.jsonl")}
    ledger = collections.defaultdict(list)                          # (participant, no) -> requests
    for r in jsonl(z, "data/ledger/2026-11-07/attempt_requests.jsonl"):
        no = threads.get(r["thread_id"])
        if no:
            ledger[(r["participant"], no)].append(r)

    calls = collections.defaultdict(list)                           # participant -> (t, no)
    by_ep = collections.defaultdict(list)                           # (participant, no) -> proxy records
    ai_code = collections.defaultdict(list)                         # participant -> (t, no, id, tokens)
    for r in jsonl(z, "data/analysis/proxy_calls.jsonl"):
        no = pno(r.get("problem_id"))
        if not no or not r.get("created_at"):
            continue
        t = ts(r["created_at"])
        by_ep[(r["participant"], no)].append(r)
        calls[r["participant"]].append((t, no))
        if r.get("status") == "success":
            for src, b in ai_code_blocks(r):
                ai_code[r["participant"]].append((t, no, r.get("chat_request_id"), tok(b), src))
    for v in calls.values():
        v.sort()

    proposals = {}                                                   # key -> (participant, no, outcomes)
    markers = collections.Counter()
    per_part = collections.defaultdict(collections.Counter)
    sessions = collections.defaultdict(set)
    for r in jsonl(z, "data/analysis/telemetry.jsonl"):
        p, t = r["participant"], r["type"]
        per_part[p][t] += 1
        sessions[p].add(r["session_id"])
        if t == "edit_proposal":
            pl = r["payload"]
            key = (pl.get("thread_id"), pl.get("message_id"), pl.get("proposal_index"))
            no = pno(r.get("problem_id")) or threads.get(pl.get("thread_id"))
            proposals.setdefault(key, [p, no, []])[2].append(pl.get("outcome"))
        elif t == "submission_marker":
            markers[(p, pno(r["payload"].get("problem_id")))] += 1
    prop_final = collections.defaultdict(collections.Counter)
    for p, no, outs in proposals.values():
        final = next((o for o in PROPOSAL_FINAL if o in outs), outs[-1])
        prop_final[(p, no)][final] += 1

    captures = collections.defaultdict(collections.Counter)
    for r in jsonl(z, "data/analysis/source_captures.jsonl"):
        captures[r["participant"]][r.get("result") or "unknown"] += 1

    # ---- submission linkage -----------------------------------------------
    link_rows = []
    for s in subs:
        p, t = s["user_id"], s["t"]
        code = tok((JUDGE / s["code_path"]).read_text(encoding="utf-8"))
        best = (0.0, None, None, None, None)
        best_chat = 0.0
        for ct, no, rid, b, src in ai_code.get(p, []):
            if ct > t or ct < t - MATCH_WINDOW:
                continue
            sm = difflib.SequenceMatcher(None, code, b, autojunk=False)
            floor = min(best[0], best_chat) if src == "chat" else best[0]
            if sm.real_quick_ratio() <= floor or sm.quick_ratio() <= floor:
                continue
            r = sm.ratio()
            if src == "chat" and r > best_chat:
                best_chat = r
            if r > best[0]:
                best = (r, no, rid, ct, src)
        arr = calls.get(p, [])
        times = [c[0] for c in arr]
        recent = arr[bisect.bisect_left(times, t - CHAT_WINDOW):bisect.bisect_right(times, t)]
        link_rows.append({
            "participant": p, "submission_id": s["submission_id"], "judge_problem_id": s["problem_id"],
            "problem_no": s["no"], "submitted_at": s["submitted_at"], "language": s["language"],
            "verdict": s["verdict"], "attempt_no_on_problem": s["attempt_no_on_problem"],
            "best_ai_similarity": round(best[0], 4), "best_match_source": best[4] or "",
            "best_chat_similarity": round(best_chat, 4),
            "best_match_problem_no": best[1] or "", "best_match_chat_request_id": best[2] or "",
            "best_match_lag_s": round((t - best[3]).total_seconds(), 1) if best[3] else "",
            "derived_from_ai": best[0] >= MATCH_MIN, "verbatim_ai": best[0] >= VERBATIM,
            "match_in_same_problem_thread": bool(best[1]) and best[1] == s["no"] if best[0] >= MATCH_MIN else "",
            "chat_calls_prior_15min": len(recent),
            "chat_calls_prior_15min_same_problem": sum(1 for _, n in recent if n == s["no"]),
        })
    write(OUT / "submission_linkage.csv", link_rows)

    # mapping check: judge problem x thread of best-matching AI code
    conf = collections.defaultdict(collections.Counter)
    for r in link_rows:
        if r["derived_from_ai"]:
            conf[r["problem_no"]][r["best_match_problem_no"]] += 1
    write(OUT / "mapping_check.csv", [
        {"judge_problem_id": 794 + no, "problem_no": no, "matched_submissions": sum(c.values()),
         "same_thread": c.get(no, 0), "modal_thread": c.most_common(1)[0][0],
         "modal_is_mapped": c.most_common(1)[0][0] == no,
         "other_threads": json.dumps({k: v for k, v in c.items() if k != no})}
        for no, c in sorted(conf.items())])

    # ---- episode audit -------------------------------------------------------
    links_by_ep = collections.defaultdict(list)
    for r in link_rows:
        links_by_ep[(r["participant"], r["problem_no"])].append(r)
    ep_rows = []
    for p in participants:
        for no in range(1, 14):
            js = sorted((s for s in subs if s["user_id"] == p and s["no"] == no), key=lambda s: s["t"])
            lg = sorted(ledger.get((p, no), []), key=lambda r: r["accepted_at"])
            px = by_ep.get((p, no), [])
            lk = links_by_ep.get((p, no), [])
            pf = prop_final.get((p, no), collections.Counter())
            first_sub = js[0]["t"] if js else None
            first_chat = ts(lg[0]["accepted_at"]) if lg else None
            lat = [r["latency_ms"] for r in px if r.get("latency_ms") is not None and r.get("status") == "success"]
            first_ac = next((s for s in js if s["first_ac_on_problem"] == "True"), None)
            ep_rows.append({
                "participant": p, "problem_no": no, "judge_problem_id": 794 + no, "problem_title": titles.get(no, ""),
                # judge outcome
                "judge_submissions": len(js), "solved": bool(first_ac),
                "attempts_to_ac": first_ac["attempt_no_on_problem"] if first_ac else "",
                "first_submission_at": js[0]["submitted_at"] if js else "",
                "first_ac_at": first_ac["submitted_at"] if first_ac else "",
                **{f"n_{v}": sum(1 for s in js if s["verdict"] == v) for v in ("AC", "WA", "TLE", "MLE", "RE", "PE", "CE")},
                # assistance and stages (attempt ledger)
                "chat_attempts": len(lg),
                "max_unlocked_stage": max((r["unlocked_stage"] for r in lg), default=""),
                "max_selected_stage": max((r["selected_stage"] for r in lg), default=""),
                "attempts_at_stage_1_5": json.dumps([sum(1 for r in lg if r["selected_stage"] == k) for k in range(1, 6)]),
                "providers": ";".join(sorted({r["provider"] for r in lg})),
                "first_chat_at": lg[0]["accepted_at"] if lg else "",
                "chat_before_first_submission": (first_chat < first_sub) if (first_chat and first_sub) else "",
                # proxy calls
                "proxy_calls": len(px), "proxy_errors": sum(1 for r in px if r.get("status") != "success"),
                "median_latency_ms": int(st.median(lat)) if lat else "",
                "cost_usd": round(sum(r.get("cost_usd") or 0 for r in px), 4),
                # proposals (final outcome per proposal)
                "proposals": sum(pf.values()),
                **{f"proposals_{k}": pf.get(k, 0) for k in ("applied", "rejected", "conflict", "invalid", "shown", "undone")},
                "submission_markers": markers.get((p, no), 0),
                # linkage
                "subs_derived_from_ai": sum(1 for r in lk if r["derived_from_ai"]),
                "subs_verbatim_ai": sum(1 for r in lk if r["verbatim_ai"]),
                "subs_matched_other_thread": sum(1 for r in lk if r["derived_from_ai"] and not r["match_in_same_problem_thread"]),
                "has_judge": bool(js), "has_thread": bool(lg),
                "episode_type": ("judge+chat" if js and lg else "judge_only" if js else "chat_only" if lg else "none"),
            })
    write(OUT / "episode_audit.csv", ep_rows)

    # ---- participant audit ---------------------------------------------------
    pa_rows = []
    for p in participants:
        c, cap = per_part[p], captures[p]
        pl = [r for r in link_rows if r["participant"] == p]
        pa_rows.append({
            "participant": p, "sessions": len(sessions[p]), "judge_submissions": len(pl),
            "problems_solved": sum(1 for e in ep_rows if e["participant"] == p and e["solved"]),
            "chat_messages": c["chat_message"], "edit_events": c["edit_delta"], "file_saves": c["file_save"],
            "editor_snapshots": c["editor_snapshot"], "proposal_events": c["edit_proposal"],
            "submission_markers": c["submission_marker"],
            "captures_success": cap.get("success", 0), "captures_failed": cap.get("failed", 0),
            "captures_other": sum(v for k, v in cap.items() if k not in ("success", "failed")),
            "share_subs_derived_from_ai": round(sum(r["derived_from_ai"] for r in pl) / len(pl), 3) if pl else "",
            "share_subs_verbatim_ai": round(sum(r["verbatim_ai"] for r in pl) / len(pl), 3) if pl else "",
        })
    write(OUT / "participant_audit.csv", pa_rows)

    # ---- summary -------------------------------------------------------------
    n = len(link_rows)
    der = [r for r in link_rows if r["derived_from_ai"]]
    types = collections.Counter(e["episode_type"] for e in ep_rows)
    allprop = collections.Counter()
    for v in prop_final.values():
        allprop.update(v)
    summary = {
        "participants": len(participants), "judge_submissions": n,
        "episodes_participant_x_problem": len(ep_rows), "episode_types": dict(types),
        "subs_derived_from_ai_ge_0.80": len(der), "subs_verbatim_ai_ge_0.99": sum(r["verbatim_ai"] for r in link_rows),
        "subs_no_ai_match": n - len(der),
        "ai_code_sources": "fenced chat code blocks and proposal (propose_file_edit) replacement text",
        "derived_by_best_source": dict(collections.Counter(r["best_match_source"] for r in der)),
        "verbatim_by_best_source": dict(collections.Counter(r["best_match_source"] for r in link_rows if r["verbatim_ai"])),
        "chat_text_only_ge_0.80": sum(r["best_chat_similarity"] >= MATCH_MIN for r in link_rows),
        "chat_text_only_ge_0.99": sum(r["best_chat_similarity"] >= VERBATIM for r in link_rows),
        "derived_matches_in_other_thread": sum(1 for r in der if not r["match_in_same_problem_thread"]),
        "subs_without_chat_in_prior_15min": sum(1 for r in link_rows if r["chat_calls_prior_15min"] == 0),
        "mapping_modal_thread_correct": f"{sum(1 for no, c in conf.items() if c.most_common(1)[0][0] == no)}/{len(conf)}",
        "proposals_final_outcomes": dict(allprop),
        "ledger_attempts_mapped": sum(len(v) for v in ledger.values()),
        "proxy_calls_mapped": sum(len(v) for v in by_ep.values()),
    }
    (OUT / "audit_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def write(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
