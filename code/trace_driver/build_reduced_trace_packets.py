r"""the reduced record configuration E1+E+T (assistant output R-A, editor events and
source captures R-E, chronology R-T; prompts R-U and proposals R-P withheld) for all 36 controlled-trace runs.

Each reduced packet is derived from the full-record trace packet of the same run by removing the R-U and R-P sections
and rewriting the header in the format of code/analysis/tlt_rq4_packets.py ("Configuration packet (E1+E+T)").
Nothing else is changed. Every reduced packet gets a new random ID (never one of the full-record IDs), so a coder
cannot link it to the full packet of the same run. The scenario key goes to key_reduced.csv only.

  python code/trace_driver/build_reduced_trace_packets.py

Output: D:\tlt\trace\packets\reduced\T*.md, D:\tlt\trace\key_reduced.csv, D:\tlt\trace\batches\trace_red_NN.txt.
The full-record packets, key.csv, key_ext.csv and out\ are only read.
"""
import csv
import json
import random
import re
import sys
from pathlib import Path

T = Path(r"D:\tlt\trace")
# --config Full-U builds the recommended configuration (prompts withheld, proposals kept)
CFG = sys.argv[sys.argv.index("--config") + 1] if "--config" in sys.argv else "E1+E+T"
if CFG == "Full-U":
    KEEP, WITHHELD = ["R-A", "R-P", "R-E", "R-T"], ["R-U"]
    DROP = ("## User messages and attached files (R-U)",)
    SUFFIX, KEYNAME, BATCH = "reduced_fullu", "key_reduced_fullu.csv", "trace_redU_"
else:
    KEEP, WITHHELD = ["R-A", "R-E", "R-T"], ["R-U", "R-P"]
    DROP = ("## User messages and attached files (R-U)", "## Proposal events (R-P)")
    SUFFIX, KEYNAME, BATCH = "reduced", "key_reduced.csv", "trace_red_"


def reduce(text, cid):
    lines = text.splitlines()
    assert lines[0].startswith("# Reference packet (full record) "), lines[0]
    out, skip = [], False
    for ln in lines[1:]:
        if ln.startswith("## "):
            skip = ln.strip() in DROP
        if ln.startswith("Record types present:"):
            ln = f"Record types present: {', '.join(KEEP)}."
        elif ln.startswith("withheld:"):
            ln = f"withheld: [{', '.join(WITHHELD)}]"
        if not skip:
            out.append(ln)
    body = "\n".join([f"# Configuration packet ({CFG}) {cid}"] + out) + "\n"
    assert "(R-U)" not in body and "## Assistant answers (R-A)" in body
    assert ("## Proposal events (R-P)" in body) == ("R-P" in KEEP)
    assert not re.search(r"^### Request Q\d", body, re.M)
    return body


def main():
    rows = []
    for keyname, pdir in (("key.csv", T / "packets"), ("key_ext.csv", T / "packets" / "ext")):
        for r in csv.DictReader(open(T / keyname, encoding="utf-8")):
            if r.get("packet_id"):
                rows.append((r, pdir / f"{r['packet_id']}.md"))
    odir = T / "packets" / SUFFIX
    odir.mkdir(parents=True, exist_ok=True)
    for old in list(odir.glob("T*.md")) + list((T / "batches").glob(f"{BATCH}*.txt")):
        old.unlink()
    used = {p.stem for p in (T / "packets").rglob("T*.md") if p.parent != odir}
    rng = random.Random()
    key = []
    for r, src in rows:
        while True:
            cid = f"T{rng.getrandbits(24):06x}"
            if cid not in used:
                used.add(cid)
                break
        (odir / f"{cid}.md").write_text(reduce(src.read_text(encoding="utf-8"), cid), encoding="utf-8")
        key.append(dict(packet_id=cid, run_id=r["run_id"], scenario=r["scenario"], full_packet_id=r["packet_id"]))
    with open(T / KEYNAME, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(key[0]))
        w.writeheader()
        w.writerows(key)
    paths = [odir / f"{k['packet_id']}.md" for k in key]
    rng.shuffle(paths)
    batches, cur, size = [], [], 0
    for p in paths:
        if cur and size + p.stat().st_size > 300 * 1024:
            batches.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += p.stat().st_size
    if cur:
        batches.append(cur)
    for i, b in enumerate(batches, 1):
        (T / "batches" / f"{BATCH}{i:02d}.txt").write_text("".join(str(x) + "\n" for x in b), encoding="utf-8")
    full = sum(src.stat().st_size for _, src in rows)
    red = sum(p.stat().st_size for p in paths)
    print(json.dumps(dict(packets=len(key), batches=len(batches), bytes_full=full, bytes_reduced=red, ratio=round(red / full, 3))))


if __name__ == "__main__":
    main()
