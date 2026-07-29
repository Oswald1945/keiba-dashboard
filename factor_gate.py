# -*- coding: utf-8 -*-
"""
factor_gate.py ― 買い判定(購入推奨ゲート)の作り直し用データ分析
==============================================================
現行重みで各レースの軸を出し、
  (1) 現行ゲート(購入推奨/非推奨)の holdout 成績を診断（逆選別の定量化）
  (2) 軸人気 / 自信度(偏差値gap) / 頭数 / クラス 別に、
      軸複勝率・軸複勝ROI・ワイドROI を 訓練｜検証 で算出し、
      「相対的に良い買い場」を特定
→ 新ゲート設計の根拠にする。partial_rho不使用、実測のみ。
出力: factor_gate_report.md
"""
import json, os, math
import numpy as np
import factor_optimize as FO
import factor_roi_offline as FR

SD = os.path.dirname(os.path.abspath(__file__))
FACTORS = FR.FACTORS


def load_meta():
    m = {}
    for l in open(os.path.join(SD, "racemeta_cache.jsonl"), encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        m[r["rid"]] = r
    return m


def build_records():
    structs = FR.load_structs()
    payouts = FR.load_payouts()
    PP = {rid: FR.parse_po(po) for rid, po in payouts.items()}
    meta = load_meta()
    wv = FR.wvec(dict(FO.CUR_W))
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
        pos = st["uma"].index(umA)
        fanek = st["pop"][pos]
        po = payouts.get(st["rid"], {})
        fuk = {}
        for c, a in (po.get("fukusho") or []):
            try: fuk[int(c)] = a/100.0
            except Exception: pass
        pp = PP.get(st["rid"])
        bets = FR.slim_eval(rc, pp) if pp is not None else {}
        mm = meta.get(st["rid"], {})
        recs.append(dict(
            isval=st["isval"], verdict=rc["verdict"], fin=fA,
            fanek=int(fanek) if fanek else 99, gap=gap, n=len(st["uma"]),
            cls=mm.get("cls", "?"),
            fuk=fuk.get(umA), wide=bets.get("ワイド", (0, 0)), uren=bets.get("馬連", (0, 0)),
        ))
    return recs


def agg(recs):
    n = len(recs)
    if n == 0:
        return None
    plc = sum(1 for r in recs if r["fin"] and r["fin"] <= 3)
    fukR = sum((r["fuk"] or 0) for r in recs if r["fin"] and r["fin"] <= 3)
    wpts = sum(r["wide"][0] for r in recs); wret = sum(r["wide"][1] for r in recs)
    upts = sum(r["uren"][0] for r in recs); uret = sum(r["uren"][1] for r in recs)
    return dict(n=n, plc=100*plc/n, fukROI=100*fukR/n,
                wideROI=(100*wret/(wpts*100) if wpts else None),
                urenROI=(100*uret/(upts*100) if upts else None))


def row(label, recs):
    tr = [r for r in recs if not r["isval"]]
    va = [r for r in recs if r["isval"]]
    at = agg(tr); av = agg(va)
    if not at or not av:
        return None

    def c(key):
        t = at[key]; v = av[key]
        ts = ("%.0f%%" % t) if t is not None else "—"
        vs = ("%.0f%%" % v) if v is not None else "—"
        return f"{ts}｜{vs}"
    return "| %s | %d/%d | %s | %s | %s | %s |" % (
        label, at["n"], av["n"], c("plc"), c("fukROI"), c("wideROI"), c("urenROI"))


def section(lines, title, recs, keyfn, keys):
    lines.append(f"\n### {title}")
    lines.append("| 区分 | R(訓/検) | 軸複勝率 | 軸複ROI | ワイドROI | 馬連ROI |")
    lines.append("|---|--:|--|--|--|--|")
    for k in keys:
        sub = [r for r in recs if keyfn(r) == k]
        r = row(str(k), sub)
        if r:
            lines.append(r)


def main():
    recs = build_records()
    lines = ["# 買い判定 作り直し用 分析（現行重み・実測）\n"]
    lines.append("各区分 軸複勝率/軸複ROI/ワイドROI/馬連ROI を **訓練｜検証**。買い場の良し悪しを実測で。\n")

    lines.append("## (1) 現行ゲートの診断")
    lines.append("| 区分 | R(訓/検) | 軸複勝率 | 軸複ROI | ワイドROI | 馬連ROI |")
    lines.append("|---|--:|--|--|--|--|")
    for v in ("購入推奨", "購入非推奨"):
        r = row(v, [x for x in recs if x["verdict"] == v])
        if r: lines.append(r)
    r = row("全体", recs)
    if r: lines.append(r)

    section(lines, "(2a) 軸の推定人気別", recs,
            lambda r: ("1番人気" if r["fanek"] == 1 else "2番人気" if r["fanek"] == 2
                       else "3番人気" if r["fanek"] == 3 else "4-5番人気" if r["fanek"] in (4, 5)
                       else "6番人気以下"),
            ["1番人気", "2番人気", "3番人気", "4-5番人気", "6番人気以下"])
    section(lines, "(2b) 軸の自信度(偏差値gap)別", recs,
            lambda r: ("gap<3" if r["gap"] < 3 else "gap3-6" if r["gap"] < 6
                       else "gap6-10" if r["gap"] < 10 else "gap>=10"),
            ["gap<3", "gap3-6", "gap6-10", "gap>=10"])
    section(lines, "(2c) 頭数別", recs,
            lambda r: ("~9頭" if r["n"] <= 9 else "10-13頭" if r["n"] <= 13 else "14頭~"),
            ["~9頭", "10-13頭", "14頭~"])
    section(lines, "(2d) クラス別", recs, lambda r: r["cls"],
            ["新馬", "未勝利", "1勝", "2勝", "3勝", "OP", "G3", "G2", "G1"])

    lines.append("\n**狙い**: 現行『購入推奨』が全体/非推奨より低ければ逆選別。"
                 "(2)で軸複ROI・ワイドROIが訓練・検証とも相対的に高い区分＝新ゲートで推奨すべき買い場。")
    rep = os.path.join(SD, "factor_gate_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
