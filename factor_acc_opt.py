# -*- coding: utf-8 -*-
"""
factor_acc_opt.py ― 精度(軸複勝率)を目的にした配分最適化 & 市場情報ブレンドの効果
==============================================================
(1) 重みを「訓練の軸複勝率」最大化で座標上昇探索し、ホールドアウトで現行と比較。
    → 配分見直しでスコア単体の精度が上がるか。
(2) score' = α*model_z + (1-α)*market_z（人気由来）で軸を選び、α別に軸複勝率。
    → 市場情報を混ぜると精度がどこまで上がるか（50%→62%ギャップの正体）。
新馬・未勝利は除外。依存: numpy。DB不要。出力: factor_acc_opt_report.md
"""
import json, os
import numpy as np
import factor_optimize as FO

SD = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(SD, "factor_rows.jsonl")
SPLIT = "20250601"
EXCLUDE = {"新馬", "未勝利"}
OPT = FO.OPT
GRID = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0]


def load():
    cls = {}
    for l in open(os.path.join(SD, "racemeta_cache.jsonl"), encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        cls[r["rid"]] = r.get("cls", "?")
    races = {}
    for l in open(ROWS, encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        races.setdefault(r["rid"], []).append(r)
    P, plc2, win, pop, seg, isval = [], [], [], [], [], []
    for rid, rows in races.items():
        if cls.get(rid, "?") in EXCLUDE or len(rows) < 5:
            continue
        Pm = np.zeros((len(rows), len(OPT)))
        for i, x in enumerate(rows):
            for j, f in enumerate(OPT):
                v = x.get(f)
                if v is not None: Pm[i, j] = v
        fin = np.array([x.get("着順") for x in rows], float)
        pk = np.array([x.get("人気") if x.get("人気") else np.nan for x in rows], float)
        if np.isnan(fin).any() or np.isnan(pk).any():
            continue
        P.append(Pm); plc2.append(fin <= 3); win.append(fin == 1); pop.append(pk)
        seg.append(len(rows)); isval.append(rid[:8] >= SPLIT)
    return P, plc2, win, pop, np.array(isval)


def axis_plc(P, plc2, isval, w, want_val):
    n = hit = whit = 0
    for k in range(len(P)):
        if isval[k] != want_val:
            continue
        a = int(np.argmax(P[k] @ w)); n += 1
        if plc2[k][a]: hit += 1
    return 100*hit/n if n else 0.0


def opt_plc(P, plc2, isval, start):
    w = start.copy(); best = axis_plc(P, plc2, isval, w, False)
    for _ in range(3):
        imp = False
        for j in range(len(OPT)):
            base = w[j]; bv = base
            for g in GRID:
                w[j] = g; r = axis_plc(P, plc2, isval, w, False)
                if r > best + 1e-9: best = r; bv = g
            w[j] = bv
            if bv != base: imp = True
        if not imp: break
    return w


def blend_plc(P, plc2, pop, isval, alpha, want_val, w):
    """score' = alpha*model_z + (1-alpha)*market_z, 軸複勝率。"""
    n = hit = 0
    for k in range(len(P)):
        if isval[k] != want_val:
            continue
        s = P[k] @ w
        sz = (s - s.mean()) / (s.std() or 1)
        mk = -pop[k]                          # 人気番号小=有力→大きく
        mz = (mk - mk.mean()) / (mk.std() or 1)
        a = int(np.argmax(alpha*sz + (1-alpha)*mz)); n += 1
        if plc2[k][a]: hit += 1
    return 100*hit/n if n else 0.0


def main():
    P, plc2, win, pop, isval = load()
    ntr = int((~isval).sum()); nva = int(isval.sum())
    cur = np.array([FO.CUR_W.get(f, 0.0) for f in OPT])

    lines = ["# 精度(軸複勝率)目的の配分最適化 & 市場ブレンド（新馬未勝利除外）\n"]
    lines.append(f"訓練{ntr}R / 検証{nva}R。軸=スコア1位。\n")

    # (1) 軸複勝率最大化
    w_acc = opt_plc(P, plc2, isval, cur)
    lines.append("## (1) 配分を軸複勝率目的で最適化")
    lines.append("| 重み | 訓練 軸複勝率 | 検証 軸複勝率 |")
    lines.append("|---|--:|--:|")
    lines.append("| 現行 | %.1f%% | %.1f%% |" % (
        axis_plc(P, plc2, isval, cur, False), axis_plc(P, plc2, isval, cur, True)))
    lines.append("| 精度最適化 | %.1f%% | %.1f%% |" % (
        axis_plc(P, plc2, isval, w_acc, False), axis_plc(P, plc2, isval, w_acc, True)))
    lines.append("\n### 精度最適化で変わった重み（現行→最適）")
    lines.append("| 因子 | 現行 | 最適 |")
    lines.append("|---|--:|--:|")
    for j in sorted(range(len(OPT)), key=lambda j: -(w_acc[j]-cur[j])):
        if abs(w_acc[j]-cur[j]) > 1e-6:
            lines.append("| %s | %.1f | %.1f |" % (OPT[j], cur[j], w_acc[j]))

    # (2) 市場ブレンド
    lines.append("\n## (2) 市場(人気)ブレンドの効果（検証期間・軸複勝率）")
    lines.append("| α(モデル比率) | 軸複勝率 |")
    lines.append("|---|--:|")
    for al in (1.0, 0.75, 0.5, 0.25, 0.0):
        lines.append("| %.2f | %.1f%% |" % (al, blend_plc(P, plc2, pop, isval, al, True, cur)))
    lines.append("\n※α=1.0 純モデル / α=0.0 純市場(人気)。中間で最大化されれば、"
                 "モデルと市場の併用が最も精度が高い＝スコアに市場情報を足す価値がある。")
    rep = os.path.join(SD, "factor_acc_opt_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
