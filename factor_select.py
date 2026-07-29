# -*- coding: utf-8 -*-
"""
factor_select.py ― 選別分析：ROIが控除率/100%を超える買い局面を探す
==============================================================
factor_rows.jsonl ＋ payouts_cache.jsonl だけを使い、重み設定ごとに
レースを「判定 / 軸自信度(偏差値gap) / 軸推定人気 / 頭数」でスライスし、
各スライスの 軸単複ROI・連系フォーメーションROI を訓練/検証の両方で算出。
過学習排除のため、両期間で一貫して100%超（＝控除率突破）となる局面のみ有望とみなす。
DB不要。 出力: factor_select_report.md
"""
import json, os
import numpy as np
import pandas as pd
import bet_recon as BR
import factor_roi_offline as FR

SD = os.path.dirname(os.path.abspath(__file__))
ORDER_BT = ["馬連", "ワイド", "馬単", "三連複", "三連単"]


def per_race_records(wd, structs, payouts):
    wv = FR.wvec(wd)
    recs = []
    for st in structs:
        score = st["P"] @ wv
        if np.std(score) == 0:
            continue
        mean = float(np.mean(score)); sd = float(np.std(score)) or 1.0
        dev = 50 + 10 * (score - mean) / sd
        srt = np.argsort(-score)
        gap = float(dev[srt[0]] - dev[srt[1]]) if len(srt) >= 2 else 0.0
        rc = FR.slim_reconstruct(score, st["uma"], st["kt"], st["pop"])
        if not rc:
            continue
        umA = rc["umA"]; fA = st["fin"].get(umA)
        if fA is None:
            continue
        # 軸の推定人気
        pos = st["uma"].index(umA) if umA in st["uma"] else None
        fanek = st["pop"][pos] if pos is not None else None
        po = payouts.get(st["rid"], {})
        fuk = {}
        for c, a in (po.get("fukusho") or []):
            try: fuk[int(c)] = a / 100.0
            except Exception: pass
        bets = {}
        if po:
            df_rows = [{"入線順位": st["fin"][u], "馬番": u} for u in st["fin"] if st["fin"][u]]
            if len(df_rows) >= 3:
                try:
                    er = BR.eval_race(rc, pd.DataFrame(df_rows), po)
                    if er:
                        bets = {bt: (v[0], v[1]) for bt, v in er["bets"].items()}
                except Exception:
                    pass
        recs.append(dict(isval=st["isval"], verdict=rc["verdict"], gap=gap,
                         fanek=(int(fanek) if fanek else 99), n=len(st["uma"]),
                         fin=fA, tan=st["tan"].get(umA), fuk=fuk.get(umA), bets=bets))
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
    for bt in ORDER_BT:
        pts = sum(r["bets"].get(bt, (0, 0))[0] for r in recs)
        ret = sum(r["bets"].get(bt, (0, 0))[1] for r in recs)
        form[bt] = (100 * ret / (pts * 100)) if pts else None
    return dict(n=n, win=100*win/n, plc=100*plc/n,
                tanROI=100*tanR/n, fukROI=100*fukR/n, form=form)


def slices(recs):
    """(スライス名, フィルタ関数) を返す。"""
    def gap_t(lo, hi): return lambda r: lo <= r["gap"] < hi
    return [
        ("全体", lambda r: True),
        ("判定=購入推奨", lambda r: r["verdict"] == "購入推奨"),
        ("判定=非推奨", lambda r: r["verdict"] == "購入非推奨"),
        ("軸自信度gap<3", gap_t(-1, 3)),
        ("軸自信度gap3-6", gap_t(3, 6)),
        ("軸自信度gap6-10", gap_t(6, 10)),
        ("軸自信度gap>=10", lambda r: r["gap"] >= 10),
        ("軸1-2番人気", lambda r: r["fanek"] in (1, 2)),
        ("軸3-5番人気", lambda r: r["fanek"] in (3, 4, 5)),
        ("軸6番人気以下", lambda r: r["fanek"] >= 6),
        ("頭数<=12", lambda r: r["n"] <= 12),
        ("頭数>=13", lambda r: r["n"] >= 13),
    ]


def fmt(v):
    return ("%.0f%%" % v) if v is not None else "—"


def main():
    structs = FR.load_structs()
    payouts = FR.load_payouts()
    if not payouts:
        print("payouts_cache.jsonl が無い。先に dump_payouts.py を実行。"); return
    WS = FR.weight_sets()

    lines = ["# 選別分析：ROIが控除率/100%を超える局面探索\n"]
    lines.append("各スライスで 軸単勝/軸複勝/馬連/ワイド/三連複/三連単 のROIを "
                 "**訓練｜検証** の順で併記。**両方100%超**なら過学習でない有望局面（★）。\n")
    lines.append("※フラット買い（軸流し各組1点）。控除率突破＝ROI>100%。\n")

    for name in ("現行", "OLS生"):
        recs = per_race_records(WS[name], structs, payouts)
        tr = [r for r in recs if not r["isval"]]
        va = [r for r in recs if r["isval"]]
        lines.append(f"\n## 重み={name}")
        lines.append("| スライス | R(訓/検) | 軸単勝 | 軸複勝 | 馬連 | ワイド | 三連複 | 三連単 |")
        lines.append("|---|--:|--|--|--|--|--|--|")
        for sname, filt in slices(recs):
            at = agg([r for r in tr if filt(r)])
            av = agg([r for r in va if filt(r)])
            if not at or not av:
                continue

            def cell(key, sub=False):
                if sub:
                    t = at["form"][key]; v = av["form"][key]
                else:
                    t = at[key]; v = av[key]
                star = " ★" if (t and v and t > 100 and v > 100) else ""
                return f"{fmt(t)}｜{fmt(v)}{star}"
            row = "| %s | %d/%d | %s | %s | %s | %s | %s | %s |" % (
                sname, at["n"], av["n"],
                cell("tanROI"), cell("fukROI"),
                cell("馬連", True), cell("ワイド", True),
                cell("三連複", True), cell("三連単", True))
            lines.append(row)

    lines.append("\n**読み方**: ★＝訓練・検証とも100%超で一貫（過学習でない可能性）。"
                 "★が無ければ、その軸では控除率突破の局面は見つからず＝選別だけでは不十分、"
                 "新情報（血統・展開等）が必要という判断材料。")
    rep = os.path.join(SD, "factor_select_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
