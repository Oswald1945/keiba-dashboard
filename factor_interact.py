# -*- coding: utf-8 -*-
"""
factor_interact.py ― 複合条件（交互作用・非線形）が精度を上げるか検証
==============================================================
既存因子ptsに「2乗項」と「全ペア積（交互作用）」を加えた特徴で ridge を学習し、
線形のみのモデルと比べて【検証期間の partial_rho（人気統制後の好走予測力）】が
上がるかを測る。上がれば複合条件は有効、変わらなければ線形で十分（＝複合は無益）。
すべてレース内中心化（レース固定効果除去）＋人気を統制。過学習は時系列分割＋正則化で管理。
依存: numpy のみ。DB不要。 出力: factor_interact_report.md
"""
import json, os, math, itertools
import numpy as np
import factor_optimize as FO

SD = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(SD, "factor_rows.jsonl")
SPLIT = FO.SPLIT_DATE
OPT = FO.OPT                      # 意味のある因子（定数・不可測を除く）
D0 = len(OPT)


def load():
    races = {}
    for l in open(ROWS, encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        races.setdefault(r["rid"], []).append(r)
    P_list, fin_list, nk_list, seg, isval = [], [], [], [], []
    for rid, rows in races.items():
        if len(rows) < 5:
            continue
        fin = np.array([x.get("着順") for x in rows], float)
        nk = np.array([x.get("人気") if x.get("人気") is not None else np.nan for x in rows], float)
        if np.isnan(fin).any() or np.isnan(nk).any():
            continue
        P = np.zeros((len(rows), D0))
        for i, x in enumerate(rows):
            for j, f in enumerate(OPT):
                v = x.get(f)
                if v is not None:
                    P[i, j] = v
        P_list.append(P); fin_list.append(fin); nk_list.append(nk)
        seg.append(len(rows)); isval.append(rid[:8] >= SPLIT)
    return P_list, fin_list, nk_list, np.array(seg), np.array(isval)


def build_features(P, mode):
    """mode: 'lin' | 'full'(lin+sq+pair)"""
    cols = [P]
    if mode == "full":
        cols.append(P ** 2)
        pairs = [P[:, i] * P[:, j] for i, j in itertools.combinations(range(D0), 2)]
        cols.append(np.column_stack(pairs))
    return np.column_stack(cols)


def center_per_race(A, seg):
    starts = np.concatenate([[0], np.cumsum(seg)[:-1]])
    sums = np.add.reduceat(A, starts, axis=0)
    means = sums / seg.reshape(-1, 1) if A.ndim == 2 else sums / seg
    return A - np.repeat(means, seg, axis=0)


def per_race_partial(scores, fin, nk, seg, isval, want_val):
    """レース内 partial_rho(score, -着順 | 人気) の平均（want_val=検証のみ/False=訓練のみ）。"""
    starts = np.concatenate([[0], np.cumsum(seg)[:-1]])
    acc = []

    def rank(a):
        return a.argsort(kind="mergesort").argsort().astype(float) + 1.0

    def pear(x, y):
        x = x - x.mean(); y = y - y.mean()
        d = math.sqrt(float((x*x).sum()) * float((y*y).sum()))
        return (float((x*y).sum())/d) if d > 0 else 0.0
    for k, st in enumerate(starts):
        if isval[k] != want_val:
            continue
        n = seg[k]; sl = slice(st, st+n)
        s = scores[sl]
        if np.std(s) == 0:
            continue
        sr = rank(s); gr = rank(-fin[sl]); mr = rank(-nk[sl])
        rsg = pear(sr, gr); rsm = pear(sr, mr); rmg = pear(mr, gr)
        den = math.sqrt(max(1e-9, (1-rsm**2)*(1-rmg**2)))
        acc.append((rsg - rsm*rmg)/den)
    return float(np.mean(acc)) if acc else float("nan")


def fit_eval(mode, lam, P_all, fin, nk, seg, isval):
    F = build_features(P_all, mode)
    Fc = center_per_race(F, seg)
    yc = center_per_race(-fin, seg)
    nkc = center_per_race(nk, seg)
    rowval = np.repeat(isval, seg)
    tr = ~rowval
    # 標準化（訓練統計）
    sd = Fc[tr].std(0); sd[sd == 0] = 1.0
    Fs = Fc / sd
    X = np.column_stack([Fs, nkc])          # 最終列=人気(統制・無罰)
    Xtr, ytr = X[tr], yc[tr]
    p = X.shape[1]
    A = Xtr.T @ Xtr + lam * np.eye(p)
    A[-1, -1] -= lam                         # 人気列は無罰
    beta = np.linalg.solve(A, Xtr.T @ ytr)
    scores = Fs @ beta[:-1]                   # 人気の寄与は除いた素点
    tr_rho = per_race_partial(scores, fin, nk, seg, isval, want_val=False)
    va_rho = per_race_partial(scores, fin, nk, seg, isval, want_val=True)
    return tr_rho, va_rho, F.shape[1]


def main():
    P_list, fin_list, nk_list, seg, isval = load()
    P_all = np.vstack(P_list); fin = np.concatenate(fin_list); nk = np.concatenate(nk_list)
    ntr = int((~isval).sum()); nva = int(isval.sum())

    lines = ["# 複合条件（交互作用・非線形）の検証\n"]
    lines.append(f"訓練{ntr}R / 検証{nva}R（分割<{SPLIT}）。特徴をレース内中心化＋人気統制し ridge。")
    lines.append("指標＝検証 partial_rho（人気統制後の好走予測力）。線形のみを上回れば複合が有効。\n")
    lines.append("| モデル | λ | 特徴数 | 訓練 partial_rho | 検証 partial_rho |")
    lines.append("|---|--:|--:|--:|--:|")

    # 線形のみ（基準）
    for lam in (10.0,):
        tr, va, nf = fit_eval("lin", lam, P_all, fin, nk, seg, isval)
        lines.append(f"| 線形のみ | {lam:.0f} | {nf} | {tr:+.4f} | {va:+.4f} |")
        base_va = va
    # 複合（線形+2乗+全ペア積）を複数λで
    best = None
    for lam in (5.0, 20.0, 50.0, 150.0, 500.0):
        tr, va, nf = fit_eval("full", lam, P_all, fin, nk, seg, isval)
        lines.append(f"| 複合(2乗+交互作用) | {lam:.0f} | {nf} | {tr:+.4f} | {va:+.4f} |")
        if best is None or va > best[1]:
            best = (lam, va)
    lift = best[1] - base_va
    lines.append(f"\n複合の最良（λ={best[0]:.0f}）検証 partial_rho = {best[1]:+.4f}  "
                 f"／ 線形のみ = {base_va:+.4f}  → 差 **{lift:+.4f}**")
    verdict = ("複合条件に上乗せあり（有望）" if lift >= 0.005
               else "複合条件の上乗せは無し〜誤差（線形で十分）")
    lines.append(f"\n**判定: {verdict}**")
    lines.append("\n※partial_rho差が+0.005以上で実質的な複合効果とみなす（それ未満は誤差）。")
    lines.append("※特徴は16因子＋その2乗＋全120ペア積。ridgeで過学習を抑制し検証で評価。")
    rep = os.path.join(SD, "factor_interact_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
