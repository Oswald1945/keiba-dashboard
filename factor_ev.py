# -*- coding: utf-8 -*-
"""
factor_ev.py ― 期待値(EV)ベースの買い判定検証：モデルは+EVのオーバーレイを見つけられるか
==============================================================
控除率を越える唯一の道は「モデルの真の勝率 > 市場(オッズ)の勝率」の過小評価馬を、
期待値プラスのときだけ買うこと。これを厳密に検証する:
  1) 現行スコア(総合スコア)を softmax(温度T) で勝率に較正（Tは訓練の勝者対数尤度で最適化）
  2) 較正チェック（予測勝率デシル vs 実勝率）
  3) 各馬 EV = p_model × 単勝オッズ − 1。EV>τ の馬に単勝を賭けた時の
     ホールドアウトROI・的中率・賭け数を τ 別に算出
100%超が訓練・検証で一貫すれば本物の+EVエッジ。無ければモデルは市場を写すだけ。
依存: numpy。DB不要。 出力: factor_ev_report.md
"""
import json, os, math
import numpy as np

SD = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(SD, "factor_rows.jsonl")
SPLIT = "20250601"
EXCLUDE_CLS = {"新馬", "未勝利"}   # 予想母数から除外


def load_meta_cls():
    m = {}
    p = os.path.join(SD, "racemeta_cache.jsonl")
    if os.path.exists(p):
        for l in open(p, encoding="utf-8"):
            try: r = json.loads(l)
            except Exception: continue
            m[r["rid"]] = r.get("cls", "?")
    return m


def load():
    cls = load_meta_cls()
    races = {}
    for l in open(ROWS, encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        races.setdefault(r["rid"], []).append(r)
    out = []
    for rid, rows in races.items():
        if cls.get(rid, "?") in EXCLUDE_CLS:
            continue
        s = np.array([x.get("総合スコア") for x in rows], float)
        fin = np.array([x.get("着順") for x in rows], float)
        od = np.array([x.get("単勝") if x.get("単勝") else np.nan for x in rows], float)
        if np.isnan(s).any() or np.isnan(fin).any() or np.isnan(od).any():
            continue
        if len(rows) < 5:
            continue
        out.append((rid[:8] >= SPLIT, s, fin, od))
    return out


def softmax_T(s, T):
    z = (s - s.max()) / T
    e = np.exp(z)
    return e / e.sum()


def fit_T(train):
    """勝者の対数尤度を最大化する温度T（1D探索）。"""
    best = None
    for T in np.linspace(2, 60, 59):
        ll = 0.0
        for _, s, fin, od in train:
            p = softmax_T(s, T)
            w = np.argmin(fin)         # 1着
            ll += math.log(max(1e-12, p[w]))
        if best is None or ll > best[1]:
            best = (T, ll)
    return best[0]


def calib_table(data, T):
    """予測勝率デシル vs 実勝率（較正確認）。"""
    ps, wins = [], []
    for _, s, fin, od in data:
        p = softmax_T(s, T); w = (fin == fin.min())
        ps.extend(p.tolist()); wins.extend(w.astype(float).tolist())
    ps = np.array(ps); wins = np.array(wins)
    order = np.argsort(ps)
    dec = np.array_split(order, 10)
    rows = []
    for d in dec:
        rows.append((ps[d].mean(), wins[d].mean(), len(d)))
    return rows


def ev_roi(data, T, tau):
    """EV>tau の馬に単勝1点。ROI, 的中率, 賭け数。"""
    nbet = win = 0; ret = 0.0
    for _, s, fin, od in data:
        p = softmax_T(s, T)
        ev = p * od - 1.0
        for i in range(len(s)):
            if ev[i] > tau:
                nbet += 1
                if fin[i] == 1:
                    win += 1; ret += od[i]
    if nbet == 0:
        return None
    return dict(nbet=nbet, hit=100*win/nbet, roi=100*ret/nbet)


def main():
    data = load()
    tr = [d for d in data if not d[0]]
    va = [d for d in data if d[0]]
    T = fit_T(tr)

    lines = ["# 期待値(EV)ベース買い判定の検証（新馬・未勝利を除外）\n"]
    lines.append(f"訓練{len(tr)}R / 検証{len(va)}R。較正温度T={T:.1f}（訓練の勝者尤度最大化）。\n")

    lines.append("## 較正チェック（予測勝率デシル vs 実勝率・検証期間）")
    lines.append("| デシル | 予測勝率 | 実勝率 | 頭数 |")
    lines.append("|---|--:|--:|--:|")
    for i, (pp, ww, n) in enumerate(calib_table(va, T), 1):
        lines.append("| %d | %.1f%% | %.1f%% | %d |" % (i, 100*pp, 100*ww, n))

    lines.append("\n## EVプラス単勝のROI（τ別・訓練｜検証）")
    lines.append("| EV閾値τ | 賭け数(訓/検) | 的中率(訓/検) | 単勝ROI(訓/検) |")
    lines.append("|---|--:|--:|--:|")
    for tau in (0.0, 0.05, 0.1, 0.2, 0.3, 0.5):
        rt = ev_roi(tr, T, tau); rv = ev_roi(va, T, tau)
        if not rt or not rv:
            continue
        star = " ★" if rt["roi"] > 100 and rv["roi"] > 100 else ""
        lines.append("| %.2f | %d/%d | %.0f%%/%.0f%% | %.0f%%｜%.0f%%%s |" % (
            tau, rt["nbet"], rv["nbet"], rt["hit"], rv["hit"], rt["roi"], rv["roi"], star))

    # 参照: 全単勝ベタ買い / 1番人気ベタ買い
    def flat(data, pick):
        nbet = win = 0; ret = 0.0
        for _, s, fin, od in data:
            idxs = range(len(s)) if pick == "all" else [int(np.argmax(-od + 0))] if False else None
            if pick == "fav":
                idxs = [int(np.argmin(od))]         # 最低オッズ=1番人気
            elif pick == "model":
                idxs = [int(np.argmax(s))]           # モデル1位
            else:
                idxs = range(len(s))
            for i in idxs:
                nbet += 1
                if fin[i] == 1: win += 1; ret += od[i]
        return dict(nbet=nbet, hit=100*win/nbet, roi=100*ret/nbet)
    lines.append("\n## 参照（検証期間・ベタ買い）")
    lines.append("| 戦略 | 賭け数 | 的中率 | 単勝ROI |")
    lines.append("|---|--:|--:|--:|")
    for name, pk in (("全馬単勝", "all"), ("1番人気", "fav"), ("モデル1位", "model")):
        r = flat(va, pk)
        lines.append("| %s | %d | %.0f%% | %.0f%% |" % (name, r["nbet"], r["hit"], r["roi"]))

    lines.append("\n**判定**: EVプラス単勝ROIが訓練・検証とも100%超(★)なら本物の+EVエッジ。"
                 "無ければモデルは市場を写すだけで、favorite買い・逆張りとも控除率を越えない＝新情報が必要。")
    rep = os.path.join(SD, "factor_ev_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
