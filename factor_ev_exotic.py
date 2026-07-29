# -*- coding: utf-8 -*-
"""
factor_ev_exotic.py ― 三連系(三連複/三連単)のEV検証：非効率市場でモデルは+EVを拾えるか
==============================================================
単勝市場は効率的でエッジ無し。だが三連系は市場が非効率になりやすい。
確定配当(payouts_cache)を実質オッズとして、
  モデル勝率(較正済T)→Harvilleで各組の的中確率 p_model
  単勝オッズ由来の勝率→Harvilleで p_market
  overlay比 = p_model / p_market が閾値R超の組だけ購入（＝モデルが市場より高評価＝妙味）
  的中(=実際の当たり組が購入集合に入る)なら実配当を回収
ホールドアウトROIが訓練・検証とも100%超(★)なら、三連系に本物の+EVエッジ。
新馬・未勝利は除外。top-K頭(モデル上位)内で組を生成。
依存: numpy。DB不要。 出力: factor_ev_exotic_report.md
"""
import json, os, math, itertools
import numpy as np
import factor_roi_offline as FR

SD = os.path.dirname(os.path.abspath(__file__))
ROWS = os.path.join(SD, "factor_rows.jsonl")
SPLIT = "20250601"
EXCLUDE_CLS = {"新馬", "未勝利"}
T_CAL = 25.0     # factor_ev で較正済の温度
TOPK = 7         # モデル上位K頭内で組を生成


def load_cls():
    m = {}
    p = os.path.join(SD, "racemeta_cache.jsonl")
    for l in open(p, encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        m[r["rid"]] = r.get("cls", "?")
    return m


def load():
    cls = load_cls()
    payouts = FR.load_payouts()
    races = {}
    for l in open(ROWS, encoding="utf-8"):
        try: r = json.loads(l)
        except Exception: continue
        races.setdefault(r["rid"], []).append(r)
    out = []
    for rid, rows in races.items():
        if cls.get(rid, "?") in EXCLUDE_CLS:
            continue
        if len(rows) < 6:
            continue
        s = np.array([x.get("総合スコア") for x in rows], float)
        od = np.array([x.get("単勝") if x.get("単勝") else np.nan for x in rows], float)
        uma = np.array([x.get("umaban") for x in rows])
        if np.isnan(s).any() or np.isnan(od).any() or any(u is None for u in uma):
            continue
        pp = FR.parse_po(payouts.get(rid, {}))
        s3p = {frozenset(c): a for c, a in pp["s3p"]}
        s3t = {tuple(c): a for c, a in pp["s3t"]}
        if not s3p and not s3t:
            continue
        out.append((rid[:8] >= SPLIT, s, od, [int(u) for u in uma], s3p, s3t))
    return out


def softmax_T(s, T):
    z = (s - s.max()) / T; e = np.exp(z); return e / e.sum()


def harville_order(p, idx3):
    i, j, k = idx3
    pi, pj, pk = p[i], p[j], p[k]
    d1 = 1 - pi
    d2 = 1 - pi - pj
    if d1 <= 0 or d2 <= 0:
        return 0.0
    return pi * (pj / d1) * (pk / d2)


def combo_probs(p, top):
    """top内の順列/組の Harville 確率。返す: dict(三連単 order->p), dict(三連複 set->p)。"""
    tri = {}
    for perm in itertools.permutations(top, 3):
        tri[perm] = harville_order(p, perm)
    trio = {}
    for c in itertools.combinations(top, 3):
        s = 0.0
        for perm in itertools.permutations(c, 3):
            s += tri[perm]
        trio[frozenset(c)] = s
    return tri, trio


def run(data, R, kind):
    """kind: 'trio'(三連複) / 'tri'(三連単)。overlay比>R の組を購入。ROI/的中/賭け数。"""
    nbet = hit = 0; ret = 0.0
    for isval, s, od, uma, s3p, s3t in data:
        pm = softmax_T(s, T_CAL)
        pk = (1.0 / od) / (1.0 / od).sum()
        topidx = list(np.argsort(-pm)[:TOPK])
        tri_m, trio_m = combo_probs(pm, topidx)
        tri_k, trio_k = combo_probs(pk, topidx)
        if kind == "trio":
            win = next(iter(s3p)) if s3p else None
            pay = s3p.get(win) if win else None
            for c, pmv in trio_m.items():
                pkv = trio_k.get(c, 0.0)
                if pkv > 0 and pmv / pkv > R:
                    nbet += 1
                    umset = frozenset(uma[i] for i in c)
                    if win is not None and umset == win:
                        hit += 1; ret += pay / 100.0
        else:
            win = next(iter(s3t)) if s3t else None
            pay = s3t.get(win) if win else None
            for c, pmv in tri_m.items():
                pkv = tri_k.get(c, 0.0)
                if pkv > 0 and pmv / pkv > R:
                    nbet += 1
                    umtpl = tuple(uma[i] for i in c)
                    if win is not None and umtpl == win:
                        hit += 1; ret += pay / 100.0
    if nbet == 0:
        return None
    return dict(nbet=nbet, hit=100*hit/nbet, roi=100*ret/nbet)


def main():
    data = load()
    tr = [d for d in data if not d[0]]; va = [d for d in data if d[0]]
    lines = ["# 三連系のEV検証（オーバーレイ買い・新馬未勝利除外）\n"]
    lines.append(f"訓練{len(tr)}R / 検証{len(va)}R。モデル上位{TOPK}頭内で組生成、"
                 f"overlay比(p_model/p_market)>R を購入、実配当で回収。較正T={T_CAL:.0f}。\n")
    for kind, label in (("trio", "三連複"), ("tri", "三連単")):
        lines.append(f"\n## {label}")
        lines.append("| overlay比R | 賭け数(訓/検) | 的中率(訓/検) | ROI(訓｜検) |")
        lines.append("|---|--:|--:|--:|")
        for R in (1.0, 1.38, 2.0, 3.0, 5.0, 10.0):
            rt = run(tr, R, kind); rv = run(va, R, kind)
            if not rt or not rv:
                continue
            star = " ★" if rt["roi"] > 100 and rv["roi"] > 100 else ""
            lines.append("| %.2f | %d/%d | %.1f%%/%.1f%% | %.0f%%｜%.0f%%%s |" % (
                R, rt["nbet"], rv["nbet"], rt["hit"], rv["hit"], rt["roi"], rv["roi"], star))
    lines.append("\n**判定**: ROIが訓練・検証とも100%超(★)なら三連系に+EVエッジ。"
                 "無ければ非効率市場でもモデルは市場を写すだけ＝既存情報での+EVは打ち止め。")
    lines.append(f"\n※market確率は単勝オッズ由来のHarville。overlay比>Rでモデルが市場より高評価の組のみ購入。")
    rep = os.path.join(SD, "factor_ev_exotic_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    main()
