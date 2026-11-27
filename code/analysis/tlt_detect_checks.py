r"""Checks on the detector benchmark. Aggregates only.

  python code/analysis/tlt_detect_checks.py

1. **Author overlap.** CodeNet splits are by problem, so a human author can appear in train/val and test. Test AUC is
   recomputed without the test human items whose author also appears in train or val.
2. **Duplicates.** Exact (normalized text) and near duplicates (token-set Jaccard >= 0.9) between train and test.
3. **Truncation.** Share of items longer than each model's input limit (UniXcoder and Qwen + LoRA 512 tokens; likelihood
   models and DroidDetect 1,024), for CodeNet test and PCK tier-B near-verbatim by length tercile, and tier-B
   sensitivity for truncated vs untruncated items.
4. **Compile validity** (needs compile.csv from tlt_compile_check.py): compile rates by class; CodeNet test AUC on
   compiling items only.
5. **Length matching.** CodeNet test AUC after matching each AI item to a human item of the same language and nearest
   length (characters), without replacement.

Output: results/detection_checks.json
"""
from __future__ import annotations

import collections
import csv
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from tlt_detect_data import DET, PROJECT, normalize, tokens  # noqa: E402
from tlt_detect_eval import auc, load_scores, thr  # noqa: E402

OUT = ROOT / "results" / "detection_checks.json"
HF = Path("D:/tlt/hf/hub")
MAIN = [("tokenlr", "ext", "raw"), ("structgb", "ext", "raw"), ("droid", "offshelf", "raw"), ("unixcoder", "ext", "raw"),
        ("qwenlora", "ext", "raw"), ("loglik", "zeroshot", "raw"), ("logrank", "zeroshot", "raw"), ("binoculars", "zeroshot", "raw"),
        ("dolos", "refs", "raw")]
LIMIT = {"unixcoder": ("microsoft/unixcoder-base", 512), "qwenlora": ("Qwen/Qwen2.5-Coder-1.5B", 512),
         "loglik": ("Qwen/Qwen2.5-Coder-1.5B", 1024), "droid": ("answerdotai/ModernBERT-base", 1024)}


def snap(repo):
    d = HF / ("models--" + repo.replace("/", "--")) / "snapshots"
    return str(sorted(d.iterdir())[-1])


def code(r):
    return (DET / "code" / f"{r['item_id']}.txt").read_text(encoding="utf-8", errors="replace")


