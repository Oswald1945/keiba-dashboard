# -*- coding: utf-8 -*-
"""
factor_optimize.py ― 重み(FACTOR_WEIGHTS)のオフライン最適化
==============================================================
総合スコア ≒ Σ w[f]*pts[f]（実測 r≈0.95 で線形）なので、FACTOR_WEIGHTS の
最適倍率は「レース内で人気を統制した -着順 の線形回帰係数」で閉形式に求まる。
  target : 好走 = -着順（レース内中心化＝レース固定効果除去）
  X      : 各因子pts（レース内中心化）＋ 人気（市場統制のため投入）
  → 因子の回帰係数 = 市場超過ぶんの最適な寄与倍率
過学習チェックのためレース日で【訓練/検証】に時系列分割し、
現行倍率 vs 最適倍率の partial_rho（人気統制後の好走予測力）を両期間で比較。

依存: numpy のみ。DB不要。 出力: factor_optimize_report.md
"""
import json, os, math
import numpy as np

SD = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(SD, "factor_rows.jsonl")
SPLIT_DATE = "20250601"   # 訓練=〜2025-05 / 検証=2025-06〜（5年データ用ホールドアウト）

FACTORS = [
    "最高出力pts", "クラスpts", "時計pts", "コース特徴pts", "トラックバイアスpts",
    "斤量pts", "距離pts", "コース適性pts", "臨戦pts", "人気補正pts", "騎手pts",
    "馬体重pts", "継続pts", "着差pts", "枠順pts", "昇級pts", "クラス適応pts",
    "上がりpts", "馬場適性pts", "SmartRC評価pts",
]
CUR_W = {
    "SmartRC評価pts": 1.0, "昇級pts": 2.0, "斤量pts": 2.0, "臨戦pts": 2.0, "枠順pts": 0.0,
    "最高出力pts": 1.0, "クラスpts": 1.0, "時計pts": 1.0, "コース特徴pts": 1.0,
    "距離pts": 0.0, "コース適性pts": 1.0, "騎手pts": 1.0, "馬体重pts": 0.0,
    "継続pts": 2.0, "着差pts": 2.0, "クラス適応pts": 2.0, "上がりpts": 1.0,
    "馬場適性pts": 2.0, "人気補正pts": 1.0, "トラックバイアスpts": 1.0,
}
# 値がほぼ一定/pred不能な因子は現行固定（回帰にも入れない）
FIXED = {"人気補正pts", "SmartRC評価pts", "馬体重pts", "枠順pts"}
OPT = [f for f in FACTORS if f not in FIXED]


def _fastrank(a):
    """同値は無視の高速順位（連続値スコア用、タイ稀）。"""
    return a.argsort(kind="mergesort").argsort().astype(float) + 1.0


def _pear(x, y):
    x = x - x.mean(); y = y - y.mean()
    d = math.sqrt(float((x * x).sum()) * float((y * y).sum()))
    return (float((x * y).sum()) / d) if d > 0 else 0.0


