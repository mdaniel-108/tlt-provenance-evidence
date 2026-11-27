r"""detector data layer: items, splits, normalization and verified transformations.

  python code/analysis/tlt_detect_data.py --zip D:\session-records.zip

**Items** (one row each in DET/items.csv; code in DET/code/<item_id>.txt):

| Source | Label | Sets |
|---|---|---|
| CodeNet human (tlt_codenet_select.py) | 0 | by problem split; within the 80 train problems, 1 of 6 human submissions per problem and language is held out as `seen_test` |
| CodeNet AI (tlt_generate.py, 4 generators) | 1 | by problem split; within train problems, one generator per problem and language (rotating) is held out as `seen_test` |
| PCK submissions | tier labels (tlt_pck_labels.py) | `pck` (evaluation only; never used to fit or threshold) |
| PCK logged AI code blocks (>= 5 lines, deduplicated) | 1 | `pck_ai` (PCK-in-domain training variant only, by participant fold) |

**Normalization:** comments removed, string literals kept, whitespace collapsed to single spaces per line, blank lines removed.

**Transformations** of `test` items (robustness, RQ2/RQ3):
- `rename` (verified): identifiers that are not keywords, library names or members are renamed to v1, v2, ... consistently;
  verified by equal token count and equal token kinds after the change;
- `reformat` (verified): re-indented by brace depth with 2 spaces, one statement per line kept; verified by an identical
  normalized token sequence;
- `paraphrase` (unverified rewrite): a local model (phi4-mini via Ollama) is asked to rewrite the program without changing
  behaviour. It is not checked for behaviour and is labelled as unverified.

DET = private_data/datasets/audit/tlt_detect (outside Git: it holds PCK code).
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import random
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
PROJECT = Path("../private_data")
DET = PROJECT / "datasets" / "audit" / "tlt_detect"
SEL, GEN = Path("D:/tlt/sel"), Path("D:/tlt/gen")
JUDGE = PROJECT / "datasets" / "pck2026_oln2026"
GENS = ["qwen", "llama", "granite", "phi"]
EXT = {"C": "c", "C++": "cpp", "Java": "java"}

KW = set("""auto break case char const continue default do double else enum extern float for goto if inline int long register
restrict return short signed sizeof static struct switch typedef union unsigned void volatile while bool true false class
public private protected new delete this namespace using template typename virtual friend operator try catch throw nullptr
include define std cin cout cerr endl string vector map set pair queue stack deque priority_queue unordered_map unordered_set
main printf scanf puts gets getchar putchar malloc free memset memcpy strlen strcmp sort min max abs swap make_pair push_back
pop_back size begin end first second insert erase find count emplace_back front back top push pop empty clear resize reserve
import package extends implements interface final abstract synchronized native transient instanceof super null String
System out println print printf Scanner nextInt nextLong nextLine next nextDouble hasNext Math Integer Long Double ArrayList
List HashMap Map HashSet Set Arrays Collections BufferedReader InputStreamReader IOException Exception args length charAt
substring equals parseInt parseLong split trim toCharArray StringBuilder append toString in close long_long
fixed setprecision ios sync_with_stdio tie getline lower_bound upper_bound accumulate reverse bits stdc iostream cstdio
cstring cmath algorithm stdio stdlib math string_h""".split())
TOKEN = re.compile(r"[A-Za-z_]\w*|\d+\.?\d*|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|\S")


def strip_comments(code):
    out, i, n = [], 0, len(code)
    while i < n:
        c = code[i]
        if c in "\"'":
            j = i + 1
            while j < n and code[j] != c:
                j += 2 if code[j] == "\\" else 1
            out.append(code[i:j + 1])
            i = j + 1
        elif code.startswith("//", i):
            j = code.find("\n", i)
            i = n if j < 0 else j
        elif code.startswith("/*", i):
            j = code.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def normalize(code):
    lines = [re.sub(r"\s+", " ", l).strip() for l in strip_comments(code).splitlines()]
    return "\n".join(l for l in lines if l) + "\n"


def tokens(code):
    return TOKEN.findall(strip_comments(code))


def kind(t):
    return "id" if re.match(r"[A-Za-z_]", t) else "num" if t[0].isdigit() else "str" if t[0] in "\"'" else t


def rename(code):
    toks = tokens(code)
    prev = {}
    names = {}
    body = strip_comments(code)
    res, last = [], None
    for m in TOKEN.finditer(body):
        t = m.group(0)
        if re.match(r"[A-Za-z_]\w*$", t) and t not in KW and last not in (".", "->", "::", "#") and not t.isupper():
            names.setdefault(t, f"v{len(names) + 1}")
            res.append((m.start(), m.end(), names[t]))
        last = t
    out, pos = [], 0
    for a, b, r in res:
        out.append(body[pos:a])
        out.append(r)
        pos = b
    out.append(body[pos:])
    new = "".join(out)
    nt = tokens(new)
    ok = len(nt) == len(toks) and [kind(x) for x in nt] == [kind(x) for x in toks]
    return new, ok


def reformat(code):
    depth, out = 0, []
    for l in normalize(code).splitlines():
        if l.startswith("}"):
            depth = max(0, depth - l.count("}") + l.count("{")) if l.count("{") else max(0, depth - 1)
            out.append("  " * depth + l)
            if l.count("{"):
                depth += 0
            continue
        out.append("  " * depth + l)
        depth = max(0, depth + l.count("{") - l.count("}"))
    new = "\n".join(out) + "\n"
    return new, tokens(new) == tokens(code)


def guess_lang(code):
    if re.search(r"\bpublic\s+(static\s+)?(class|void)\b|System\.out|import\s+java", code):
        return "Java"
    if re.search(r"#include\s*<(iostream|bits/stdc\+\+\.h|vector|string|algorithm|map|set)>|\bstd::|\bcout\b|\bcin\b|using\s+namespace", code):
        return "C++"
    if re.search(r"#include\s*<stdio\.h>|\bprintf\s*\(|\bscanf\s*\(", code):
        return "C"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, default=Path(r"D:\session-records.zip"))
    a = ap.parse_args()
    rng = random.Random(6312)
    (DET / "code").mkdir(parents=True, exist_ok=True)
    items = []

    def add(iid, text, **kw):
        (DET / "code" / f"{iid}.txt").write_text(text, encoding="utf-8")
        items.append(dict(item_id=iid, chars=len(text), lines=text.count("\n") + 1, **kw))

    probs = {r["problem_id"]: r for r in csv.DictReader(open(SEL / "problems.csv", encoding="utf-8"))}
    human = list(csv.DictReader(open(SEL / "human.csv", encoding="utf-8")))
    by = collections.defaultdict(list)
    for h in human:
        by[(h["problem_id"], h["language"])].append(h)
    for (p, l), hs in sorted(by.items()):
        split = probs[p]["split"]
        hold = rng.randrange(len(hs)) if split == "train" else -1
        for i, h in enumerate(hs):
            f = SEL / "code" / f"{h['submission_id']}.{h['ext']}"
            if not f.exists():
                continue
            s = "seen_test" if i == hold else split
            add(f"cnh_{h['submission_id']}", f.read_text(encoding="utf-8", errors="replace"), source="codenet", label=1 - 1, set=s,
                problem=p, language=l, generator="", status=h["status"], participant="")
    for p, pr in sorted(probs.items()):
        for j, l in enumerate(EXT):
            hold = GENS[(int(p[1:]) + j) % 4] if pr["split"] == "train" else None
            for g in GENS:
                f = GEN / g / f"{p}_{EXT[l]}.{EXT[l]}"
                if not f.exists():
                    continue
                s = "seen_test" if g == hold else pr["split"]
                add(f"cna_{g}_{p}_{EXT[l]}", f.read_text(encoding="utf-8", errors="replace"), source="codenet", label=1, set=s,
                    problem=p, language=l, generator=g, status="", participant="")
    labels = {r["submission_id"]: r for r in csv.DictReader(open(PROJECT / "datasets" / "audit" / "tlt_labels.csv", encoding="utf-8"))}
    for s in csv.DictReader(open(JUDGE / "submissions.csv", encoding="utf-8-sig")):
        lb = labels[s["submission_id"]]
        add(f"pck_{s['submission_id']}", (JUDGE / s["code_path"]).read_text(encoding="utf-8"), source="pck", label=-1, set="pck",
            problem=s["problem_id"], language=s["language"], generator="", status=s["verdict"], participant=s["user_id"])
    # PCK logged AI code blocks (in-domain variant)
    from build_episode_audit import ai_code_blocks, jsonl, pno
    z = zipfile.ZipFile(a.zip)
    seen = set()
    for r in jsonl(z, "data/analysis/proxy_calls.jsonl"):
        if r.get("operation") or r.get("status") != "success" or not pno(r.get("problem_id")):
            continue
        for _, b in ai_code_blocks(r):
            h = hashlib.sha1(normalize(b).encode()).hexdigest()
            lang = guess_lang(b)
            if h in seen or not lang or b.count("\n") < 4:
                continue
            seen.add(h)
            add(f"pai_{h[:12]}", b, source="pck_ai", label=1, set="pck_ai", problem=str(pno(r.get("problem_id"))), language=lang,
                generator="pck_logged", status="", participant=r.get("participant"))
    # transformations of test items
    tr = collections.Counter()
    for it in [i for i in items if i["set"] == "test"]:
        code = (DET / "code" / f"{it['item_id']}.txt").read_text(encoding="utf-8")
        for name, fn in (("rename", rename), ("reformat", reformat)):
            new, ok = fn(code)
            tr[(name, ok)] += 1
            if ok:
                add(f"{it['item_id']}__{name}", new, **{k: it[k] for k in ("source", "label", "problem", "language", "generator", "status", "participant")},
                    set=f"test_{name}")
    with open(DET / "items.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(items[0]))
        w.writeheader()
        w.writerows(items)
    agg = dict(by_set_label={f"{k[0]}|{k[1]}": v for k, v in sorted(collections.Counter((i["set"], i["label"]) for i in items).items())},
               transformations_verified={f"{k[0]}|{'ok' if k[1] else 'failed'}": v for k, v in sorted(tr.items())},
               pck_ai_blocks_by_language=dict(collections.Counter(i["language"] for i in items if i["set"] == "pck_ai")),
               pck_ai_participants=len({i["participant"] for i in items if i["set"] == "pck_ai"}))
    out = ROOT / "results" / "detect_items.json"
    out.write_text(json.dumps(agg, indent=2), encoding="utf-8")
    print(json.dumps(agg, indent=2))


if __name__ == "__main__":
    main()
