# -*- coding: utf-8 -*-
"""
factor_roi_offline.py ― 重み別の実測ROIをオフライン比較（高速版）
==============================================================
factor_rows.jsonl（各馬の因子pts+着順+人気+単勝）と payouts_cache.jsonl（確定配当）
だけで、重み(FACTOR_WEIGHTS)変更後の実測ROIを再計算:
  ・軸単勝ROI / 軸複勝ROI / 軸勝率 / 軸複勝率（判定別＋全体）
  ・券種フォーメーションROI（馬連/ワイド/馬単/三連複/三連単）
総合スコア=Σw×pts（r≈0.95で線形）で採点を再現。買い判定・列ロジックは
bet_recon.reconstruct を忠実に踏襲（表示専用のHarville確率のみ省略）。DB不要。
出力: factor_roi_offline_report.md
"""
import json, os, math, itertools
import numpy as np
import factor_optimize as FO

SD = os.path.dirname(os.path.abspath(__file__))
FROWS = os.path.join(SD, "factor_rows.jsonl")
PCACHE = os.path.join(SD, "payouts_cache.jsonl")
SPLIT_DATE = FO.SPLIT_DATE
FACTORS = FO.FACTORS
ORDER_BT = ["馬連", "ワイド", "馬単", "三連複", "三連単"]


