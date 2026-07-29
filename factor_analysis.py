# -*- coding: utf-8 -*-
"""
factor_analysis.py ― 因子の予測力を大規模に測定（factor_rows.jsonl から）
==============================================================
factor_backtest.py が貯めた各馬の因子pts+実着順+人気から、因子ごとに:
  raw_rho     : レース内 Spearman(因子pts, 好走=-着順) の平均（市場込みの生予測力）
  partial_rho : 人気(市場)を統制した偏Spearman の平均（市場超過情報＝本当の上乗せ価値）
  rho_pop     : 因子pts と 人気 の相関（市場をどれだけなぞっているか）
を算出。現行の総合スコア寄与倍率(FACTOR_WEIGHTS)と並べ、増幅/据置/要改善を提案。

依存は numpy のみ（scipy不要）。Spearman = 順位に対する Pearson。
出力: factor_analysis_report.md
"""
import json, os, math
import numpy as np

SD = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(SD, "factor_rows.jsonl")

FACTORS = [
    "最高出力pts", "クラスpts", "時計pts", "コース特徴pts", "トラックバイアスpts",
    "斤量pts", "距離pts", "コース適性pts", "臨戦pts", "人気補正pts", "騎手pts",
    "馬体重pts", "継続pts", "着差pts", "枠順pts", "昇級pts", "クラス適応pts",
    "上がりpts", "馬場適性pts", "SmartRC評価pts", "総合スコア",
]

# 現行倍率フォールバック（score_horse_v3 が import 不能でも表示できるように）
FALLBACK_W = {
    "SmartRC評価pts": 1.0, "昇級pts": 2.0, "斤量pts": 2.0, "臨戦pts": 2.0, "枠順pts": 0.0,
    "最高出力pts": 1.0, "クラスpts": 1.0, "時計pts": 1.0, "コース特徴pts": 1.0,
    "距離pts": 0.0, "コース適性pts": 1.0, "騎手pts": 1.0, "馬体重pts": 0.0,
    "継続pts": 2.0, "着差pts": 2.0, "クラス適応pts": 2.0, "上がりpts": 1.0,
    "馬場適性pts": 2.0, "人気補正pts": 1.0, "トラックバイアスpts": 1.0,
}


def current_weights():
    try:
        import score_horse_v3 as S
        w = dict(S.FACTOR_WEIGHTS)
        if w:
            return w
    except Exception:
        pass
    return dict(FALLBACK_W)


def _rank(a):
    """平均順位（同値は平均）。"""
    a = np.asarray(a, dtype=float)
    n = len(a)
    sorter = np.argsort(a, kind="mergesort")
    tmp = np.arange(1, n + 1, dtype=float)
    ranks = np.empty(n, dtype=float)
    ranks[sorter] = tmp
    sa = a[sorter]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sa[j + 1] == sa[i]:
            j += 1
        if j > i:
            ranks[sorter[i:j + 1]] = (tmp[i] + tmp[j]) / 2.0
        i = j + 1
    return ranks


