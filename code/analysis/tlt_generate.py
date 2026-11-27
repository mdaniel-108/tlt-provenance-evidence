r"""AI class: generate solutions for the selected CodeNet problems with local open models (Ollama on localhost only).

  python code/analysis/tlt_generate.py            # resumable; skips outputs that exist

**Generators** (four families; none is a model used in the two 2025 PCK papers):

| Key | Ollama tag | Family |
|---|---|---|
| qwen | qwen2.5-coder:7b | Alibaba Qwen |
| llama | llama3.1:8b | Meta Llama |
| granite | granite-code:8b | IBM Granite |
| phi | phi4-mini | Microsoft Phi |

**Prompt:** the problem statement (HTML converted to text), then one instruction: write a complete program in the
language that reads standard input and writes standard output, and reply with the code only. Temperature 0.2,
seed 6311 + item index, at most 1,536 new tokens, context 4,096.

The first fenced code block is kept; if there is none, the whole reply is kept and flagged. Outputs (outside Git):
D:\tlt\gen\<key>\<problem>_<lang>.<ext> and D:\tlt\gen\gen_log.csv. GPU: Ollama places only what fits in free VRAM and
offloads the rest to the CPU, so the other GPU process is not displaced.
"""
from __future__ import annotations

import csv
import html
import json
import re
import time
import urllib.request
from pathlib import Path

CN = Path("D:/tlt/codenet/Project_CodeNet")
SEL = Path("D:/tlt/sel")
GEN = Path("D:/tlt/gen")
GENS = {"qwen": "qwen2.5-coder:7b", "llama": "llama3.1:8b", "granite": "granite-code:8b", "phi": "phi4-mini"}
LANGS = {"C": "c", "C++": "cpp", "Java": "java"}
URL = "http://127.0.0.1:11434/api/generate"


def statement(pid):
    h = (CN / "problem_descriptions" / f"{pid}.html").read_text(encoding="utf-8", errors="replace")
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</pre>|</li>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", " ", h))
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()[:6000]


def ask(model, prompt, seed):
    body = json.dumps(dict(model=model, prompt=prompt, stream=False, keep_alive="10m",
                           options=dict(temperature=0.2, seed=seed, num_predict=1536, num_ctx=4096))).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read())


def main():
    probs = list(csv.DictReader(open(SEL / "problems.csv", encoding="utf-8")))
    GEN.mkdir(parents=True, exist_ok=True)
    log = GEN / "gen_log.csv"
    new = not log.exists()
    with open(log, "a", newline="", encoding="utf-8") as fo:
        w = csv.writer(fo)
        if new:
            w.writerow(["generator", "problem_id", "language", "split", "fenced", "chars", "seconds", "eval_count"])
        idx = 0
        for key, model in GENS.items():          # one generator at a time, so one model is resident
            (GEN / key).mkdir(exist_ok=True)
            for p in probs:
                st = statement(p["problem_id"])
                for lang, ext in LANGS.items():
                    idx += 1
                    f = GEN / key / f"{p['problem_id']}_{ext}.{ext}"
                    if f.exists():
                        continue
                    prompt = (f"{st}\n\nWrite a complete {lang} program that solves this problem. It must read from standard input "
                              f"and write to standard output. Reply with the code only, in one code block.")
                    t0 = time.time()
                    try:
                        r = ask(model, prompt, 6311 + idx)
                    except Exception as e:      # noqa: BLE001
                        print("error", key, p["problem_id"], lang, e)
                        continue
                    txt = r.get("response", "")
                    m = re.search(r"```[^\n]*\n(.*?)```", txt, re.S)
                    code = (m.group(1) if m else txt).strip() + "\n"
                    f.write_text(code, encoding="utf-8")
                    w.writerow([key, p["problem_id"], lang, p["split"], bool(m), len(code), round(time.time() - t0, 1), r.get("eval_count")])
                    fo.flush()
            print("done", key, flush=True)


if __name__ == "__main__":
    main()
