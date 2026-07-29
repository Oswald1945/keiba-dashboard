# -*- coding: utf-8 -*-
"""
factor_interact_roi.py ― 複合(交互作用)モデルの実測ROIと有効な複合条件の抽出
==============================================================
交互作用ridgeで学習した馬ごとスコアで軸/フォーメーションを組み、
現行(線形)重みと 実測ROI（軸単複＋連系）を検証/全期間で比較。
併せて、標準化係数の大きい2乗項・ペア積（＝効いている複合条件）を列挙。
依存: numpy。DB不要。 出力: factor_interact_roi_report.md
"""
import os, math, itertools
import numpy as np
import factor_optimize as FO
import factor_roi_offline as FR

SD = os.path.dirname(os.path.abspath(__file__))
FACTORS = FR.FACTORS
OPT = FO.OPT
OPTIDX = [FACTORS.index(f) for f in OPT]
D0 = len(OPT)
LAM = 150.0
ORDER_BT = ["馬連", "ワイド", "馬単", "三連複", "三連単"]


def pair_names():
    return [f"{OPT[i]}×{OPT[j]}" for i, j in itertools.combinations(range(D0), 2)]


def feat_names():
    return list(OPT) + [f"{f}^2" for f in OPT] + pair_names()


def build_feats(Popt):
    sq = Popt ** 2
    pairs = [Popt[:, i] * Popt[:, j] for i, j in itertools.combinations(range(D0), 2)]
    return np.column_stack([Popt, sq, np.column_stack(pairs)])


def center_seg(A, seg):
    starts = np.concatenate([[0], np.cumsum(seg)[:-1]])
    sums = np.add.reduceat(A, starts, axis=0)
    means = sums / seg.reshape(-1, 1) if A.ndim == 2 else sums / seg
    return A - np.repeat(means, seg, axis=0)


def main():
    structs = FR.load_structs()
    payouts = FR.load_payouts()
    PP = {rid: FR.parse_po(po) for rid, po in payouts.items()}
    # 大きな配列に展開
    Popt_list, fin_list, nk_list, seg = [], [], [], []
    isval = []
    for st in structs:
        uma = st["uma"]
        fin = np.array([st["fin"][u] for u in uma], float)
        pop = np.array(st["pop"], float)
        Popt_list.append(st["P"][:, OPTIDX]); fin_list.append(fin); nk_list.append(pop)
        seg.append(len(uma)); isval.append(st["isval"])
    Popt = np.vstack(Popt_list); fin = np.concatenate(fin_list); nk = np.concatenate(nk_list)
    seg = np.array(seg); isval = np.array(isval)
    rowval = np.repeat(isval, seg); tr = ~rowval

    F = build_feats(Popt)
    Fc = center_seg(F, seg); yc = center_seg(-fin, seg); nkc = center_seg(nk, seg)
    sd = Fc[tr].std(0); sd[sd == 0] = 1.0
    Fs = Fc / sd
    X = np.column_stack([Fs, nkc]); p = X.shape[1]
    A = X[tr].T @ X[tr] + LAM * np.eye(p); A[-1, -1] -= LAM
    beta = np.linalg.solve(A, X[tr].T @ yc[tr])
    inter_score = Fs @ beta[:-1]

    # 有効な複合条件（2乗・ペア積のみ）を係数絶対値で上位抽出
    names = feat_names()
    coef = beta[:-1]
    combo_idx = list(range(D0, len(names)))   # 2乗＋ペア積
    ranked = sorted(combo_idx, key=lambda k: -abs(coef[k]))[:15]

    # ROI評価（現行線形 vs 複合）
    def roi_eval(score_all, subset):
        from collections import defaultdict
        starts = np.concatenate([[0], np.cumsum(seg)[:-1]])
        b = dict(n=0, win=0, plc=0, tanR=0.0, fukR=0.0)
        form = defaultdict(lambda: [0, 0.0])
        for k, stt in enumerate(structs):
            if subset == "val" and not isval[k]:
                continue
            s = score_all[starts[k]:starts[k]+seg[k]]
            rc = FR.slim_reconstruct(s, stt["uma"], stt["kt"], stt["pop"])
            if not rc:
                continue
            umA = rc["umA"]; fA = stt["fin"].get(umA)
            if fA is None:
                continue
            po = payouts.get(stt["rid"], {})
            fuk = {}
            for c, a in (po.get("fukusho") or []):
                try: fuk[int(c)] = a/100.0
                except Exception: pass
            b["n"] += 1
            if fA == 1:
                b["win"] += 1
                if stt["tan"].get(umA): b["tanR"] += stt["tan"][umA]
            if fA <= 3:
                b["plc"] += 1
                if fuk.get(umA): b["fukR"] += fuk[umA]
            pp = PP.get(stt["rid"])
            if pp is not None:
                for bt, v in FR.slim_eval(rc, pp).items():
                    form[bt][0] += v[0]; form[bt][1] += v[1]
        n = max(1, b["n"])
        return b, n, form

    # 現行線形スコア
    wv = FR.wvec(dict(FO.CUR_W))
    lin_score = np.concatenate([ (st["P"] @ wv) for st in structs ])

    lines = ["# 複合(交互作用)モデルの実測ROIと有効な複合条件\n"]
    lines.append(f"訓練{int(tr.sum())}頭 / 検証{int(rowval.sum())}頭 相当。ridge(λ={LAM:.0f})。\n")
    lines.append("## 実測ROI比較（軸流し各組1点）")
    lines.append("| モデル | 期間 | R | 軸勝率 | 軸複勝率 | 軸単ROI | 軸複ROI | 馬連 | ワイド | 三連複 | 三連単 |")
    lines.append("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for label, sc in (("現行線形", lin_score), ("複合(交互作用)", inter_score)):
        for sub in ("val", "all"):
            b, n, form = roi_eval(sc, sub)
            def fr_(bt):
                pts, ret = form[bt]
                return ("%.0f%%" % (100*ret/(pts*100))) if pts else "—"
            lines.append("| %s | %s | %d | %.1f%% | %.1f%% | %.0f%% | %.0f%% | %s | %s | %s | %s |" % (
                label, "検証" if sub == "val" else "全期間", b["n"],
                100*b["win"]/n, 100*b["plc"]/n, 100*b["tanR"]/n, 100*b["fukR"]/n,
                fr_("馬連"), fr_("ワイド"), fr_("三連複"), fr_("三連単")))

    lines.append("\n## 効いている複合条件（標準化係数の絶対値・上位15）")
    lines.append("| 複合項 | 係数(標準化) | 向き |")
    lines.append("|---|--:|---|")
    for k in ranked:
        c = coef[k]
        lines.append("| %s | %+.3f | %s |" % (names[k], c, "順(高いほど好走)" if c > 0 else "逆"))
    lines.append("\n※係数は標準化特徴に対する寄与。順=その複合が大きいほど好走、逆=好走を下げる。")
    lines.append("※ROIが現行を明確に上回らなければ、partial_rhoの上乗せは実利益化しないと判断。")
    rep = os.path.join(SD, "factor_interact_roi_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
