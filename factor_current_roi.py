# -*- coding: utf-8 -*-
"""
factor_current_roi.py ― 現行システムのベースライン回収率（5年・1勝クラス以上）
==============================================================
現行重み＋現行の買い判定(bet_recon.reconstruct)＋推奨フォーメーション(軸流し各組1点)を、
過去5年の1勝クラス以上（新馬・未勝利を除く）で購入したときの実測ROIを、
判定別（購入推奨/非推奨/全体）に、軸単複＋券種別＋全券種合算で算出。
全期間と検証期間(2025-06〜)の両方を表示。DB不要。
出力: factor_current_roi_report.md
"""
import json, os
from collections import defaultdict
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
    structs = FR.load_structs()
    payouts = FR.load_payouts()
    PP = {rid: FR.parse_po(po) for rid, po in payouts.items()}
    cls = load_cls()
    wv = FR.wvec(dict(FO.CUR_W))
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
        po = payouts.get(st["rid"], {})
        fuk = {}
        for c, a in (po.get("fukusho") or []):
            try: fuk[int(c)] = a/100.0
            except Exception: pass
        pp = PP.get(st["rid"])
        bets = FR.slim_eval(rc, pp) if pp is not None else {}
        recs.append(dict(isval=st["isval"], verdict=rc["verdict"], fin=fA,
                         tan=st["tan"].get(umA), fuk=fuk.get(umA), bets=bets))
    return recs


def agg(recs):
    n = len(recs)
    if n == 0:
        return None
    win = sum(1 for r in recs if r["fin"] == 1)
    plc = sum(1 for r in recs if r["fin"] and r["fin"] <= 3)
    tanR = sum((r["tan"] or 0) for r in recs if r["fin"] == 1)
    fukR = sum((r["fuk"] or 0) for r in recs if r["fin"] and r["fin"] <= 3)
    form = {}
    tot_pts = 0; tot_ret = 0.0
    for bt in BT:
        pts = sum(r["bets"].get(bt, (0, 0))[0] for r in recs)
        ret = sum(r["bets"].get(bt, (0, 0))[1] for r in recs)
        form[bt] = (pts, ret, (100*ret/(pts*100) if pts else None))
        tot_pts += pts; tot_ret += ret
    return dict(n=n, win=100*win/n, plc=100*plc/n, tanROI=100*tanR/n, fukROI=100*fukR/n,
                form=form, allform=(100*tot_ret/(tot_pts*100) if tot_pts else None))


def block(lines, title, recs):
    a = agg(recs)
    if not a:
        return
    lines.append(f"\n### {title}（{a['n']}レース）")
    lines.append("| 指標 | 軸勝率 | 軸複勝率 | 軸単勝ROI | 軸複勝ROI |")
    lines.append("|---|--:|--:|--:|--:|")
    lines.append("| 値 | %.1f%% | %.1f%% | **%.0f%%** | **%.0f%%** |" % (
        a["win"], a["plc"], a["tanROI"], a["fukROI"]))
    lines.append("\n| 券種 | 総点数 | 総払戻(円) | 回収率 |")
    lines.append("|---|--:|--:|--:|")
    for bt in BT:
        pts, ret, roi = a["form"][bt]
        lines.append("| %s | %d | %d | %s |" % (bt, pts, int(ret), ("%.0f%%" % roi) if roi is not None else "—"))
    lines.append("| **全券種合算** | — | — | **%s** |" % (("%.0f%%" % a["allform"]) if a["allform"] is not None else "—"))


def main():
    recs = collect()
    lines = ["# 現行システムのベースライン回収率（5年・1勝クラス以上）\n"]
    lines.append("現行重み＋現行の買い判定＋推奨フォーメーション（軸流し各組1点）を購入した場合の実測。")
    lines.append("軸単複は実オッズ・実複勝配当、連系はNL_HR_PAY確定配当。新馬・未勝利は除外。\n")

    for period, sel in (("全期間(5年)", lambda r: True),
                        ("検証期間(2025-06〜)", lambda r: r["isval"])):
        sub = [r for r in recs if sel(r)]
        lines.append(f"\n## {period}")
        block(lines, "全レース", sub)
        block(lines, "購入推奨のみ", [r for r in sub if r["verdict"] == "購入推奨"])
        block(lines, "購入非推奨のみ", [r for r in sub if r["verdict"] == "購入非推奨"])

    lines.append("\n※回収率100%=収支トントン。控除率（単勝約20%/連系約27.5%）を越えるには100%超が必要。")
    lines.append("※現行ゲートは検証で購入推奨＜非推奨の逆選別が判明済み（ブラッシュアップ対象）。")
    rep = os.path.join(SD, "factor_current_roi_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
