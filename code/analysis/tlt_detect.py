r"""detectors: score every item with every method, per training regime.

  python code/analysis/tlt_detect.py classical      # Token LR, Structural GB (CPU)
  python code/analysis/tlt_detect.py lm             # log-likelihood, log-rank, Binoculars (GPU, zero-shot)
  python code/analysis/tlt_detect.py droid          # DroidDetect-Base-Binary, off the shelf (GPU)
  python code/analysis/tlt_detect.py unixcoder      # fine-tuned UniXcoder (GPU)
  python code/analysis/tlt_detect.py qwenlora       # Qwen2.5-Coder-1.5B + LoRA classifier (GPU)

Scores go to DET/scores/<method>__<regime>__<input>.csv (item_id, score; higher = more AI-like). Training uses only
`train` items; `val` fixes thresholds later (tlt_detect_eval.py); `seen_test`, `test`, transformed tests and `pck`
are scored only.

**Regimes:**
- `ext` (primary): CodeNet human + locally generated AI code;
- `pck` (secondary): `ext` plus PCK-logged AI blocks from the training participants of fold k (3 folds by participant);
  PCK submissions are scored only by the model of the fold that held their participant out;
- `logo_<g>` (transfer): `ext` without generator g; scored on g's held-out code.

**Inputs:** `raw` and `norm` (tlt_detect_data.normalize). GPU work is capped with torch.cuda.set_per_process_memory_fraction
so that only free memory is used (memory share computed from nvidia-smi at start; never above the free share).
"""
from __future__ import annotations

import csv
import math
import random
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from tlt_detect_data import DET, GENS, normalize, strip_comments, tokens  # noqa: E402

HF = Path("D:/tlt/hf/hub")
SC = DET / "scores"
SEED = 6313


def items():
    rows = list(csv.DictReader(open(DET / "items.csv", encoding="utf-8")))
    for r in rows:
        r["label"] = int(r["label"])
    return rows


def text(r, inp):
    t = (DET / "code" / f"{r['item_id']}.txt").read_text(encoding="utf-8", errors="replace")
    return normalize(t) if inp == "norm" else t


def folds(rows):
    parts = sorted({r["participant"] for r in rows if r["source"] == "pck"})
    rng = random.Random(SEED)
    rng.shuffle(parts)
    return {p: i % 3 for i, p in enumerate(parts)}


def pnum(r):
    """PCK problem number 1-13: logged blocks carry it directly; submissions carry the judge ID (= 794 + number)."""
    p = int(r["problem"])
    return p - 794 if p > 100 else p


def regimes(rows):
    """Yield (regime, train_rows, score_rows)."""
    base = [r for r in rows if r["set"] == "train"]
    import os
    if os.environ.get("TLT_INDOMAIN") == "lopo":
        # PCK-in-domain with participants AND problems held out. The 13 problems are split into
        # 3 groups; model (kp, kq) trains on logged blocks of participants outside fold kp and problems outside group
        # kq, and scores only submissions of fold kp on group kq (plus val, to fix its own threshold).
        fd = folds(rows)
        probs = list(range(1, 14))
        random.Random(SEED + 1).shuffle(probs)
        pg = {p: i % 3 for i, p in enumerate(probs)}
        for kp in range(3):
            for kq in range(3):
                extra = [r for r in rows if r["set"] == "pck_ai" and fd.get(r["participant"], -1) != kp and pg[pnum(r)] != kq]
                sc = [r for r in rows if r["set"] == "pck" and fd.get(r["participant"]) == kp and pg[pnum(r)] == kq]
                sc += [r for r in rows if r["set"] == "val"]
                yield f"pcklp{kp}{kq}", base + extra, sc
        return
    scored_ext = [r for r in rows if r["set"] not in ("train", "pck_ai")]
    yield "ext", base, scored_ext
    fd = folds(rows)
    for k in range(3):
        extra = [r for r in rows if r["set"] == "pck_ai" and fd.get(r["participant"], -1) != k]
        sc = [r for r in rows if r["set"] == "pck" and fd.get(r["participant"]) == k]
        sc += [r for r in rows if r["set"] == "val"]          # each fold model fixes its own threshold
        if k == 0:
            sc += [r for r in rows if r["set"] in ("test", "seen_test")]
        yield f"pck{k}", base + extra, sc
    for g in GENS:
        tr = [r for r in base if r["generator"] != g]
        sc = [r for r in rows if r["set"] in ("val", "test") and (r["label"] == 0 or r["generator"] == g)]
        yield f"logo_{g}", tr, sc