def _pearson(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    x = x - x.mean(); y = y - y.mean()
    d = math.sqrt(float((x * x).sum()) * float((y * y).sum()))
    return float((x * y).sum() / d) if d > 0 else np.nan


def _spearman(x, y):
    if len(x) < 4:
        return np.nan
    return _pearson(_rank(x), _rank(y))


def partial_spearman(x, y, z):
    """z を統制した x,y の偏Spearman。"""
    rxy = _spearman(x, y); rxz = _spearman(x, z); ryz = _spearman(y, z)
    for r in (rxy, rxz, ryz):
        if r is None or (isinstance(r, float) and math.isnan(r)):
            return np.nan
    den = math.sqrt((1 - rxz**2) * (1 - ryz**2))
    if den == 0:
        return np.nan
    return (rxy - rxz * ryz) / den


def main():
    if not os.path.exists(ROWS):
        print("factor_rows.jsonl が無い。先に factor_backtest.py を実行。"); return
    races = {}
    for l in open(ROWS, encoding="utf-8"):
        try:
            r = json.loads(l)
        except Exception:
            continue
        races.setdefault(r["rid"], []).append(r)

    raw = {f: [] for f in FACTORS}
    part = {f: [] for f in FACTORS}
    rpop = {f: [] for f in FACTORS}
    pop_raw = []
    n_ok = n_horse = 0

    for rid, rows in races.items():
        if len(rows) < 5:
            continue
        fin = np.array([r.get("着順") for r in rows], dtype="float")
        nk = np.array([r.get("人気") if r.get("人気") is not None else np.nan for r in rows], dtype="float")
        if np.isnan(fin).any():
            continue
        good = -fin
        mkt = -nk
        mkt_ok = np.isfinite(mkt)
        has_mkt = mkt_ok.sum() >= 4 and np.nanstd(mkt) > 0
        n_ok += 1; n_horse += len(rows)
        if has_mkt:
            rr = _spearman(mkt[mkt_ok], good[mkt_ok])
            if not np.isnan(rr):
                pop_raw.append(rr)
        for f in FACTORS:
            v = np.array([r.get(f) if r.get(f) is not None else np.nan for r in rows], dtype="float")
            fin_ok = np.isfinite(v)
            if fin_ok.sum() < 4 or np.nanstd(v[fin_ok]) == 0:
                continue
            rr = _spearman(v[fin_ok], good[fin_ok])
            if not np.isnan(rr):
                raw[f].append(rr)
            if has_mkt:
                both = fin_ok & mkt_ok
                if both.sum() >= 4 and np.nanstd(v[both]) > 0 and np.nanstd(mkt[both]) > 0:
                    rp = _spearman(v[both], mkt[both])
                    if not np.isnan(rp):
                        rpop[f].append(rp)
                    pr = partial_spearman(v[both], good[both], mkt[both])
                    if not np.isnan(pr):
                        part[f].append(pr)

    def mean(a):
        return float(np.mean(a)) if a else float("nan")

    W = current_weights()
    rows_out = []
    for f in FACTORS:
        rows_out.append((f, mean(raw[f]), mean(part[f]), mean(rpop[f]), len(part[f]), W.get(f)))
    facs = [r for r in rows_out if r[0] != "総合スコア"]
    facs.sort(key=lambda x: -(x[2] if not math.isnan(x[2]) else -9))
    total = [r for r in rows_out if r[0] == "総合スコア"]

    def suggest(part_rho, cur_w):
        if math.isnan(part_rho):
            return "測定不能"
        if part_rho >= 0.04:
            return "増幅候補（市場超過あり）"
        if part_rho >= 0.015:
            return "有効・据置〜微増"
        if part_rho > -0.015:
            return "市場相似/中立（据置 or 改善）"
        return "逆張り気味・要改善/減量"

    lines = [f"# 因子の予測力（{n_ok}レース / {n_horse}頭・JV採点）\n"]
    lines.append("| 因子 | 現行倍率 | raw_rho(生) | **partial_rho(人気統制後)** | rho_pop(市場相似) | n | 判定 |")
    lines.append("|---|--:|--:|--:|--:|--:|---|")
    for (f, r_raw, r_part, r_pop, k, w) in facs:
        wtxt = "-" if w is None else ("%.1f" % w)
        lines.append("| %s | %s | %+.3f | **%+.3f** | %+.3f | %d | %s |"
                     % (f, wtxt, r_raw, r_part, r_pop, k, suggest(r_part, w)))
    for (f, r_raw, r_part, r_pop, k, w) in total:
        lines.append("| **%s** | - | %+.3f | %+.3f | %+.3f | %d | （モデル全体） |"
                     % (f, r_raw, r_part, r_pop, k))
    lines.append(f"\n【参考】人気(市場)単体の生予測力 raw_rho = {mean(pop_raw):+.3f}（n={len(pop_raw)}）")
    lines.append("\n**読み方**")
    lines.append("- partial_rho が正で大きい＝市場が知らない好走情報を持つ因子。**①増幅候補**。")
    lines.append("- partial_rho が0付近＝市場をなぞるだけ。**②ロジック改善で上乗せ余地**。")
    lines.append("- partial_rho が負＝現状は逆効果。ロジック見直し or 減量候補。")
    lines.append("- rho_pop が高い＝人気と重複。単体で効いて見えても上乗せは小さい。")

    rep = os.path.join(SD, "factor_analysis_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