def main():
    rows = list(csv.DictReader(open(DET / "items.csv", encoding="utf-8")))
    for r in rows:
        r["label"] = int(r["label"])
    byset = collections.defaultdict(list)
    for r in rows:
        byset[r["set"]].append(r)
    S = load_scores()
    res = dict(note="Checks on the CodeNet benchmark and PCK tier-B detection. CodeNet human code is a historical, presumed-human population.")
    val_h = [r["item_id"] for r in byset["val"] if r["label"] == 0]

    # 1. author overlap
    user = {f"cnh_s{r['submission_id'].lstrip('s')}": r["user_id"] for r in csv.DictReader(open("D:/tlt/sel/human.csv", encoding="utf-8"))}
    user.update({f"cnh_{r['submission_id']}": r["user_id"] for r in csv.DictReader(open("D:/tlt/sel/human.csv", encoding="utf-8"))})
    seen_users = {user.get(r["item_id"]) for s in ("train", "val") for r in byset[s] if r["label"] == 0}
    test = byset["test"]
    th_ = [r for r in test if r["label"] == 0]
    overlap = [r for r in th_ if user.get(r["item_id"]) in seen_users]
    missing = sum(1 for r in th_ if r["item_id"] not in user)
    test_clean = [r for r in test if not (r["label"] == 0 and user.get(r["item_id"]) in seen_users)]
    res["author_overlap"] = dict(test_human=len(th_), from_authors_in_train_or_val=len(overlap), unmapped=missing,
                                 auc={"__".join(k): dict(all=auc(S[k], test)[0], without_overlap=auc(S[k], test_clean)[0]) for k in MAIN if k in S})

    # 2. duplicates
    nt = {r["item_id"]: normalize(code(r)) for s in ("train", "val", "test") for r in byset[s]}
    ts = {i: set(tokens(t)) for i, t in nt.items()}
    exact = collections.Counter()
    near = collections.Counter()
    trainset = byset["train"] + byset["val"]
    tr_text = collections.defaultdict(list)
    for r in trainset:
        tr_text[nt[r["item_id"]]].append(r)
    maxj = []
    for r in test:
        if nt[r["item_id"]] in tr_text:
            exact[r["label"]] += 1
        a = ts[r["item_id"]]
        best = 0.0
        for q in trainset:
            if q["language"] != r["language"]:
                continue
            b = ts[q["item_id"]]
            u = len(a | b)
            if u:
                best = max(best, len(a & b) / u)
        maxj.append(best)
        if best >= 0.9:
            near[r["label"]] += 1
    res["duplicates_train_val_vs_test"] = dict(test_items=len(test), exact_normalized={"human": exact[0], "ai": exact[1]},
                                               near_jaccard_ge_0_9={"human": near[0], "ai": near[1]},
                                               max_jaccard_median=round(float(np.median(maxj)), 3))

    # 3. truncation
    from transformers import AutoTokenizer
    lab = {f"pck_{r['submission_id']}": r for r in csv.DictReader(open(PROJECT / "datasets" / "audit" / "tlt_labels.csv", encoding="utf-8"))}
    tb = [r for r in byset["pck"] if lab[r["item_id"]]["stratum"] == "near_verbatim" and lab[r["item_id"]]["tier_B"] == "1"]
    ln = sorted(int(r["lines"]) for r in tb)
    q1, q2 = np.quantile(ln, [1 / 3, 2 / 3])
    terc = {"short": [r for r in tb if int(r["lines"]) <= q1], "medium": [r for r in tb if q1 < int(r["lines"]) <= q2],
            "long": [r for r in tb if int(r["lines"]) > q2]}
    trunc = {}
    ntok_cache = {}
    for m, (repo, lim) in LIMIT.items():
        tok = ntok_cache.get(repo) or AutoTokenizer.from_pretrained(snap(repo))
        ntok_cache[repo] = tok
        n = {r["item_id"]: len(tok(code(r)).input_ids) for r in test + tb}
        key = {"unixcoder": ("unixcoder", "ext", "raw"), "qwenlora": ("qwenlora", "ext", "raw"), "loglik": ("loglik", "zeroshot", "raw"),
               "droid": ("droid", "offshelf", "raw")}[m]
        sc = S[key]
        t5 = thr(S[key], val_h, 0.05)
        d = dict(limit=lim, codenet_test_truncated=round(float(np.mean([n[r["item_id"]] > lim for r in test])), 3),
                 codenet_test_truncated_ai=round(float(np.mean([n[r["item_id"]] > lim for r in test if r["label"] == 1])), 3),
                 codenet_test_truncated_human=round(float(np.mean([n[r["item_id"]] > lim for r in test if r["label"] == 0])), 3),
                 tier_B_truncated_by_tercile={k: round(float(np.mean([n[r["item_id"]] > lim for r in v])), 3) for k, v in terc.items()},
                 tier_B_median_tokens_by_tercile={k: int(np.median([n[r["item_id"]] for r in v])) for k, v in terc.items()})
        for name, cond in (("truncated", lambda r: n[r["item_id"]] > lim), ("not_truncated", lambda r: n[r["item_id"]] <= lim)):
            mem = [r for r in tb if cond(r) and r["item_id"] in sc]
            d[f"tier_B_sensitivity_{name}"] = dict(n=len(mem), sensitivity=round(float(np.mean([sc[r["item_id"]] >= t5 for r in mem])), 3) if mem else None)
        lng = terc["long"]
        for name, cond in (("truncated", lambda r: n[r["item_id"]] > lim), ("not_truncated", lambda r: n[r["item_id"]] <= lim)):
            mem = [r for r in lng if cond(r) and r["item_id"] in sc]
            d[f"long_tercile_sensitivity_{name}"] = dict(n=len(mem), sensitivity=round(float(np.mean([sc[r["item_id"]] >= t5 for r in mem])), 3) if mem else None)
        trunc[m] = d
    res["truncation"] = dict(tier_B_n=len(tb), tercile_line_cutoffs=[float(q1), float(q2)], methods=trunc)

    # 4. compile validity
    cf = DET / "compile.csv"
    if cf.exists():
        comp = {r["item_id"]: int(r["compiles"]) for r in csv.DictReader(open(cf, encoding="utf-8"))}
        rate = collections.defaultdict(list)
        for r in rows:
            if r["item_id"] in comp and r["set"] in ("train", "val", "test", "seen_test", "pck", "pck_ai"):
                grp = "pck_submission" if r["set"] == "pck" else "pck_assistant_block" if r["set"] == "pck_ai" else ("codenet_ai" if r["label"] == 1 else "codenet_human")
                rate[(grp, r["language"])].append(comp[r["item_id"]])
                rate[(grp, "all")].append(comp[r["item_id"]])
        hum = [r for r in rows if r["source"] == "codenet" and r["label"] == 0 and r["item_id"] in comp]
        by_status = collections.defaultdict(list)
        for r in hum:
            by_status[r["status"]].append(comp[r["item_id"]])
        test_ok = [r for r in test if comp.get(r["item_id"]) == 1]
        res["compile_validity"] = dict(
            rates={f"{g}|{l}": dict(n=len(v), compiles=round(float(np.mean(v)), 3)) for (g, l), v in sorted(rate.items())},
            codenet_human_by_status={k: dict(n=len(v), compiles=round(float(np.mean(v)), 3)) for k, v in sorted(by_status.items())},
            test_compiling=dict(n=len(test_ok), human=sum(r["label"] == 0 for r in test_ok), ai=sum(r["label"] == 1 for r in test_ok)),
            auc_compiling_only={"__".join(k): dict(all=auc(S[k], test)[0], compiling_only=auc(S[k], test_ok)[0]) for k in MAIN if k in S})

    # 5. length matching (nearest human of the same language, without replacement)
    rng = np.random.default_rng(6399)
    matched = []
    for lang in ("C", "C++", "Java"):
        hs = [r for r in test if r["label"] == 0 and r["language"] == lang]
        ais = [r for r in test if r["label"] == 1 and r["language"] == lang]
        rng.shuffle(ais)
        pool = list(hs)
        for a in ais:
            if not pool:
                break
            j = min(range(len(pool)), key=lambda i: abs(int(pool[i]["chars"]) - int(a["chars"])))
            if abs(int(pool[j]["chars"]) - int(a["chars"])) <= 0.2 * int(a["chars"]):
                matched += [a, pool.pop(j)]
    res["length_matched"] = dict(pairs=len(matched) // 2,
                                 median_chars_ai=int(np.median([int(r["chars"]) for r in matched if r["label"] == 1])),
                                 median_chars_human=int(np.median([int(r["chars"]) for r in matched if r["label"] == 0])),
                                 unmatched_median_chars=dict(ai=int(np.median([int(r["chars"]) for r in test if r["label"] == 1])),
                                                             human=int(np.median([int(r["chars"]) for r in test if r["label"] == 0]))),
                                 auc={"__".join(k): dict(all=auc(S[k], test)[0], length_matched=auc(S[k], matched)[0]) for k in MAIN if k in S})
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
