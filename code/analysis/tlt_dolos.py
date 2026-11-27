r"""similarity baseline: Dolos 2.10.0 (Maertens et al.) against freshly generated AI reference solutions.

  python code/analysis/tlt_dolos.py statements --zip D:\session-records.zip   # PCK problem statements (contest material)
  python code/analysis/tlt_dolos.py refs                                             # PCK references, 4 local generators x 3 languages
  python code/analysis/tlt_dolos.py score                                            # Dolos max similarity per item

**References:** for CodeNet items, the four generated programs for the same problem and language (tlt_generate.py);
an AI item is compared only with the other three generators' programs, never with its own. For PCK submissions,
references are generated the same way from the English PCK problem statements (same prompt, temperature and seeds as
tlt_generate.py). The PCK assistant's own answers are **not** references: this baseline measures overlap with what local
models write for the problem, not reuse of the logged answer.

**Score:** the maximum Dolos pair similarity between the item and its references (Dolos default k-gram and window).
Reported separately from the detectors: it measures overlap with reference solutions, not authorship.

Outputs: D:\tlt\pck_statements\<problem>.md, D:\tlt\pck_refs\<gen>\<problem>_<ext>.<ext> (no participant data),
DET/scores/dolos__refs__raw.csv (outside Git).
"""
from __future__ import annotations

import csv
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from tlt_detect_data import DET, GENS  # noqa: E402
from tlt_generate import GENS as GEN_TAGS, LANGS, ask  # noqa: E402

STM, REFS, GEN = Path("D:/tlt/pck_statements"), Path("D:/tlt/pck_refs"), Path("D:/tlt/gen")
DOLOS = Path("D:/tlt/dolos/node_modules/.bin/dolos.cmd")
DL = {"C": "c", "C++": "cpp", "Java": "java"}


def statements(zpath):
    z = zipfile.ZipFile(zpath)
    STM.mkdir(parents=True, exist_ok=True)
    got = {}
    for n in sorted(z.namelist()):
        m = re.search(r"problem_translations/(\d+)\.en\.md$", n)
        if m and m.group(1) not in got:
            got[m.group(1)] = z.read(n).decode("utf-8", "replace")
    for pid, t in got.items():
        (STM / f"{pid}.md").write_text(t, encoding="utf-8")
    print("statements", len(got), sorted(got))


def refs():
    for key, model in GEN_TAGS.items():
        (REFS / key).mkdir(parents=True, exist_ok=True)
        for i, f in enumerate(sorted(STM.glob("*.md"))):
            for j, (lang, ext) in enumerate(LANGS.items()):
                out = REFS / key / f"{f.stem}_{ext}.{ext}"
                if out.exists():
                    continue
                prompt = (f"{f.read_text(encoding='utf-8')[:6000]}\n\nWrite a complete {lang} program that solves this problem. It must read "
                          f"from standard input and write to standard output. Reply with the code only, in one code block.")
                r = ask(model, prompt, 7311 + 3 * i + j)
                txt = r.get("response", "")
                m = re.search(r"```[^\n]*\n(.*?)```", txt, re.S)
                out.write_text((m.group(1) if m else txt).strip() + "\n", encoding="utf-8")
        print("refs done", key, flush=True)


def dolos_max(item_text, lang, ref_texts):
    if not ref_texts:
        return None
    ext = {"C": "c", "C++": "cpp", "Java": "java"}[lang]
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        (d / f"item.{ext}").write_text(item_text, encoding="utf-8")
        for k, t in enumerate(ref_texts):
            (d / f"ref{k}.{ext}").write_text(t, encoding="utf-8")
        files = [str(d / f"item.{ext}")] + [str(d / f"ref{k}.{ext}") for k in range(len(ref_texts))]
        subprocess.run([str(DOLOS), "run", "-l", DL[lang], "-f", "csv", "-o", str(d / "o")] + files,
                       capture_output=True, text=True, timeout=300)
        best = 0.0
        p = d / "o" / "pairs.csv"
        if not p.exists():
            return None
        for r in csv.DictReader(open(p, encoding="utf-8")):
            if Path(r["leftFilePath"]).stem == "item" or Path(r["rightFilePath"]).stem == "item":
                best = max(best, float(r["similarity"]))
        return best


def score():
    rows = list(csv.DictReader(open(DET / "items.csv", encoding="utf-8")))
    pck_problem_no = lambda pid: str(int(pid))           # judge problem_id is the statement number (e.g. 795)
    out = []
    for r in rows:
        if r["set"] not in ("val", "test", "seen_test", "pck"):
            continue
        ext = {"C": "c", "C++": "cpp", "Java": "java"}[r["language"]]
        if r["source"] == "codenet":
            refs_ = [GEN / g / f"{r['problem']}_{ext}.{ext}" for g in GENS if g != r["generator"]]
        else:
            refs_ = [REFS / g / f"{pck_problem_no(r['problem'])}_{ext}.{ext}" for g in GENS]
        texts = [p.read_text(encoding="utf-8", errors="replace") for p in refs_ if p.exists()]
        s = dolos_max((DET / "code" / f"{r['item_id']}.txt").read_text(encoding="utf-8", errors="replace"), r["language"], texts)
        if s is not None:
            out.append((r["item_id"], s))
    (DET / "scores").mkdir(exist_ok=True)
    with open(DET / "scores" / "dolos__refs__raw.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["item_id", "score"])
        w.writerows((i, f"{s:.6f}") for i, s in out)
    print("dolos scored", len(out))


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["statements", "refs", "score"])
    ap.add_argument("--zip", type=Path, default=Path(r"D:\session-records.zip"))
    a = ap.parse_args()
    {"statements": lambda: statements(a.zip), "refs": refs, "score": score}[a.mode]()