def load_structs():
    """レースごとに (P行列, umaban, コース特徴, 人気, 着順, 単勝) を事前計算。"""
    races = {}
    for l in open(FROWS, encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        races.setdefault(r["rid"], []).append(r)
    structs = []
    ktidx = FACTORS.index("コース特徴pts")
    for rid, rows in races.items():
        rows = [x for x in rows if x.get("umaban") is not None]
        if len(rows) < 5:
            continue
        P = np.zeros((len(rows), len(FACTORS)))
        uma = []; fin = {}; tan = {}; pop = []
        for i, x in enumerate(rows):
            for j, f in enumerate(FACTORS):
                v = x.get(f)
                if v is not None:
                    P[i, j] = v
            u = int(x["umaban"]); uma.append(u)
            fin[u] = x.get("着順"); tan[u] = x.get("単勝")
            pop.append(x.get("人気"))
        structs.append(dict(rid=rid, isval=rid[:8] >= SPLIT_DATE, P=P,
                            uma=uma, kt=P[:, ktidx], pop=pop, fin=fin, tan=tan))
    return structs


def load_payouts():
    po = {}
    if not os.path.exists(PCACHE):
        return po
    for l in open(PCACHE, encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        po[r["rid"]] = r["payouts"]
    return po


def slim_reconstruct(score, uma, kt, pop):
    """bet_recon.reconstruct の判定・列ロジックを忠実に再現（表示用確率は省略）。"""
    n = len(score)
    if n < 2:
        return None
    mean = float(np.mean(score))
    sd = float(np.std(score)) or 1.0
    dev = 50 + 10 * (score - mean) / sd
    idx = list(np.argsort(-score))          # スコア降順（オッズ非cap＝winprob降順と同順）
    idx = idx[:8]
    if len(idx) < 2:
        return None
    names = [str(uma[i]) for i in idx]
    um = {str(uma[i]): int(uma[i]) for i in idx}
    dv = {str(uma[i]): float(dev[i]) for i in idx}
    sc = {str(uma[i]): pop[i] for i in idx}
    kt_map = {str(uma[i]): float(kt[i]) for i in idx}
    A = names[0]; devA = dv[A]
    n_runners = n
    cand = [nm for nm in names if nm != A and (devA - dv[nm]) <= 20.0]
    cand.sort(key=lambda nm: -dv[nm])
    cap = min(6, n_runners // 3)
    partners = []; prev = None
    for nm in cand:
        if len(partners) >= cap:
            break
        if partners and (prev - dv[nm]) > 5.0:
            break
        partners.append(nm); prev = dv[nm]
    col1 = ([A] + [nm for nm in partners if (devA - dv[nm]) <= 3.0])[:3]
    head_fixed = (len(col1) == 1)
    col2 = ([] if head_fixed else [A]) + [nm for nm in partners if (devA - dv[nm]) <= 10.0]
    col3 = ([] if head_fixed else [A]) + list(partners)
    contend = [A] + partners

    def _pop(nm):
        v = sc.get(nm)
        try: return int(v)
        except Exception: return 99
    kt_axis = kt_map.get(A)
    top3 = sum(1 for nm in contend if _pop(nm) in (1, 2, 3))
    cond1 = top3 <= 2
    cond2 = True if _pop(A) not in (1, 2) else all(_pop(nm) not in (1, 2, 3, 4) for nm in partners)
    cond3 = (kt_axis is not None and kt_axis > 0)
    pops_ct = [_pop(nm) for nm in contend]
    only123 = all(p in (1, 2, 3) for p in pops_ct)
    all123in = all(r in pops_ct for r in (1, 2, 3))
    cond4 = not (only123 or all123in)
    verdict = '購入推奨' if (len(partners) >= 1 and cond1 and cond2 and cond3 and cond4) else '購入非推奨'
    col1 = sorted(col1, key=lambda nm: um[nm])
    col2 = sorted(col2, key=lambda nm: um[nm])
    col3 = sorted(col3, key=lambda nm: um[nm])
    return dict(A=A, umA=um[A], verdict=verdict, col1=col1, col2=col2, col3=col3, um=um)


def parse_po(po):
    """払戻dictを1回だけ組番パース（レースごとに使い回す・pandas不使用の高速評価用）。"""
    def cmb(key, k):
        out = []
        for c, a in (po.get(key) or []):
            try:
                parts = [int(x) for x in str(c).split('-')]
            except Exception:
                continue
            if len(parts) == k:
                out.append((parts, a))
        return out
    return dict(
        umaren=[(set(p), a) for p, a in cmb('umaren', 2)],
        wide=[(set(p), a) for p, a in cmb('wide', 2)],
        umatan=cmb('umatan', 2),
        s3p=[(set(p), a) for p, a in cmb('sanrenpuku', 3)],
        s3t=cmb('sanrentan', 3),
    )


def slim_eval(rec, pp):
    """bet_recon.eval_race のフォーメーション集計を pandas 無しで再現。券種→(点数,払戻)。"""
    um = rec['um']; A = rec['A']; umA = rec['umA']
    col1u = [um[n] for n in rec['col1']]
    col2u = [um[n] for n in rec['col2']]
    col3u = [um[n] for n in rec['col3']]
    uren = [um[n] for n in rec['col2'] if n != A]
    wd = [um[n] for n in rec['col3'] if n != A]
    bets = {}
    ret = 0
    for o in uren:
        for cs, a in pp['umaren']:
            if cs == {umA, o}: ret += a
    bets['馬連'] = (len(uren), ret)
    ret = 0
    for o in wd:
        for cs, a in pp['wide']:
            if cs == {umA, o}: ret += a
    bets['ワイド'] = (len(wd), ret)
    pts = 0; ret = 0
    for i in col1u:
        for j in col2u:
            if i != j:
                pts += 1
                for combo, a in pp['umatan']:
                    if combo == [i, j]: ret += a
    bets['馬単'] = (pts, ret)
    ret = 0; cnt = 0
    for c in itertools.combinations(wd, 2):
        cnt += 1
        for cs, a in pp['s3p']:
            if cs == {umA, c[0], c[1]}: ret += a
    bets['三連複'] = (cnt, ret)
    pts = 0; ret = 0
    for i in col1u:
        for j in col2u:
            for k in col3u:
                if i != j and j != k and i != k:
                    pts += 1
                    for combo, a in pp['s3t']:
                        if combo == [i, j, k]: ret += a
    bets['三連単'] = (pts, ret)
    return bets


def wvec(wd):
    return np.array([wd.get(f, 0.0) for f in FACTORS], float)


def weight_sets():
    data = FO.load(); train, _ = FO.split(data)
    optidx = [FACTORS.index(f) for f in FO.OPT]
    Xs, ys = [], []
    for r in train.values():
        P = r["P"][:, optidx]; y = -r["fin"]; pp = r["nk"]
        Xs.append(np.column_stack([P - P.mean(0), pp - pp.mean()])); ys.append(y - y.mean())
    X = np.vstack(Xs); y = np.concatenate(ys)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None); ols = beta[:len(FO.OPT)]

    def c2w(fac, cap=None):
        pos = [c for c in fac if c > 0]; scl = np.median(pos) if pos else 1.0
        wd = dict(FO.CUR_W)
        for f, c in zip(FO.OPT, fac):
            v = max(0.0, c) / scl if scl > 0 else 0.0
            if cap is not None: v = min(v, cap)
            wd[f] = round(v, 2)
        return wd
    return {"現行": dict(FO.CUR_W), "OLS生": c2w(ols), "OLS上限3": c2w(ols, cap=3.0)}


def evaluate(wd, structs, payouts, PP):
    from collections import defaultdict
    wv = wvec(wd)
    # buckets[subset][verdict or 全レース] = dict, form[subset][全体][bt]=[点数,払戻]
    def newb():
        return defaultdict(lambda: dict(n=0, win=0, plc=0, tanR=0.0, fukR=0.0))
    def newf():
        return defaultdict(lambda: [0, 0.0])
    B = {"val": newb(), "all": newb()}
    F = {"val": newf(), "all": newf()}

    for st in structs:
        score = st["P"] @ wv
        rc = slim_reconstruct(score, st["uma"], st["kt"], st["pop"])
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
        subs = ["all"] + (["val"] if st["isval"] else [])
        for sub in subs:
            for key in (rc["verdict"], "全レース"):
                b = B[sub][key]; b["n"] += 1
                if fA == 1:
                    b["win"] += 1
                    if st["tan"].get(umA): b["tanR"] += st["tan"][umA]
                if fA and fA <= 3:
                    b["plc"] += 1
                    if fuk.get(umA): b["fukR"] += fuk[umA]
        pp = PP.get(st["rid"])
        if pp is not None:
            bets = slim_eval(rc, pp)
            for sub in subs:
                for bt, v in bets.items():
                    F[sub][bt][0] += v[0]; F[sub][bt][1] += v[1]
    return B, F


def main():
    structs = load_structs()
    payouts = load_payouts()
    if not payouts:
        print("payouts_cache.jsonl が無い。先に dump_payouts.py を実行。"); return
    WS = weight_sets()
    PP = {rid: parse_po(po) for rid, po in payouts.items()}
    results = {name: evaluate(wd, structs, payouts, PP) for name, wd in WS.items()}

    lines = ["# 重み別の実測ROIオフライン比較（軸単複＋フォーメーション）\n"]
    lines.append(f"分割: 訓練<{SPLIT_DATE}≤検証。連系配当は payouts_cache（NL_HR_PAY）。\n")
    for sub, label in (("val", "検証期間(ホールドアウト)"), ("all", "全期間")):
        lines.append(f"\n## {label}")
        lines.append("### 軸（スコア1位）単複ROI・全レース")
        lines.append("| 重み | R数 | 軸勝率 | 軸複勝率 | 軸単勝ROI | 軸複勝ROI |")
        lines.append("|---|--:|--:|--:|--:|--:|")
        for name in WS:
            b = results[name][0][sub]["全レース"]; n = max(1, b["n"])
            lines.append("| %s | %d | %.1f%% | %.1f%% | %.0f%% | %.0f%% |"
                         % (name, b["n"], 100*b["win"]/n, 100*b["plc"]/n,
                            100*b["tanR"]/n, 100*b["fukR"]/n))
        lines.append("\n### 券種フォーメーションROI・全レース（軸流し各組1点）")
        lines.append("| 重み | 馬連 | ワイド | 馬単 | 三連複 | 三連単 |")
        lines.append("|---|--:|--:|--:|--:|--:|")
        for name in WS:
            F = results[name][1][sub]
            cells = []
            for bt in ORDER_BT:
                pts, ret = F[bt]
                cells.append("%.0f%%" % (100*ret/(pts*100)) if pts else "—")
            lines.append("| %s | %s |" % (name, " | ".join(cells)))
    lines.append("\n※軸単複は実オッズ・実複勝配当。フォーメーションはNL_HR_PAY確定配当で軸流し各組1点。")
    lines.append("※100%超で控除率超えの妙味。重み間で連系ROIが伸びるかが採否の決め手。")
    rep = os.path.join(SD, "factor_roi_offline_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
