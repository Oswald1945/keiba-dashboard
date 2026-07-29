# -*- coding: utf-8 -*-
"""
factor_segweight.py ― セグメント別スコア配分（条件別重み）の検証
==============================================================
コース/距離/クラス/芝ダ/馬場/開催週などで重みを細分化し、
【全体重みを holdout（検証期間）で上回るか】を軸精度＋実測ROIで判定。
過学習防止：条件別OLSは全体OLSへ shrinkage（部分プーリング, α=n/(n+K)）。
評価は軸勝率・軸複勝率・軸単複ROI・連系ROI（partial_rhoは馬券指標として不適のため不使用）。
依存: numpy。DB不要。 出力: factor_segweight_report.md
"""
import json, os, math
import numpy as np
import factor_optimize as FO
import factor_roi_offline as FR

SD = os.path.dirname(os.path.abspath(__file__))
FACTORS = FR.FACTORS
OPT = FO.OPT
OPTIDX = [FACTORS.index(f) for f in OPT]
KTI = OPT.index("コース特徴pts")
K_SHRINK = 400.0     # 部分プーリング定数（レース数）
MIN_SEG_TR = 200     # これ未満の条件は全体重みで代替
ORDER_BT = ["馬連", "ワイド", "馬単", "三連複", "三連単"]