def write(method, regime, inp, ids, scores):
    SC.mkdir(parents=True, exist_ok=True)
    f = SC / f"{method}__{regime}__{inp}.csv"
    with open(f, "w", newline="", encoding="utf-8") as fo:
        w = csv.writer(fo)
        w.writerow(["item_id", "score"])
        for i, s in zip(ids, scores):
            w.writerow([i, f"{float(s):.6f}"])


# ---------------- classical ----------------
def struct_features(code):
    raw = code.replace("\r\n", "\n")
    lines = raw.split("\n")
    nonblank = [l for l in lines if l.strip()]
    n = max(1, len(lines))
    nb = max(1, len(nonblank))
    sc = strip_comments(raw)
    com = len(raw) - len(sc)
    ind = [len(l) - len(l.lstrip(" \t")) for l in nonblank]
    ids = [t for t in tokens(raw) if re.match(r"[A-Za-z_]\w*$", t)]
    il = [len(t) for t in ids] or [0]
    ops = re.findall(r"[=+\-*/<>]=?|&&|\|\|", sc)
    spaced = re.findall(r" [=+\-*/<>]=? |  ?&& ?| ?\|\| ?", sc)
    return [
        len(lines), np.mean([len(l) for l in lines]), max(len(l) for l in lines), 1 - len(nonblank) / n, com / max(1, len(raw)),
        np.mean(ind) if ind else 0, sum("\t" in l[:4] for l in nonblank) / nb, np.mean(il), sum(len(t) == 1 for t in ids) / max(1, len(ids)),
        sum(bool(re.search(r"\)\s*\{\s*$", l)) for l in nonblank) / nb, sum(l.strip() == "{" for l in nonblank) / nb,
        len(spaced) / max(1, len(ops)), sum(bool(re.search(r"[a-z][A-Z]", t)) for t in ids) / max(1, len(ids)),
        sum("_" in t.strip("_") for t in ids) / max(1, len(ids)), sum(l != l.rstrip() for l in lines) / n, float(raw.endswith("\n")),
        raw.count("//") / nb, raw.count("/*") / nb, len(set(ids)) / max(1, len(ids)), raw.count(";") / nb,
        float("bits/stdc++" in raw), float("using namespace std" in raw), float("scanf" in raw), float("cin" in raw),
        float("BufferedReader" in raw), float("Scanner" in raw), raw.count("const ") / nb, raw.count("auto ") / nb,
        len(re.findall(r"\b(int|long|void|bool|char|double|string|String)\s+\w+\s*\(", raw)),
    ]


def classical():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from xgboost import XGBClassifier
    rows = items()
    for regime, tr, sc in regimes(rows):
        for inp in ("raw", "norm"):
            Xtr = [text(r, inp) for r in tr]
            ytr = [r["label"] for r in tr]
            Xsc = [text(r, inp) for r in sc]
            vec = TfidfVectorizer(tokenizer=lambda s: TOKS(s), lowercase=False, ngram_range=(1, 3), min_df=2, sublinear_tf=True, token_pattern=None)
            A = vec.fit_transform(Xtr)
            lr = LogisticRegression(C=4.0, max_iter=2000, class_weight="balanced", random_state=SEED).fit(A, ytr)
            write("tokenlr", regime, inp, [r["item_id"] for r in sc], lr.predict_proba(vec.transform(Xsc))[:, 1])
            if inp == "raw":   # structural features need raw layout
                F = np.array([struct_features(x) for x in Xtr])
                gb = XGBClassifier(n_estimators=400, max_depth=4, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8,
                                   random_state=SEED, n_jobs=4, eval_metric="logloss").fit(F, ytr)
                write("structgb", regime, inp, [r["item_id"] for r in sc], gb.predict_proba(np.array([struct_features(x) for x in Xsc]))[:, 1])
        print("classical", regime, len(tr), len(sc), flush=True)


def TOKS(s):
    return re.findall(r"[A-Za-z_]\w*|\d+|\S", s)


# ---------------- GPU helpers ----------------
def gpu_cap(torch):
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout.split(",")
    used, total = float(out[0]), float(out[1])
    frac = max(0.05, (total - used - 300) / total)       # leave 300 MiB headroom; never touch memory in use
    torch.cuda.set_per_process_memory_fraction(min(frac, 0.95), 0)
    print(f"GPU cap {frac:.2f} of {total:.0f} MiB (in use before start {used:.0f})", flush=True)
    return frac * total


