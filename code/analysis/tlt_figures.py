r"""manuscript figures from committed aggregate JSON only (no participant data).

  python code/analysis/tlt_figures.py

Fig. 1 (fig_transfer.pdf): per detector, CodeNet ROC-AUC on unseen problems vs share of PCK tier-B near-verbatim reuse
flagged (95% participant-clustered CI) and share of the unknown group flagged, at the CodeNet-validation 5% threshold.
Fig. 2 (fig_configs.pdf): agreement with the full-record reference per record configuration and claim (share of the
cases the reference resolved), with counts printed in each cell, and median packet size.
Palette validated with the dataviz validator (#1f6fb2, #c4621b: CVD and contrast checks pass); unknown in gray.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results"
FIG = ROOT / "figures"
BLUE, ORANGE, GRAY, INK = "#1f6fb2", "#c4621b", "#8a8a8a", "#222222"
plt.rcParams.update({"font.family": "serif", "font.size": 7.5, "axes.edgecolor": "#999999", "axes.linewidth": 0.6,
                     "xtick.color": INK, "ytick.color": INK, "axes.labelcolor": INK})


def fig_transfer():
    d = json.load(open(OUT / "detection.json"))["methods"]
    rows = [("Dolos (baseline)", "dolos__refs__raw"),        # the similarity baseline
            ("Binoculars", "binoculars__zeroshot__raw"), ("Log-rank", "logrank__zeroshot__raw"),
            ("Log-likelihood", "loglik__zeroshot__raw"), ("Token LR", "tokenlr__ext__raw"),
            ("Structural GB", "structgb__ext__raw"), ("DroidDetect", "droid__offshelf__raw"),
            ("Qwen + LoRA", "qwenlora__ext__raw"), ("UniXcoder", "unixcoder__ext__raw")]
    fig, ax = plt.subplots(figsize=(3.45, 2.55))
    for i, (name, k) in enumerate(rows):
        v = d[k]
        auc = v["codenet_test_unseen_problems"]["roc_auc"]
        b = v["pck"]["tier_B|near_verbatim|fpr5"]
        u = v["pck"]["unknown|all|fpr5"]["sensitivity"]
        ax.plot([b["sensitivity"], auc], [i, i], color="#d0d0d0", lw=1.2, zorder=1)
        ax.errorbar(b["sensitivity"], i, xerr=[[b["sensitivity"] - b["ci95"][0]], [b["ci95"][1] - b["sensitivity"]]],
                    fmt="o", ms=4.5, color=ORANGE, mec="white", mew=0.6, elinewidth=0.9, capsize=0, zorder=3)
        ax.plot(u, i, marker="D", ms=3.2, color=GRAY, mec="white", mew=0.5, ls="none", zorder=2)
        ax.plot(auc, i, marker="s", ms=4.2, color=BLUE, mec="white", mew=0.6, ls="none", zorder=3)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_xlim(-0.02, 1.02)
    ax.set_xlabel("Share or ROC-AUC")
    ax.grid(axis="x", color="#eeeeee", lw=0.5)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    h = [plt.Line2D([], [], marker="s", color=BLUE, ls="none", ms=4.2, label="CodeNet ROC-AUC (unseen problems)"),
         plt.Line2D([], [], marker="o", color=ORANGE, ls="none", ms=4.5, label="PCK tier B flagged (95% CI)"),
         plt.Line2D([], [], marker="D", color=GRAY, ls="none", ms=3.2, label="PCK unknown group flagged")]
    ax.legend(handles=h, loc="upper center", bbox_to_anchor=(0.42, 1.24), ncol=1, frameon=False, fontsize=6.6, handletextpad=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "fig_transfer.pdf", bbox_inches="tight")


def fig_configs():
    J = json.load(open(OUT / "rq4_main.json"))
    d = J["configurations"]
    mech = J.get("mechanism_check", {})      # C3 agrees only when the mechanism also matches
    order = [("E0", "Code only"), ("E1", "Assistant"), ("E1u", "Assistant + user"), ("E1u+P", "+ proposals"),
             ("E1+E+T", "Assistant + editor + time"), ("Full-A", "Full − assistant"), ("Full-U", "Full − user"),
             ("Full-P", "Full − proposals"), ("Full-E", "Full − editor"), ("Full-T", "Full − time")]
    claims = ["C1", "C2", "C3", "C4"]
    import numpy as np
    M = np.zeros((len(order), 4))
    fig, ax = plt.subplots(figsize=(3.45, 2.75))
    for i, (k, _) in enumerate(order):
        for j, c in enumerate(claims):
            t = mech[k][c] if mech else d[k][c]
            ag = t["agree"] if mech else t["agree_with_reference"]
            M[i, j] = ag / t["reference_resolved"] if t["reference_resolved"] else np.nan
    ax.imshow(M, cmap="Blues", vmin=0, vmax=1, aspect="auto")
    for i, (k, _) in enumerate(order):
        for j, c in enumerate(claims):
            t = mech[k][c] if mech else d[k][c]
            ag = t["agree"] if mech else t["agree_with_reference"]
            ax.text(j, i, f"{ag}/{t['reference_resolved']}", ha="center", va="center", fontsize=6.3,
                    color="white" if M[i, j] > 0.6 else INK)
        ax.text(4.0, i, f"{d[k]['cost']['median_packet_kb']:.0f} KB", ha="left", va="center", fontsize=6.3, color=INK)
    ax.set_xticks(range(4))
    ax.set_xticklabels(["C1", "C2", "C3", "C4"], fontsize=7)   # claim names are given in the caption
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([o[1] for o in order])
    ax.get_yticklabels()[6].set_fontweight("bold")   # Full-U, the recommended configuration
    for s in ax.spines.values():
        s.set_visible(False)
    ax.tick_params(length=0)
    ax.set_xlim(-0.5, 4.6)
    fig.tight_layout()
    fig.savefig(FIG / "fig_configs.pdf", bbox_inches="tight")


EXT = [("Token LR", "tokenlr__ext__raw"), ("Structural GB", "structgb__ext__raw"), ("Log-likelihood", "loglik__zeroshot__raw"),
       ("Log-rank", "logrank__zeroshot__raw"), ("Binoculars", "binoculars__zeroshot__raw"), ("DroidDetect", "droid__offshelf__raw"),
       ("UniXcoder", "unixcoder__ext__raw"), ("Qwen + LoRA", "qwenlora__ext__raw")]


def fig_funnel():
    """How the 1,047 submissions divide into reference groups (pck_labels.json)."""
    L = json.load(open(OUT / "pck_labels.json"))
    nv, ed, no = L["near_verbatim"], L["edited"], L["none"]
    rows = [("Near-verbatim\n(n = 895)", [nv["tier_A"], nv["tier_B"] - nv["tier_A"], nv["b_chain"], nv["unknown"]]),
            ("Edited\n(n = 57)", [ed["tier_A"], ed["tier_B"] - ed["tier_A"], ed["b_chain"], ed["unknown"]]),
            ("Unmatched\n(n = 95)", [0, 0, 0, no["unknown"]])]
    cols = ["#123f6b", "#3d82c4", "#9cc3e6", "#bdbdbd"]
    names = ["Tier A (broad rule)", "Tier B only (same-request rule)", "B-chain (earlier AI answer)", "Unknown provenance"]
    fig, ax = plt.subplots(figsize=(7.0, 1.55))
    for i, (lab, vals) in enumerate(rows):
        x = 0
        for v, c in zip(vals, cols):
            if v:
                ax.barh(i, v, left=x, color=c, edgecolor="white", linewidth=1.2, height=0.62)
                if v >= 18:
                    ax.text(x + v / 2, i, str(v), ha="center", va="center", fontsize=6.8, color="white" if c in cols[:2] else INK)
            x += v
    ax.set_yticks(range(3))
    ax.set_yticklabels([r[0] for r in rows], fontsize=7)
    ax.invert_yaxis()
    ax.set_xlim(0, 900)
    ax.set_xlabel("Submissions")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    hd = [plt.Rectangle((0, 0), 1, 1, color=c) for c in cols]
    ax.legend(hd, names, ncol=4, loc="lower center", bbox_to_anchor=(0.45, 1.0), frameon=False, fontsize=6.6, handlelength=1.0)
    fig.tight_layout()
    fig.savefig(FIG / "fig_funnel.pdf", bbox_inches="tight")


def fig_operating():
    """Separation: share of tier-B reuse flagged vs share of the unknown group flagged (detection.json)."""
    d = json.load(open(OUT / "detection.json"))["methods"]
    fig, ax = plt.subplots(figsize=(3.45, 3.0))
    ax.plot([0, 1], [0, 1], color="#cccccc", lw=0.8, ls="--", zorder=1)
    ax.text(0.62, 0.55, "no separation", rotation=40, fontsize=6.3, color="#888888")
    pts = [(n, k, BLUE) for n, k in EXT] + [("PCK-in-domain: " + n, k.replace("ext", "pck0"), ORANGE)
                                              for n, k in EXT if "__ext__" in k]
    off = {"Token LR": (4, -2), "Structural GB": (4, 2), "DroidDetect": (-46, 3), "UniXcoder": (-40, 3), "Qwen + LoRA": (4, -7)}
    zero = {"Log-rank", "Binoculars", "Log-likelihood"}
    ax.annotate("Log-likelihood, log-rank,\nBinoculars (zero-shot)", (0.02, 0.03), textcoords="offset points", xytext=(48, 26),
                fontsize=6.2, color=INK, arrowprops=dict(arrowstyle="-", color="#999999", lw=0.5))
    for n, k, c in pts:
        p = d[k]["pck"]
        x, y = p["unknown|all|fpr5"]["sensitivity"], p["tier_B|near_verbatim|fpr5"]["sensitivity"]
        ax.plot(x, y, "o" if c == BLUE else "s", ms=4.6, color=c, mec="white", mew=0.6, zorder=3)
        if c == BLUE and n not in zero:
            ax.annotate(n, (x, y), textcoords="offset points", xytext=off.get(n, (4, 2)), fontsize=6.2, color=INK)
    ax.set_xlim(-0.03, 1.03)
    ax.set_ylim(-0.03, 1.03)
    ax.set_xlabel("Unknown-provenance submissions flagged")
    ax.set_ylabel("Tier-B near-verbatim reuse flagged")
    ax.grid(color="#f0f0f0", lw=0.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    h = [plt.Line2D([], [], marker="o", color=BLUE, ls="none", ms=4.6, label="External, zero-shot or released"),
         plt.Line2D([], [], marker="s", color=ORANGE, ls="none", ms=4.6, label="PCK-in-domain (four trained models)")]
    ax.legend(handles=h, loc="upper left", bbox_to_anchor=(0.0, 1.04), frameon=False, fontsize=6.2)
    fig.tight_layout()
    fig.savefig(FIG / "fig_operating.pdf", bbox_inches="tight")


def fig_shift():
    """CodeNet ROC-AUC under four conditions per trainable detector (detection.json)."""
    D = json.load(open(OUT / "detection.json"))
    d, lg = D["methods"], D["leave_one_generator_out"]
    rows = [("Token LR", "tokenlr"), ("Structural GB", "structgb"), ("UniXcoder", "unixcoder")]
    conds = [("Unseen problems", BLUE, "o"), ("Renamed", "#5aa0d8", "^"), ("Reformatted", "#8a8a8a", "v"), ("Unseen generator (min.)", ORANGE, "s")]
    fig, ax = plt.subplots(figsize=(3.45, 1.7))
    for i, (n, k) in enumerate(rows):
        v = d[f"{k}__ext__raw"]
        vals = [v["codenet_test_unseen_problems"]["roc_auc"], v["codenet_auc_rename"]["transformed"],
                v["codenet_auc_reformat"]["transformed"],
                min(x["unseen_generator"] for kk, x in lg.items() if kk.startswith(f"{k}__raw__"))]
        ax.plot([min(vals), max(vals)], [i, i], color="#dddddd", lw=1.2, zorder=1)
        for (cn, c, m), val in zip(conds, vals):
            ax.plot(val, i, m, ms=4.4, color=c, mec="white", mew=0.5, zorder=3)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_xlim(0.75, 1.0)
    ax.set_xlabel("CodeNet ROC-AUC")
    ax.grid(axis="x", color="#f0f0f0", lw=0.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    h = [plt.Line2D([], [], marker=m, color=c, ls="none", ms=4.4, label=cn) for cn, c, m in conds]
    ax.legend(handles=h, ncol=2, loc="lower center", bbox_to_anchor=(0.45, 1.0), frameon=False, fontsize=6.2)
    fig.tight_layout()
    fig.savefig(FIG / "fig_shift.pdf", bbox_inches="tight")


def fig_trace():
    """Trace validation outcomes per scenario and claim, both adjudicators pooled (trace_validation.json)."""
    t = json.load(open(OUT / "trace_validation.json"))["coders"]
    import numpy as np
    scen = [f"S{i}" for i in range(1, 10)]
    claims = ["C1", "C2", "C3", "C4"]
    colors = {"correct": BLUE, "unresolved": "#d9d9d9", "wrong": ORANGE}
    fig, ax = plt.subplots(figsize=(3.45, 2.45))
    for i, s in enumerate(scen):
        for j, c in enumerate(claims):
            cnt = {"correct": 0, "unresolved": 0, "wrong": 0}
            for coder in ("ref1", "ref2"):
                for k, v in t[coder]["by_scenario_claim"].get(f"{s}|{c}", {}).items():
                    cnt["correct" if k == "correct" else "unresolved" if k == "unresolved" else "wrong"] += v
            x0 = j * 1.0
            tot = sum(cnt.values()) or 1
            left = 0
            for key in ("correct", "unresolved", "wrong"):
                w = cnt[key] / tot * 0.86
                if w:
                    ax.barh(i, w, left=x0 + left, color=colors[key], height=0.66, edgecolor="white", linewidth=0.6)
                left += w
    ax.set_yticks(range(9))
    ax.set_yticklabels(["S1 apply proposal", "S2 copy and paste", "S3 retype by hand", "S4 apply, rename", "S5 apply, undo, rewrite",
                        "S6 edit after AI", "S7 earlier answer", "S8 echoing answer", "S9 no AI"], fontsize=6.4)
    ax.invert_yaxis()
    ax.set_xticks([0.43, 1.43, 2.43, 3.43])
    ax.set_xticklabels(claims)
    ax.xaxis.tick_top()
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    h = [plt.Rectangle((0, 0), 1, 1, color=colors[k]) for k in ("correct", "unresolved", "wrong")]
    ax.legend(h, ["Correct", "Unresolved", "Wrong (support or mechanism)"], ncol=3, loc="upper center",
              bbox_to_anchor=(0.42, -0.02), frameon=False, fontsize=6.2, handlelength=1.0)
    fig.tight_layout()
    fig.savefig(FIG / "fig_trace.pdf", bbox_inches="tight")


def fig_reduced():
    """(a) the 36 scripted runs under the full record and the reduced packets, both coders pooled
    (trace_validation.json, 288 decisions each); (b) C3 mechanisms on the 86 reference-resolved cases of all 177
    (rq4_main.json mechanism_check *_all_cases; c3_abstain.json agreed decisions)."""
    tv = json.load(open(OUT / "trace_validation.json"))
    rm = json.load(open(OUT / "rq4_main.json"))["mechanism_check"]
    ab = json.load(open(OUT / "c3_abstain.json"))["agreed"]
    colors = {"correct": BLUE, "unresolved": "#d9d9d9", "wrong": ORANGE}

    def tri(coders):
        c = {"correct": 0, "unresolved": 0, "wrong": 0}
        for x in coders.values():
            for k, v in x["totals"].items():
                c[k if k in c else "wrong"] += v
        return c
    full = tri(tv["coders"])
    for k, v in tri(tv["extension"]["coders"]).items():
        full[k] += v
    rows_a = [("Full record", full), ("Full-U", tri(tv["reduced_FullU"]["coders"])),
              ("E1+E+T", tri(tv["reduced_E1pEpT"]["coders"])),
              ("E1+E+T, abstention rule", tri(tv["reduced_E1pEpT_c3abstain"]["coders"]))]
    fu, ee = rm["Full-U_all_cases"]["C3"], rm["E1+E+T_all_cases"]["C3"]
    rows_b = [("Full-U", dict(correct=fu["agree"], unresolved=fu["lost_to_unresolved"], wrong=fu["opposite"])),
              ("E1+E+T", dict(correct=ee["agree"], unresolved=ee["lost_to_unresolved"], wrong=ee["opposite"])),
              ("E1+E+T, abstention rule", dict(correct=ab.get("ref_resolved|agree", 0),
                                               unresolved=ab.get("ref_resolved|lost", 0),
                                               wrong=ab.get("ref_resolved|opposite", 0)))]
    fig, axs = plt.subplots(2, 1, figsize=(3.45, 2.05), gridspec_kw=dict(height_ratios=[4, 3], hspace=0.8))
    for ax, rows, title in ((axs[0], rows_a, "(a) Scripted runs: 288 decisions against the known actions"),
                            (axs[1], rows_b, "(b) Participants: C3 on the 86 mechanisms the reference resolved")):
        for i, (lab, c) in enumerate(rows):
            tot, x = sum(c.values()), 0
            for k in ("correct", "unresolved", "wrong"):
                v = c[k]
                if v:
                    ax.barh(i, v / tot, left=x, color=colors[k], height=0.62, edgecolor="white", linewidth=1.0)
                    if v / tot >= 0.05:
                        ax.text(x + v / tot / 2, i, str(v), ha="center", va="center", fontsize=6.2,
                                color="white" if k == "correct" else INK)
                    else:
                        ax.text(1.015, i, str(v), ha="left", va="center", fontsize=6.2, color=ORANGE)
                x += v / tot
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([r[0] for r in rows], fontsize=6.6)
        ax.invert_yaxis()
        ax.set_xlim(0, 1)
        ax.set_xticks([])
        ax.tick_params(length=0)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_title(title, fontsize=6.8, loc="left", x=-0.42, color=INK)
    h = [plt.Rectangle((0, 0), 1, 1, color=colors[k]) for k in ("correct", "unresolved", "wrong")]
    axs[1].legend(h, ["Correct / matches reference", "Unresolved", "Wrong (support or mechanism)"], ncol=3,
                  loc="upper center", bbox_to_anchor=(0.30, -0.02), frameon=False, fontsize=6.0, handlelength=1.0,
                  columnspacing=0.9)
    fig.savefig(FIG / "fig_reduced.pdf", bbox_inches="tight")


def tab_lopo():
    """in-domain flag rates with participants held out vs participants and problem groups held out
    (indomain_checks.json), written as a LaTeX table body to figs/tab_lopo.tex."""
    d = json.load(open(OUT / "indomain_checks.json"))
    m, near = d["lopo"]["methods"], d["near"]
    names = {"tokenlr": "Token LR", "structgb": r"Struct.\ GB", "unixcoder": "UniXcoder", "qwenlora": "Qwen + LoRA"}
    pct = lambda x: f"{100 * x:.0f}"
    L = []
    for k, n in names.items():
        a, b = m[k]["participant_out"], m[k]["participant_and_problem_out"]
        L.append(f"{n} & " + " & ".join(f"{pct(a[g]['flagged'])} / {pct(b[g]['flagged'])}"
                                         for g in ("tierB_near", "tierB_edited", "unknown")) + r" \\")
    g = m["tokenlr"]["participant_out"]
    head = (r"Method & Tier B, near-verb. & Tier B, edited & Unknown \\" + "\n"
            + r" & ($n=" + str(g["tierB_near"]["n"]) + r"$) & ($n=" + str(g["tierB_edited"]["n"])
            + r"$) & ($n=" + str(g["unknown"]["n"]) + r"$) \\")
    foot = (r"\multicolumn{4}{l}{\footnotesize Training block from another participant, token similarity $\geq$0.80: "
            + f"{100 * near['share_ge_0_80_any']:.1f}" + r"\% of near-verb.; $\geq$0.99: "
            + f"{100 * near['share_ge_0_99_any']:.1f}" + r"\%.} \\")
    (FIG / "tab_lopo.tex").write_text("\n".join([r"\toprule", head, r"\midrule", *L, r"\bottomrule"]) + "\n",  # foot (near-duplicate shares) is stated in the text
                                      encoding="utf-8")


def fig_echo():
    """schematic of the two echo rules on a constructed 16-token example (no data). The matched answer
    covers every submission position (near-verbatim); the producing request's user text covers positions 1-5 and an
    earlier request's user text (within 90 minutes) positions 6-9. Same-request rule: 11 of 16 new, at least half,
    tier B. Broad rule: 7 of 16 new, under half, so the tier-A test fails (the case stays tier B only).
    Colours are explained in the caption (no legend)."""
    n, half = 16, 8
    u0, u1 = set(range(0, 5)), set(range(5, 9))
    GREY, PALE = "#bdbdbd", "#c9dcef"
    fig, ax = plt.subplots(figsize=(3.45, 2.05))
    cw, ch, x0 = 0.112, 0.32, 1.30

    def row(y, fill, label, sub=None):
        for i in range(n):
            ax.add_patch(plt.Rectangle((x0 + i * cw, y), cw, ch, facecolor=fill(i), edgecolor="#777777", linewidth=0.4))
        ax.text(x0 - 0.08, y + ch / 2 + (0.07 if sub else 0), label, ha="right", va="center", fontsize=7.4, color=INK)
        if sub:
            ax.text(x0 - 0.08, y + ch / 2 - 0.13, sub, ha="right", va="center", fontsize=6.4, color="#555555")

    ax.text(0.0, 3.62, "(a) Records covering each submission token", fontsize=7.6, color=INK)
    row(3.05, lambda i: PALE, "matched answer")
    row(2.55, lambda i: GREY if i in u0 else "white", "user text", "producing request")
    row(2.05, lambda i: GREY if i in u1 else "white", "user text", "earlier request")
    ax.text(0.0, 1.55, "(b) Tokens counted as new", fontsize=7.6, color=INK)
    for y, disc, lab, sub, verdict in ((1.00, u0, "same-request", "rule", "11 new: tier B"),
                                       (0.40, u0 | u1, "broad", "rule", "7 new: under half")):
        k = len(disc)
        row(y, lambda i, k=k: GREY if i < k else BLUE, lab, sub)
        ax.text(x0 + n * cw + 0.06, y + ch / 2, verdict, ha="left", va="center", fontsize=7.2, color=INK)
    xl = x0 + (n - half) * cw
    ax.plot([xl, xl], [0.30, 1.42], color=INK, lw=0.7, ls=(0, (2, 1.5)))
    ax.text(xl, 0.14, "half of the submission", ha="center", va="center", fontsize=6.6, color="#555555")
    ax.set_xlim(0, 4.05)
    ax.set_ylim(0.0, 3.8)
    ax.axis("off")
    fig.savefig(FIG / "fig_echo.pdf", bbox_inches="tight")


if __name__ == "__main__":
    FIG.mkdir(parents=True, exist_ok=True)
    fig_transfer()
    fig_configs()
    fig_funnel()
    fig_operating()
    fig_shift()
    fig_trace()
    fig_reduced()
    tab_lopo()
    fig_echo()
    print("figures written to", FIG)