def load_meta():
    m = {}
    p = os.path.join(SD, "racemeta_cache.jsonl")
    for l in open(p, encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        m[r["rid"]] = r
    return m


def nichiji_band(n):
    if n <= 2: return "序盤"
    if n <= 6: return "中盤"
    return "終盤"


def fit_ols(idxs, Plist, finlist, nklist):
    """レース内中心化した -着順 を OPT因子pts+人気 に回帰し、OPT係数(生)を返す。"""
    Xs, ys = [], []
    for k in idxs:
        P = Plist[k]; y = -finlist[k]; pop = nklist[k]
        Xs.append(np.column_stack([P - P.mean(0), pop - pop.mean()]))
        ys.append(y - y.mean())
    if not Xs:
        return None
    X = np.vstack(Xs); y = np.concatenate(ys)
    if len(y) < len(OPT) + 2:
        return None
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return coef[:len(OPT)]


def evaluate(idxs, wmap_or_vec, structs, Plist, payouts, PP, per_seg_key=None):
    """idxs のレースを、重み（固定ベクトル or segment->ベクトルのdict）で評価。"""
    from collections import defaultdict
    b = dict(n=0, win=0, plc=0, tanR=0.0, fukR=0.0)
    form = defaultdict(lambda: [0, 0.0])
    for k in idxs:
        st = structs[k]
        if isinstance(wmap_or_vec, dict):
            w = wmap_or_vec.get(per_seg_key[k])
            if w is None:
                continue
        else:
            w = wmap_or_vec
        s = Plist[k] @ w
        rc = FR.slim_reconstruct(s, st["uma"], Plist[k][:, KTI], st["pop"])
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
        b["n"] += 1
        if fA == 1:
            b["win"] += 1
            if st["tan"].get(umA): b["tanR"] += st["tan"][umA]
        if fA <= 3:
            b["plc"] += 1
            if fuk.get(umA): b["fukR"] += fuk[umA]
        pp = PP.get(st["rid"])
        if pp is not None:
            for bt, v in FR.slim_eval(rc, pp).items():
                form[bt][0] += v[0]; form[bt][1] += v[1]
    return b, form


def line_for(label, b, form):
    n = max(1, b["n"])
    def fr_(bt):
        pts, ret = form[bt]
        return ("%.0f%%" % (100*ret/(pts*100))) if pts else "—"
    return "| %s | %d | %.1f%% | %.1f%% | %.0f%% | %.0f%% | %s | %s | %s | %s |" % (
        label, b["n"], 100*b["win"]/n, 100*b["plc"]/n, 100*b["tanR"]/n, 100*b["fukR"]/n,
        fr_("馬連"), fr_("ワイド"), fr_("三連複"), fr_("三連単"))


def main():
    structs = FR.load_structs()
    payouts = FR.load_payouts()
    PP = {rid: FR.parse_po(po) for rid, po in payouts.items()}
    meta = load_meta()
    # 事前計算
    Plist, finlist, nklist = [], [], []
    isval = np.zeros(len(structs), bool)
    seg_defs = {
        "芝ダ": [], "芝ダ×距離帯": [], "クラス": [], "競馬場": [], "馬場": [], "開催週": [],
    }
    keymaps = {name: [None]*len(structs) for name in seg_defs}
    for k, st in enumerate(structs):
        Plist.append(st["P"][:, OPTIDX])
        finlist.append(np.array([st["fin"][u] for u in st["uma"]], float))
        nklist.append(np.array(st["pop"], float))
        isval[k] = st["isval"]
        mm = meta.get(st["rid"], {})
        keymaps["芝ダ"][k] = mm.get("surface")
        keymaps["芝ダ×距離帯"][k] = (mm.get("surface","?")+mm.get("band","?"))
        keymaps["クラス"][k] = mm.get("cls")
        keymaps["競馬場"][k] = mm.get("jyo_name")
        keymaps["馬場"][k] = mm.get("baba")
        keymaps["開催週"][k] = nichiji_band(mm.get("nichiji", 0))
    tr_idx = [k for k in range(len(structs)) if not isval[k]]
    va_idx = [k for k in range(len(structs)) if isval[k]]
    cur_w = np.array([FO.CUR_W.get(f, 0.0) for f in OPT])
    glob = fit_ols(tr_idx, Plist, finlist, nklist)   # 全体OLS(生)

    lines = ["# セグメント別スコア配分（条件別重み）の検証\n"]
    lines.append(f"訓練{len(tr_idx)}R / 検証{len(va_idx)}R。条件別OLSは全体OLSへ shrinkage(α=n/(n+{K_SHRINK:.0f}))。")
    lines.append("評価は検証期間（ホールドアウト）。partial_rhoは使わず軸精度＋実測ROIで判定。\n")

    # ベースライン（全体）
    lines.append("## ベースライン（全レース・検証期間）")
    lines.append("| 重み | R | 軸勝率 | 軸複勝率 | 軸単ROI | 軸複ROI | 馬連 | ワイド | 三連複 | 三連単 |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    b, f = evaluate(va_idx, cur_w, structs, Plist, payouts, PP); lines.append(line_for("現行(全体)", b, f))
    b, f = evaluate(va_idx, glob, structs, Plist, payouts, PP); lines.append(line_for("全体OLS", b, f))

    # 各セグメンテーションで条件別shrink重みを作り、検証で評価
    for name in seg_defs:
        km = keymaps[name]
        segs = sorted(set(x for x in km if x))
        # 各セグメントの訓練OLS→shrink
        wmap = {}
        for s in segs:
            sidx = [k for k in tr_idx if km[k] == s]
            if len(sidx) < MIN_SEG_TR:
                wmap[s] = glob.copy()
                continue
            c = fit_ols(sidx, Plist, finlist, nklist)
            if c is None:
                wmap[s] = glob.copy(); continue
            a = len(sidx) / (len(sidx) + K_SHRINK)
            wmap[s] = a * c + (1 - a) * glob
        b, f = evaluate(va_idx, wmap, structs, Plist, payouts, PP, per_seg_key=km)
        lines.append(f"\n## 条件別重み: {name}（検証期間・全レース集計）")
        lines.append("| 重み | R | 軸勝率 | 軸複勝率 | 軸単ROI | 軸複ROI | 馬連 | ワイド | 三連複 | 三連単 |")
        lines.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
        lines.append(line_for(f"条件別({name})", b, f))
        # 参照として同じ検証レースを現行で
        b2, f2 = evaluate(va_idx, cur_w, structs, Plist, payouts, PP)
        lines.append(line_for("（現行・同レース）", b2, f2))

    lines.append("\n**判定基準**: 条件別重みが検証の軸勝率・軸複勝率・各ROIで現行/全体OLSを明確に上回れば有効。")
    lines.append("同等〜下回れば、条件別に配分を変えても実益なし（過学習を排すると効かない）。")
    rep = os.path.join(SD, "factor_segweight_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
