# -*- coding: utf-8 -*-
"""
factor_segment.py ― 条件別ROI（場×芝ダ×距離×馬場）で有望ポケットを探索
==============================================================
factor_rows + payouts_cache + racemeta_cache を使い、重み設定ごとに
レースを条件でスライスし、軸単複＋連系ROIを訓練/検証で算出。
両期間とも100%超のセルに★（過学習でない可能性）。小標本セルは除外。
DB不要。 出力: factor_segment_report.md
"""
import json, os
import numpy as np
import factor_roi_offline as FR

SD = os.path.dirname(os.path.abspath(__file__))
ORDER_BT = ["馬連", "ワイド", "馬単", "三連複", "三連単"]
MIN_TR, MIN_VA = 150, 50   # 小標本セル除外の下限（5年データ用に引き上げ）


def load_meta():
    m = {}
    p = os.path.join(SD, "racemeta_cache.jsonl")
    if not os.path.exists(p):
        return m
    for l in open(p, encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        m[r["rid"]] = r
    return m


def records(wd, structs, payouts, meta, PP):
    wv = FR.wvec(wd)
    out = []
    for st in structs:
        mm = meta.get(st["rid"])
        if not mm:
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
            try: fuk[int(c)] = a / 100.0
            except Exception: pass
        pp = PP.get(st["rid"])
        bets = FR.slim_eval(rc, pp) if pp is not None else {}
        out.append(dict(isval=st["isval"], fin=fA, tan=st["tan"].get(umA), fuk=fuk.get(umA),
                        bets=bets, surface=mm["surface"], band=mm["band"],
                        jyo=mm["jyo_name"], baba=mm["baba"]))
    return out


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
    return dict(n=n, tanROI=100*tanR/n, fukROI=100*fukR/n, form=form)


def fmt(v): return ("%.0f%%" % v) if v is not None else "—"


def seg_table(lines, title, recs, keyfn, keys=None):
    tr = [r for r in recs if not r["isval"]]
    va = [r for r in recs if r["isval"]]
    lines.append(f"\n### {title}")
    lines.append("| 条件 | R(訓/検) | 軸単勝 | 軸複勝 | 馬連 | ワイド | 三連複 | 三連単 |")
    lines.append("|---|--:|--|--|--|--|--|--|")
    allkeys = keys or sorted(set(keyfn(r) for r in recs))
    for k in allkeys:
        at = agg([r for r in tr if keyfn(r) == k])
        av = agg([r for r in va if keyfn(r) == k])
        if not at or not av or at["n"] < MIN_TR or av["n"] < MIN_VA:
            continue

        def cell(key, sub=False):
            t = at["form"][key] if sub else at[key]
            v = av["form"][key] if sub else av[key]
            star = " ★" if (t and v and t > 100 and v > 100) else ""
            return f"{fmt(t)}｜{fmt(v)}{star}"
        lines.append("| %s | %d/%d | %s | %s | %s | %s | %s | %s |" % (
            k, at["n"], av["n"], cell("tanROI"), cell("fukROI"),
            cell("馬連", True), cell("ワイド", True), cell("三連複", True), cell("三連単", True)))


def main():
    structs = FR.load_structs()
    payouts = FR.load_payouts()
    meta = load_meta()
    if not payouts or not meta:
        print("payouts_cache.jsonl か racemeta_cache.jsonl が無い。先にダンプを実行。"); return
    WS = FR.weight_sets()
    PP = {rid: FR.parse_po(po) for rid, po in payouts.items()}

    lines = ["# 条件別ROI（場×芝ダ×距離×馬場）― 有望ポケット探索\n"]
    lines.append("各セル 軸/連系ROIを **訓練｜検証**。両方100%超に★。"
                 f"小標本は除外（訓練≥{MIN_TR}/検証≥{MIN_VA}）。フラット買い（軸流し各組1点）。\n")
    for name in ("現行", "OLS生"):
        recs = records(WS[name], structs, payouts, meta, PP)
        lines.append(f"\n## 重み={name}")
        seg_table(lines, "芝ダ別", recs, lambda r: r["surface"], keys=["芝", "ダ"])
        seg_table(lines, "芝ダ×距離帯", recs, lambda r: r["surface"] + r["band"],
                  keys=[s + b for s in ("芝", "ダ") for b in ("短", "マ", "中", "長")])
        seg_table(lines, "馬場状態別", recs, lambda r: r["baba"],
                  keys=["良", "稍重", "重", "不良"])
        seg_table(lines, "競馬場別", recs, lambda r: r["jyo"])
    lines.append("\n**注意**: スコアは馬場=良固定で採点済み。馬場スライスは『実際の馬場で層別した既存スコアの成績』。")
    lines.append("★のあるポケットのみ、第2段（shrinkage付き条件別重み）に進む価値がある。")
    rep = os.path.join(SD, "factor_segment_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
