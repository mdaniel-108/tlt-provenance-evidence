r"""do the items compile? Syntax/semantic check only (gcc/g++ -fsyntax-only, javac to a temp dir);
nothing is executed. Runs inside WSL (Ubuntu-22.04: gcc 11, g++ 11, OpenJDK javac).

  wsl -d Ubuntu-22.04 -e python3 code/analysis/tlt_compile_check.py

Input (outside Git): private_data/datasets/audit/tlt_detect/items.csv and code/<item_id>.txt
Output (outside Git): .../tlt_detect/compile.csv (item_id, compiles, seconds). Aggregates go to detection_checks.json
via tlt_detect_checks.py.
"""
import csv, os, re, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor

DET = "../private_data/datasets/audit/tlt_detect"
items = list(csv.DictReader(open(f"{DET}/items.csv", encoding="utf-8")))
done = {}
out = f"{DET}/compile.csv"
if os.path.exists(out):
    done = {r["item_id"]: r for r in csv.DictReader(open(out, encoding="utf-8"))}


def check(it):
    src = open(f"{DET}/code/{it['item_id']}.txt", encoding="utf-8", errors="replace").read()
    t0 = time.time()
    with tempfile.TemporaryDirectory() as d:
        lang = it["language"]
        if lang == "Java":
            m = re.search(r"public\s+(?:final\s+)?class\s+(\w+)", src)
            fn = os.path.join(d, (m.group(1) if m else "Main") + ".java")
            cmd = ["javac", "-nowarn", "-d", d, fn]
        else:
            fn = os.path.join(d, "a.c" if lang == "C" else "a.cpp")
            cmd = (["gcc", "-std=gnu11"] if lang == "C" else ["g++", "-std=gnu++17"]) + ["-fsyntax-only", "-w", fn]
        open(fn, "w", encoding="utf-8").write(src)
        try:
            ok = subprocess.run(cmd, capture_output=True, timeout=60).returncode == 0
        except subprocess.TimeoutExpired:
            ok = False
    return dict(item_id=it["item_id"], compiles=int(ok), seconds=round(time.time() - t0, 2))


todo = [it for it in items if it["item_id"] not in done]
print(len(items), "items;", len(todo), "to check", flush=True)
rows = list(done.values())
with ThreadPoolExecutor(max_workers=int(sys.argv[1]) if len(sys.argv) > 1 else 6) as ex:
    for i, r in enumerate(ex.map(check, todo), 1):
        rows.append(r)
        if i % 500 == 0:
            print(i, flush=True)
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["item_id", "compiles", "seconds"])
    w.writeheader(); w.writerows(rows)
print("done", sum(int(r["compiles"]) for r in rows), "of", len(rows))