def load():
    races = {}
    for l in open(ROWS, encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        races.setdefault(r["rid"], []).append(r)
    data = {}
    for rid, rows in races.items():
        if len(rows) < 5:
            continue
        fin = np.array([x.get("着順") for x in rows], float)
        nk = np.array([x.get("人気") if x.get("人気") is not None else np.nan for x in rows], float)
        if np.isnan(fin).any() or np.isnan(nk).any():
            continue
        P = np.zeros((len(rows), len(FACTORS)))
        for i, x in enumerate(rows):
            for j, f in enumerate(FACTORS):
                v = x.get(f)
                if v is not None:
                    P[i, j] = v
        data[rid] = dict(P=P, fin=fin, nk=nk,
                         gr=_fastrank(-fin), mr=_fastrank(-nk))
        data[rid]["rmg"] = _pear(data[rid]["mr"], data[rid]["gr"])
    return data


def split(data):
    tr = {k: v for k, v in data.items() if k[:8] < SPLIT_DATE}
    va = {k: v for k, v in data.items() if k[:8] >= SPLIT_DATE}
    return tr, va


def fit_ols(train):
    """レース内中心化した -着順 を 因子pts＋人気 に回帰。因子係数を返す。"""
    optidx = [FACTORS.index(f) for f in OPT]
    Xs, ys = [], []
    for r in train.values():
        P = r["P"][:, optidx]
        y = -r["fin"]
        pop = r["nk"]
        Pc = P - P.mean(0)
        yc = y - y.mean()
        popc = pop - pop.mean()
        X = np.column_stack([Pc, popc])  # 因子 + 人気(統制)
        Xs.append(X); ys.append(yc)
    X = np.vstack(Xs); y = np.concatenate(ys)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    fac_coef = coef[:len(OPT)]   # 人気係数は捨てる（統制目的）
    return dict(zip(OPT, fac_coef))


def to_vec(wd):
    return np.array([wd.get(f, 0.0) for f in FACTORS], float)


def mean_partial(data, w):
    acc = []
    for r in data.values():
        s = r["P"] @ w
        if np.std(s) == 0:
            continue
        sr = _fastrank(s)
        rsg = _pear(sr, r["gr"]); rsm = _pear(sr, r["mr"]); rmg = r["rmg"]
        den = math.sqrt(max(1e-9, (1 - rsm**2) * (1 - rmg**2)))
        acc.append((rsg - rsm * rmg) / den)
    return float(np.mean(acc)) if acc else float("nan")


def main():
    data = load()
    train, val = split(data)
    print("train=%d val=%d races" % (len(train), len(val)))

    cur = dict(CUR_W)
    coef = fit_ols(train)

    # 係数を倍率へ整形: 負は0（逆張り採用は過学習リスク→ドロップ）、
    # OPT係数(正)の中央値が1.0になるよう規格化（現行と比較しやすく）。ランキングは正のスケール不変。
    pos = [c for c in coef.values() if c > 0]
    scale = (np.median(pos) if pos else 1.0)
    opt = dict(cur)  # FIXEDは現行維持
    for f in OPT:
        c = coef[f]
        opt[f] = round(max(0.0, c) / scale, 2) if scale > 0 else 0.0

    rows_metrics = [
        ("現行", cur), ("最適化(OLS係数)", opt),
    ]
    lines = ["# 重み最適化（人気統制OLS・時系列分割検証）\n"]
    lines.append(f"分割: 訓練<{SPLIT_DATE}≤検証  |  訓練{len(train)}R / 検証{len(val)}R\n")
    lines.append("| 重み設定 | 訓練 partial_rho | 検証 partial_rho |")
    lines.append("|---|--:|--:|")
    metr = {}
    for name, wd in rows_metrics:
        wv = to_vec(wd)
        tr_ = mean_partial(train, wv); va_ = mean_partial(val, wv)
        metr[name] = (tr_, va_)
        lines.append(f"| {name} | {tr_:+.4f} | {va_:+.4f} |")
    lift = metr["最適化(OLS係数)"][1] - metr["現行"][1]
    lines.append(f"\n検証期間の改善: **{lift:+.4f}**（{'実質改善の見込み' if lift>0 else '横ばい/悪化'}）\n")

    lines.append("## 因子別 倍率（現行 → 最適化）  ※OLS回帰係数(生)も併記")
    lines.append("| 因子 | 現行 | 最適化 | 変化 | 回帰係数(生) |")
    lines.append("|---|--:|--:|:--|--:|")
    order = sorted(FACTORS, key=lambda f: -(coef.get(f, -9) if f in OPT else -9))
    for f in order:
        c = cur.get(f, 0.0); o = opt.get(f, 0.0)
        raw = coef.get(f)
        if f in FIXED:
            mark = "（固定）"; rawtxt = "-"
        else:
            rawtxt = "%+.3f" % raw
            if o > c + 1e-6: mark = "↑ 増幅"
            elif o < c - 1e-6: mark = "↓ 減量"
            else: mark = "→ 据置"
        lines.append("| %s | %.1f | %.2f | %s | %s |" % (f, c, o, mark, rawtxt))
    lines.append("\n※固定＝pred/バックテストで値が一定or不可測（人気補正・SmartRC・馬体重・枠順）→現行維持。")
    lines.append("※回帰係数が負の因子は現状『市場超過で逆効果』。倍率0へドロップ（減量）。")
    lines.append("※倍率はOPT正係数の中央値=1.0で規格化（ランキングは正スケール不変）。")

    rep = os.path.join(SD, "factor_optimize_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
