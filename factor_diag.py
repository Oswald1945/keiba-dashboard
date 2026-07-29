# -*- coding: utf-8 -*-
"""
factor_diag.py ― 精度目的の因子診断（5年・1勝クラス以上）
==============================================================
的中精度(軸複勝率)の観点で各因子を診断:
  A) 単独精度: その因子だけで軸(=因子pts1位)を選んだ時の複勝率＋順位相関
  B) アブレーション: その因子を現行から除いた(w=0)時の総合 軸複勝率の変化
     Δ>0 = 除くと精度低下(=効いている) / Δ<0 = 除くと精度向上(=足を引っ張る)
  C) 変動レース率: その因子が馬間で差を持つ(=採点で効く)レースの割合
新馬・未勝利は除外。全期間/検証期間。DB不要。出力: factor_diag_report.md
"""
import json, os, math
import numpy as np
import factor_optimize as FO

SD = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(SD, "factor_rows.jsonl")
SPLIT = "20250601"
EXCLUDE = {"新馬", "未勝利"}
OPT = FO.OPT


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
    P, plc, fin, isval = [], [], [], []
    for rid, rows in races.items():
        if cls.get(rid, "?") in EXCLUDE or len(rows) < 5:
            continue
        Pm = np.zeros((len(rows), len(OPT)))
        for i, x in enumerate(rows):
            for j, f in enumerate(OPT):
                v = x.get(f)
                if v is not None: Pm[i, j] = v
        fn = np.array([x.get("着順") for x in rows], float)
        if np.isnan(fn).any():
            continue
        P.append(Pm); plc.append(fn <= 3); fin.append(fn); isval.append(rid[:8] >= SPLIT)
    return P, plc, fin, np.array(isval)


def axis_plc(P, plc, isval, w, val):
    n = hit = 0
    for k in range(len(P)):
        if isval[k] != val: continue
        a = int(np.argmax(P[k] @ w)); n += 1
        if plc[k][a]: hit += 1
    return 100*hit/n if n else 0.0


def solo(P, plc, fin, isval, j, val):
    """因子j単独で軸を選んだ複勝率 と 因子pts vs 着順 の平均順位相関、変動率。"""
    n = hit = 0; rhos = []; varc = 0; tot = 0
    for k in range(len(P)):
        if isval[k] != val: continue
        col = P[k][:, j]; tot += 1
        if np.std(col) > 0:
            varc += 1
            a = int(np.argmax(col)); n += 1
            if plc[k][a]: hit += 1
            sr = (-col).argsort().argsort() + 1
            r = np.corrcoef(sr, fin[k])[0, 1]
            if not math.isnan(r): rhos.append(r)
    return (100*hit/n if n else 0.0), (np.mean(rhos) if rhos else 0.0), (100*varc/tot if tot else 0.0)


def main():
    P, plc, fin, isval = load()
    ntr = int((~isval).sum()); nva = int(isval.sum())
    cur = np.array([FO.CUR_W.get(f, 0.0) for f in OPT])
    base_tr = axis_plc(P, plc, isval, cur, False)
    base_va = axis_plc(P, plc, isval, cur, True)

    rows = []
    for j, f in enumerate(OPT):
        s_plc, s_rho, s_var = solo(P, plc, fin, isval, j, True)
        w2 = cur.copy(); w2[j] = 0.0
        abl = axis_plc(P, plc, isval, w2, True)      # 除外時 検証複勝率
        delta = base_va - abl                          # Δ>0=効く
        rows.append((f, cur[j], s_plc, s_rho, s_var, delta))

    lines = ["# 精度目的の因子診断（5年・1勝クラス以上）\n"]
    lines.append(f"訓練{ntr}R / 検証{nva}R。総合(現行)の軸複勝率＝訓練{base_tr:.1f}%／検証{base_va:.1f}%。")
    lines.append("参考: 人気1位の複勝率 ≒ 63.7%（市場ベンチマーク）。\n")
    lines.append("| 因子 | 現行倍率 | 単独軸複勝率 | 単独順位相関 | 変動レース率 | アブレーションΔ(除外時の精度変化) |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for f, w, sp, sr, sv, d in sorted(rows, key=lambda x: -x[5]):
        mark = "効く" if d > 0.3 else ("足を引く" if d < -0.3 else "中立/死に重み")
        lines.append("| %s | %.1f | %.1f%% | %+.3f | %.0f%% | %+.2f pt（%s） |" % (
            f, w, sp, sr, sv, d, mark))
    lines.append("\n**読み方**")
    lines.append("- 単独軸複勝率が高い＝その因子だけでも当てる力がある（順位相関は負ほど良い＝高ptで上位）。")
    lines.append("- アブレーションΔ>0＝除くと総合精度が下がる＝効いている。Δ<0＝除くと上がる＝現状足を引っ張る（ロジック修正 or 減量/無効化の候補）。")
    lines.append("- 変動レース率が低い因子は、多くのレースで差を生まず採点に効いていない（発火条件の見直し候補）。")
    rep = os.path.join(SD, "factor_diag_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
