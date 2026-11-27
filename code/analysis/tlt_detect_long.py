r"""long-input variants vs the 512/1,024-token originals. Aggregates only.

  python code/analysis/tlt_detect_long.py

Compares droid offshelf vs offshelf_chunk (max over 1,024-token windows), unixcoder ext vs ext_ht and qwenlora ext vs
ext_ht (first and last 256 tokens, retrained). Threshold: 5% of CodeNet validation human code, per score file.
Output: results/detection_long.json
"""
import collections, csv, json, random, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from tlt_detect_data import DET, PROJECT  # noqa: E402
from tlt_detect_eval import auc, boot_sens, load_scores, thr  # noqa: E402

rows = list(csv.DictReader(open(DET / "items.csv", encoding="utf-8")))
for r in rows:
    r["label"] = int(r["label"])
by = collections.defaultdict(list)
for r in rows:
    by[r["set"]].append(r)
lab = {f"pck_{r['submission_id']}": r for r in csv.DictReader(open(PROJECT / "datasets" / "audit" / "tlt_labels.csv", encoding="utf-8"))}
tb = [r for r in by["pck"] if lab[r["item_id"]]["stratum"] == "near_verbatim" and lab[r["item_id"]]["tier_B"] == "1"]
unk = [r for r in by["pck"] if lab[r["item_id"]]["unknown"] == "1"]
ln = sorted(int(r["lines"]) for r in tb)
q1, q2 = np.quantile(ln, [1 / 3, 2 / 3])
terc = {"short": [r for r in tb if int(r["lines"]) <= q1], "medium": [r for r in tb if q1 < int(r["lines"]) <= q2], "long": [r for r in tb if int(r["lines"]) > q2]}
val_h = [r["item_id"] for r in by["val"] if r["label"] == 0]
S = load_scores()
rng = random.Random(6314)
res = {}
for m, a, b in (("droid", "offshelf", "offshelf_chunk"), ("unixcoder", "ext", "ext_ht"), ("qwenlora", "ext", "ext_ht")):
    for reg in (a, b):
        k = (m, reg, "raw")
        if k not in S:
            continue
        sc = S[k]
        t = thr(sc, val_h, 0.05)
        fl = lambda mem: [int(sc[r["item_id"]] >= t) for r in mem if r["item_id"] in sc]
        f = fl(tb)
        res[f"{m}__{reg}"] = dict(codenet_unseen_auc=auc(sc, by["test"])[0],
                                  tier_B=boot_sens(f, [r["participant"] for r in tb if r["item_id"] in sc], rng),
                                  by_tercile={k2: round(float(np.mean(fl(v))), 3) for k2, v in terc.items()},
                                  unknown=round(float(np.mean(fl(unk))), 3),
                                  # CodeNet test human false-positive rate at the same threshold
                                  codenet_test_human_fpr=round(float(np.mean(fl([r for r in by["test"] if r["label"] == 0]))), 3))
res["tercile_cut_lines"] = [float(q1), float(q2)]          # ties at a cut go to the lower tercile
out = ROOT / "results" / "detection_long.json"
out.write_text(json.dumps(res, indent=1), encoding="utf-8")
print(json.dumps(res, indent=1))