def snap(repo):
    d = HF / ("models--" + repo.replace("/", "--")) / "snapshots"
    return str(next(d.iterdir()))


def scored_union(rows):
    """Zero-shot and off-the-shelf methods: every non-training item once."""
    return [r for r in rows if r["set"] not in ("pck_ai",)]


def lm():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    gpu_cap(torch)
    rows = scored_union(items())
    # log-likelihood and log-rank: Qwen2.5-Coder-1.5B. Binoculars: the 0.5B base/instruct pair, because two 1.5B models
    # do not fit in the free GPU memory next to the other process.
    tok = AutoTokenizer.from_pretrained(snap("Qwen/Qwen2.5-Coder-1.5B"))
    big = AutoModelForCausalLM.from_pretrained(snap("Qwen/Qwen2.5-Coder-1.5B"), torch_dtype=torch.float16).cuda().eval()
    for inp in ("raw", "norm"):
        ll, rk, ids = [], [], []
        for r in rows:
            x = tok(text(r, inp), return_tensors="pt", truncation=True, max_length=1024).input_ids.cuda()
            with torch.no_grad():
                logp = torch.log_softmax(big(x).logits[0, :-1].cpu().float(), -1)    # vocabulary-sized arrays on the CPU
            tl = logp.gather(1, x[0, 1:, None].cpu())[:, 0]
            rank = (logp > tl[:, None]).sum(1).float() + 1
            ll.append(tl.mean().item())
            rk.append(-torch.log(rank).mean().item())
            ids.append(r["item_id"])
        write("loglik", "zeroshot", inp, ids, ll)
        write("logrank", "zeroshot", inp, ids, rk)
        print("lm", inp, len(ids), flush=True)
    del big
    torch.cuda.empty_cache()
    obs = AutoModelForCausalLM.from_pretrained(snap("Qwen/Qwen2.5-Coder-0.5B"), torch_dtype=torch.float16).cuda().eval()
    perf = AutoModelForCausalLM.from_pretrained(snap("Qwen/Qwen2.5-Coder-0.5B-Instruct"), torch_dtype=torch.float16).cuda().eval()
    for inp in ("raw", "norm"):
        bino, ids = [], []
        for r in rows:
            x = tok(text(r, inp), return_tensors="pt", truncation=True, max_length=1024).input_ids.cuda()
            with torch.no_grad():
                logp = torch.log_softmax(obs(x).logits[0, :-1].cpu().float(), -1)
                pp = torch.softmax(perf(x).logits[0, :-1].cpu().float(), -1)
            tl = logp.gather(1, x[0, 1:, None].cpu())[:, 0]
            bino.append(-((-tl.mean()) / (-(pp * logp).sum(-1).mean())).item())   # low ratio = machine-like; negated
            ids.append(r["item_id"])
        write("binoculars", "zeroshot", inp, ids, bino)
        print("binoculars", inp, len(ids), flush=True)


def droid():
    import torch
    import torch.nn as nn
    from transformers import AutoModel, AutoTokenizer
    gpu_cap(torch)
    rows = scored_union(items())
    base = snap("answerdotai/ModernBERT-base")
    tok = AutoTokenizer.from_pretrained(base)

    sd = torch.load(Path(snap("project-droid/DroidDetect-Base-Binary")) / "pytorch_model.bin", map_location="cpu", weights_only=True)
    pdim = sd["text_projection.weight"].shape[0]          # 256 in the released checkpoint (its config.json says 128)

    class TL(nn.Module):
        def __init__(self):
            super().__init__()
            self.text_encoder = AutoModel.from_pretrained(base)
            self.text_projection = nn.Linear(768, pdim)
            self.classifier = nn.Linear(pdim, 2)

        def forward(self, ids, att):
            e = self.text_encoder(input_ids=ids, attention_mask=att).last_hidden_state.mean(1)
            return self.classifier(torch.relu(self.text_projection(e)))

    m = TL()
    missing, unexpected = m.load_state_dict(sd, strict=False)
    print("droid load: missing", len(missing), "unexpected", len(unexpected), flush=True)
    m = m.half().cuda().eval()
    import os
    chunk = os.environ.get("TLT_LONG") == "chunk"     # score every 1,024-token window, keep the maximum
    for inp in (("raw",) if chunk else ("raw", "norm")):
        ids, sc = [], []
        for r in rows:
            if chunk:
                full = tok(text(r, inp)).input_ids
                body = full[1:-1]
                wins = [body[i:i + 1022] for i in range(0, max(1, len(body)), 1022)] or [[]]
                ps = []
                for w in wins:
                    x = torch.tensor([[full[0]] + w + [full[-1]]]).cuda()
                    with torch.no_grad():
                        lg = m(x, torch.ones_like(x)).float()
                    ps.append(torch.softmax(lg, -1)[0, 1].item())
                sc.append(max(ps))
            else:
                e = tok(text(r, inp), return_tensors="pt", truncation=True, max_length=1024)
                with torch.no_grad():
                    lg = m(e.input_ids.cuda(), e.attention_mask.cuda()).float()
                sc.append(torch.softmax(lg, -1)[0, 1].item())
            ids.append(r["item_id"])
        write("droid", "offshelf_chunk" if chunk else "offshelf", inp, ids, sc)
        print("droid", inp, len(ids), flush=True)


