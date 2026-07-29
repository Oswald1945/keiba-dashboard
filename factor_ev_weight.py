# -*- coding: utf-8 -*-
"""
factor_ev_weight.py ― スコア配分をEV(回収率)目的で最適化し、精度とのバランスを見る
==============================================================
これまでの重み最適化は「精度(順位相関/軸勝率)」目的。ここでは【軸単勝ROIを直接最大化】
する重みを訓練で探索し、ホールドアウトで軸勝率・軸複勝率・軸単勝ROIを現行/全体OLSと比較。
さらに 現行→ROI最適 の中間を補間し、精度とEVのトレードオフ曲線を示す。
新馬・未勝利は除外。依存: numpy。DB不要。出力: factor_ev_weight_report.md
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
    p = os.path.join(SD, "racemeta_cache.jsonl")
    for l in open(p, encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        cls[r["rid"]] = r.get("cls", "?")
    races = {}
    for l in open(ROWS, encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        races.setdefault(r["rid"], []).append(r)
    P, tan, winrow, seg, isval = [], [], [], [], []
    plc = []
    for rid, rows in races.items():
        if cls.get(rid, "?") in EXCLUDE or len(rows) < 5:
            continue
        Pm = np.zeros((len(rows), len(OPT)))
        for i, x in enumerate(rows):
            for j, f in enumerate(OPT):
                v = x.get(f)
                if v is not None: Pm[i, j] = v
        fin = np.array([x.get("着順") for x in rows], float)
        od = np.array([x.get("単勝") if x.get("単勝") else np.nan for x in rows], float)
        if np.isnan(fin).any() or np.isnan(od).any():
            continue
        P.append(Pm); tan.append(od); winrow.append(fin == 1); plc.append(fin <= 3)
        seg.append(len(rows)); isval.append(rid[:8] >= SPLIT)
    BigP = np.vstack(P)
    return P, tan, winrow, plc, np.array(seg), np.array(isval), BigP


def eval_w(P, tan, winrow, plc, isval, w, want_val):
    """軸(スコア1位)の 勝率/複勝率/単勝ROI。"""
    n = win = pl = 0; ret = 0.0
    for k in range(len(P)):
        if isval[k] != want_val:
            continue
        s = P[k] @ w
        a = int(np.argmax(s))
        n += 1
        if winrow[k][a]:
            win += 1; ret += tan[k][a]
        if plc[k][a]:
            pl += 1
    if n == 0:
        return None
    return dict(n=n, win=100*win/n, plc=100*pl/n, roi=100*ret/n)


def opt_roi(P, tan, winrow, plc, isval, start):
    """訓練の軸単勝ROIを最大化する座標上昇。"""
    w = start.copy()
    best = eval_w(P, tan, winrow, plc, isval, w, False)["roi"]
    for _ in range(3):
        improved = False
        for j in range(len(OPT)):
            base = w[j]; bestv = base
            for g in GRID:
                w[j] = g
                r = eval_w(P, tan, winrow, plc, isval, w, False)["roi"]
                if r > best + 1e-9:
                    best = r; bestv = g
            w[j] = bestv
            if bestv != base:
                improved = True
        if not improved:
            break
    return w


def main():
    P, tan, winrow, plc, seg, isval, BigP = load()
    ntr = int((~isval).sum()); nva = int(isval.sum())
    cur = np.array([FO.CUR_W.get(f, 0.0) for f in OPT])

    # 現行を起点に、訓練の軸単勝ROIを最大化する重みを探索
    w_roi = opt_roi(P, tan, winrow, plc, isval, cur)

    lines = ["# スコア配分のEV(単勝ROI)目的 最適化と 精度‐EVトレードオフ（新馬未勝利除外）\n"]
    lines.append(f"訓練{ntr}R / 検証{nva}R。軸=スコア1位。ROI最適=訓練の軸単勝ROI最大化。\n")
    lines.append("| 重み | 期間 | 軸勝率 | 軸複勝率 | 軸単勝ROI |")
    lines.append("|---|---|--:|--:|--:|")
    for name, w in (("現行", cur), ("ROI最適化", w_roi)):
        for wv, lab in ((False, "訓練"), (True, "検証")):
            m = eval_w(P, tan, winrow, plc, isval, w, wv)
            lines.append("| %s | %s | %.1f%% | %.1f%% | %.0f%% |" % (
                name, lab, m["win"], m["plc"], m["roi"]))

    lines.append("\n## 精度‐EV トレードオフ（現行→ROI最適 を補間・検証期間）")
    lines.append("| 混合λ | 軸勝率 | 軸複勝率 | 軸単勝ROI |")
    lines.append("|---|--:|--:|--:|")
    for lam in (0.0, 0.25, 0.5, 0.75, 1.0):
        w = (1 - lam) * cur + lam * w_roi
        m = eval_w(P, tan, winrow, plc, isval, w, True)
        lines.append("| %.2f | %.1f%% | %.1f%% | %.0f%% |" % (lam, m["win"], m["plc"], m["roi"]))

    lines.append("\n## ROI最適化で強調された重み（現行→最適）")
    lines.append("| 因子 | 現行 | ROI最適 |")
    lines.append("|---|--:|--:|")
    order = sorted(range(len(OPT)), key=lambda j: -(w_roi[j] - cur[j]))
    for j in order:
        if abs(w_roi[j] - cur[j]) > 1e-6:
            lines.append("| %s | %.1f | %.1f |" % (OPT[j], cur[j], w_roi[j]))

    lines.append("\n**判定**: ROI最適化しても検証の軸単勝ROIが100%未満・現行と大差なければ、"
                 "配分見直しでEVは改善しない（＝重みではなく情報の問題）。訓練だけ高く検証で落ちれば過学習。")
    rep = os.path.join(SD, "factor_ev_weight_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
