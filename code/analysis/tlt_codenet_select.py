r"""CodeNet selection: problems, human submissions and problem splits.

  python code/analysis/tlt_codenet_select.py select     # metadata only -> D:\tlt\sel\
  python code/analysis/tlt_codenet_select.py extract    # one pass over the tar for the selected files

**Problems:** CodeNet problems with a description and, in each of C, C++ and Java, at least 20 accepted and 10 non-accepted
submissions from distinct users. 120 problems, half AIZU and half AtCoder, seed 6310. Split by problem: 80 train,
20 validation (thresholds), 20 test (unseen problems).

**Human class (historical, presumed human; CodeNet collection ends in 2020):** per problem and language, 3 accepted and
3 non-accepted submissions (Wrong Answer, Time Limit Exceeded, Runtime Error, Memory Limit Exceeded, Compile Error), from
distinct users, seed 6310. Matching AI and human code on verdict is not feasible: CodeNet has no test cases to judge the
generated code, so the AI class is matched on problem and language only, and length is compared in the output.

Outputs (outside Git): D:\tlt\sel\problems.csv, human.csv, and D:\tlt\sel\code\<submission_id>.<ext>.
Aggregate counts: results/codenet_selection.json.
"""
from __future__ import annotations

import collections
import csv
import json
import random
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CN = Path("D:/tlt/codenet/Project_CodeNet")
TAR = Path("D:/tlt/codenet_dl/Project_CodeNet.tar.gz")
SEL = Path("D:/tlt/sel")
OUT = ROOT / "results"
LANGS = ["C", "C++", "Java"]
NONAC = {"Wrong Answer", "Time Limit Exceeded", "Runtime Error", "Memory Limit Exceeded", "Compile Error"}
N_PROB, MIN_AC, MIN_NON = 120, 20, 10


def select():
    rng = random.Random(6310)
    plist = {r["id"]: r for r in csv.DictReader(open(CN / "metadata" / "problem_list.csv", encoding="utf-8"))}
    ok = collections.defaultdict(list)
    pools = {}
    for pid, meta in sorted(plist.items()):
        if not (CN / "problem_descriptions" / f"{pid}.html").exists():
            continue
        f = CN / "metadata" / f"{pid}.csv"
        if not f.exists():
            continue
        by = collections.defaultdict(lambda: {"ac": {}, "non": {}})
        for r in csv.DictReader(open(f, encoding="utf-8")):
            if r["language"] not in LANGS:
                continue
            k = "ac" if r["status"] == "Accepted" else "non" if r["status"] in NONAC else None
            if k:
                by[r["language"]][k].setdefault(r["user_id"], r)      # one per user
        if all(len(by[l]["ac"]) >= MIN_AC and len(by[l]["non"]) >= MIN_NON for l in LANGS):
            ok[meta["dataset"]].append(pid)
            pools[pid] = by
    chosen = []
    for ds in ("AIZU", "AtCoder"):
        c = sorted(ok[ds])
        rng.shuffle(c)
        chosen += c[: N_PROB // 2]
    rng.shuffle(chosen)
    split = {p: ("train" if i < 80 else "val" if i < 100 else "test") for i, p in enumerate(chosen)}
    SEL.mkdir(parents=True, exist_ok=True)
    with open(SEL / "problems.csv", "w", newline="", encoding="utf-8") as fo:
        w = csv.writer(fo)
        w.writerow(["problem_id", "dataset", "name", "split"])
        for p in chosen:
            w.writerow([p, plist[p]["dataset"], plist[p]["name"], split[p]])
    rows = []
    for p in chosen:
        for l in LANGS:
            for k, n in (("ac", 3), ("non", 3)):
                users = sorted(pools[p][l][k])
                rng.shuffle(users)
                used = {r["user_id"] for r in rows if r["problem_id"] == p and r["language"] == l}
                for u in [u for u in users if u not in used][:n]:
                    r = pools[p][l][k][u]
                    rows.append(dict(submission_id=r["submission_id"], problem_id=p, language=l, user_id=u, status=r["status"],
                                     ext=r["filename_ext"], code_size=r["code_size"], split=split[p]))
    with open(SEL / "human.csv", "w", newline="", encoding="utf-8") as fo:
        w = csv.DictWriter(fo, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    info = dict(eligible_problems={k: len(v) for k, v in ok.items()}, chosen=len(chosen),
                chosen_by_dataset=dict(collections.Counter(plist[p]["dataset"] for p in chosen)),
                split=dict(collections.Counter(split.values())), human_submissions=len(rows),
                human_by_language=dict(collections.Counter(r["language"] for r in rows)),
                human_by_status=dict(collections.Counter(r["status"] for r in rows)),
                distinct_human_users=len({r["user_id"] for r in rows}))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "codenet_selection.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info, indent=2))


def extract():
    rows = list(csv.DictReader(open(SEL / "human.csv", encoding="utf-8")))
    want = {f"Project_CodeNet/data/{r['problem_id']}/{r['language']}/{r['submission_id']}.{r['ext']}": r for r in rows}
    (SEL / "code").mkdir(parents=True, exist_ok=True)
    got = 0
    with tarfile.open(TAR, "r|gz") as t:
        for m in t:
            r = want.get(m.name)
            if r and m.isfile():
                data = t.extractfile(m).read()
                (SEL / "code" / f"{r['submission_id']}.{r['ext']}").write_bytes(data)
                got += 1
    print("extracted", got, "of", len(want))


if __name__ == "__main__":
    {"select": select, "extract": extract}[sys.argv[1]]()