def finetune(method):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    cap = gpu_cap(torch)
    rows = items()
    torch.manual_seed(SEED)
    if method == "unixcoder":
        repo, maxlen, bs, epochs, lr = "microsoft/unixcoder-base", 512, 8, 3, 2e-5
    else:
        repo, maxlen, bs, epochs, lr = "Qwen/Qwen2.5-Coder-1.5B", 512, 2, 1, 1e-4
    path = snap(repo)
    tok = AutoTokenizer.from_pretrained(path)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    regs = [g for g in regimes(rows) if method == "unixcoder" or not g[0].startswith("logo")]
    import os
    only = os.environ.get("TLT_ONLY_REGIME")      # rerun a single regime (e.g. after a failed run); others are kept
    if only:
        regs = [g for g in regs if g[0] == only]
    ht = os.environ.get("TLT_LONG") == "headtail"   # keep the first and last maxlen/2 tokens of long programs

    def enc(texts):
        out = []
        for t in texts:
            x = tok(t).input_ids
            if len(x) > maxlen:
                x = x[:maxlen // 2] + x[-(maxlen - maxlen // 2):] if ht else x[:maxlen]
            out.append(x)
        L = max(len(x) for x in out)
        ids_ = torch.tensor([x + [tok.pad_token_id] * (L - len(x)) for x in out])
        att = torch.tensor([[1] * len(x) + [0] * (L - len(x)) for x in out])
        return ids_, att

    for regime, tr, sc in regs:
        inp = "raw"
        model = AutoModelForSequenceClassification.from_pretrained(path, num_labels=2, torch_dtype=torch.float32 if method == "unixcoder" else torch.bfloat16)
        model.config.pad_token_id = tok.pad_token_id
        if method == "qwenlora":
            from peft import LoraConfig, get_peft_model
            model.gradient_checkpointing_enable()
            model = get_peft_model(model, LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05, task_type="SEQ_CLS",
                                                     target_modules=["q_proj", "k_proj", "v_proj", "o_proj"]))
        model.cuda()
        opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
        rng = random.Random(SEED)
        data = [(text(r, inp), r["label"]) for r in tr]
        scaler_dtype = torch.float16 if method == "unixcoder" else torch.bfloat16
        model.train()
        for ep in range(epochs):
            rng.shuffle(data)
            for i in range(0, len(data), bs):
                b = data[i:i + bs]
                xi, xa = enc([x for x, _ in b])
                with torch.autocast("cuda", dtype=scaler_dtype):
                    out = model(input_ids=xi.cuda(), attention_mask=xa.cuda(), labels=torch.tensor([y for _, y in b]).cuda())
                out.loss.backward()
                opt.step()
                opt.zero_grad()
        model.eval()
        ids, s = [], []
        for r in sc:
            xi, xa = enc([text(r, inp)])
            with torch.no_grad(), torch.autocast("cuda", dtype=scaler_dtype):
                lg = model(input_ids=xi.cuda(), attention_mask=xa.cuda()).logits.float()
            s.append(torch.softmax(lg, -1)[0, 1].item())
            ids.append(r["item_id"])
        write(method, regime + ("_ht" if ht else ""), inp, ids, s)
        print(method, regime, len(tr), len(sc), flush=True)
        del model, opt
        torch.cuda.empty_cache()


if __name__ == "__main__":
    {"classical": classical, "lm": lm, "droid": droid, "unixcoder": lambda: finetune("unixcoder"),
     "qwenlora": lambda: finetune("qwenlora")}[sys.argv[1]]()
