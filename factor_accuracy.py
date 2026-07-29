# -*- coding: utf-8 -*-
"""
factor_accuracy.py ― 現行ロジックの「的中精度」ベースライン（5年・1勝クラス以上）
==============================================================
評価軸をROIではなく精度に。現行重みで:
  軸(スコア1位)の 勝率/連対率/複勝率、
  モデル上位3頭が実3着内を何頭カバーするか、
  推奨フォーメーション(軸流し)の的中率（当たり組を含む率）、
  順位予想と実着順の順位相関、
  参考: 1番人気の複勝率 / モデル1位≠1番人気時の勝敗
を 全体/購入推奨/非推奨 × 全期間/検証期間 で算出。DB不要。
出力: factor_accuracy_report.md
"""
import json, os, math
import numpy as np
import factor_optimize as FO
import factor_roi_offline as FR

SD = os.path.dirname(os.path.abspath(__file__))
EXCLUDE = {"新馬", "未勝利"}
BT = ["馬連", "ワイド", "馬単", "三連複", "三連単"]


def load_cls():
    m = {}
    for l in open(os.path.join(SD, "racemeta_cache.jsonl"), encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        m[r["rid"]] = r.get("cls", "?")
    return m


def collect():
    structs = FR.load_structs(); payouts = FR.load_payouts()
    PP = {rid: FR.parse_po(po) for rid, po in payouts.items()}
    cls = load_cls(); wv = FR.wvec(dict(FO.CUR_W))
    recs = []
    for st in structs:
        if cls.get(st["rid"], "?") in EXCLUDE:
            continue
        score = st["P"] @ wv
        if np.std(score) == 0:
            continue
        rc = FR.slim_reconstruct(score, st["uma"], st["kt"], st["pop"])
        if not rc:
            continue
        umA = rc["umA"]; fA = st["fin"].get(umA)
        if fA is None:
            continue
        # モデル上位3頭（スコア順）と実3着内のカバー
        order = np.argsort(-score)
        model_top3 = set(int(st["uma"][i]) for i in order[:3])
        actual_top3 = set(u for u, f in st["fin"].items() if f and f <= 3)
        cover = len(model_top3 & actual_top3)
        # 順位相関（スコア順位 vs 着順）
        fin_arr = np.array([st["fin"][u] for u in st["uma"]], float)
        sc_rank = (-score).argsort().argsort() + 1
        fn_rank = fin_arr
        rho = np.corrcoef(sc_rank, fn_rank)[0, 1]
        # 1番人気（最小人気番号）の複勝
        pops = np.array(st["pop"], float)
        fav_i = int(np.nanargmin(pops)) if np.isfinite(pops).any() else None
        fav_u = int(st["uma"][fav_i]) if fav_i is not None else None
        fav_fin = st["fin"].get(fav_u)
        fav_is_axis = (fav_u == umA)
        pp = PP.get(st["rid"])
        bets = FR.slim_eval(rc, pp) if pp is not None else {}
        recs.append(dict(isval=st["isval"], verdict=rc["verdict"], fin=fA,
                         cover=cover, rho=(rho if not math.isnan(rho) else None),
                         fav_fin=fav_fin, fav_is_axis=fav_is_axis,
                         bets=bets))
    return recs


def acc(recs):
    n = len(recs)
    if n == 0:
        return None
    win = sum(1 for r in recs if r["fin"] == 1)
    ren = sum(1 for r in recs if r["fin"] and r["fin"] <= 2)
    plc = sum(1 for r in recs if r["fin"] and r["fin"] <= 3)
    cover = np.mean([r["cover"] for r in recs])
    rho = np.mean([r["rho"] for r in recs if r["rho"] is not None])
    favplc = np.mean([1 if (r["fav_fin"] and r["fav_fin"] <= 3) else 0 for r in recs])
    form = {}
    for bt in BT:
        hits = sum(1 for r in recs if r["bets"].get(bt, (0, 0))[1] > 0)
        pts = [r["bets"].get(bt, (0, 0))[0] for r in recs if r["bets"].get(bt, (0, 0))[0] > 0]
        form[bt] = (100*hits/n, np.mean(pts) if pts else 0)
    return dict(n=n, win=100*win/n, ren=100*ren/n, plc=100*plc/n,
                cover=cover, rho=rho, favplc=100*favplc, form=form)


def block(lines, title, recs):
    a = acc(recs)
    if not a:
        return
    lines.append(f"\n### {title}（{a['n']}レース）")
    lines.append("| 軸勝率 | 軸連対率 | 軸複勝率 | 上位3の実3着内カバー(平均/3頭) | 順位相関 | 参考:1番人気複勝率 |")
    lines.append("|--:|--:|--:|--:|--:|--:|")
    lines.append("| %.1f%% | %.1f%% | **%.1f%%** | %.2f | %.3f | %.1f%% |" % (
        a["win"], a["ren"], a["plc"], a["cover"], a["rho"], a["favplc"]))
    lines.append("\n| 推奨フォーメーション的中率 | 馬連 | ワイド | 馬単 | 三連複 | 三連単 |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    lines.append("| 当たり組を含む率 | %.0f%% | %.0f%% | %.0f%% | %.0f%% | %.0f%% |" % tuple(
        a["form"][bt][0] for bt in BT))
    lines.append("| （平均点数） | %.1f | %.1f | %.1f | %.1f | %.1f |" % tuple(
        a["form"][bt][1] for bt in BT))


def main():
    recs = collect()
    lines = ["# 現行ロジックの的中精度ベースライン（5年・1勝クラス以上）\n"]
    lines.append("評価軸＝精度（ROIではない）。現行重み。新馬・未勝利は除外。")
    lines.append("軸=スコア1位。順位相関=スコア順位と実着順のPearson（負ほど良い=高スコアが上位）。\n")
    # モデル vs 1番人気（不一致時の勝敗）
    diff = [r for r in recs if not r["fav_is_axis"]]
    if diff:
        mw = np.mean([1 if r["fin"] == 1 else 0 for r in diff])
        fw = np.mean([1 if r["fav_fin"] == 1 else 0 for r in diff])
        lines.append(f"**モデル軸≠1番人気のレース（{len(diff)}R）の単勝的中**："
                     f"モデル軸 {100*mw:.1f}% ／ 1番人気 {100*fw:.1f}%\n")
    for period, sel in (("全期間(5年)", lambda r: True),
                        ("検証期間(2025-06〜)", lambda r: r["isval"])):
        sub = [r for r in recs if sel(r)]
        lines.append(f"\n## {period}")
        block(lines, "全レース", sub)
        block(lines, "購入推奨のみ", [r for r in sub if r["verdict"] == "購入推奨"])
        block(lines, "購入非推奨のみ", [r for r in sub if r["verdict"] == "購入非推奨"])
    lines.append("\n※軸複勝率＝スコア1位が3着内に入る率。順位相関の目安：0=無相関、負で大きいほど並びが正確。")
    lines.append("※フォーメーション的中率＝推奨買い目に当たり組が含まれた率（点数=1レースの購入点数）。")
    rep = os.path.join(SD, "factor_accuracy_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
