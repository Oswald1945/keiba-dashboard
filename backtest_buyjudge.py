# -*- coding: utf-8 -*-
"""
backtest_buyjudge.py — 買いレース判定の期待値検証。
各過去レースで軸=モデル勝率1位を選び、想定人気(est_pop)別の市場ベースラインに対する
エッジ(モデル勝率−市場推定勝率)で「買い/見送り」を判定したときの、軸単勝ROI・複勝ROI・
的中率・想定人気分布を、現行ルールと比較する。確定オッズが無い予想時を再現するため、
softmaxの上限キャップは smartrc の odds_tan(想定オッズ) を使う。
"""
import json, glob, math, pathlib
import numpy as np
import pandas as pd

SD = pathlib.Path(__file__).parent
DONE = SD / 'input' / 'done'
T = 20.0
MR = 3.0


def win_probs(scores, odds):
    s = np.array(scores, float)
    e = np.exp((s - s.max()) / T)
    p = e / e.sum()
    capped = []
    for pi, o in zip(p, odds):
        if o and o > 0:
            capped.append(min(pi, (1.0 / o) * MR))
        else:
            capped.append(pi)
    capped = np.array(capped)
    return capped / capped.sum()


def load_race(rid):
    sc_f = SD / f'scores_{rid}.csv'
    sm_f = SD / f'smartrc_{rid}.json'
    rs_f = DONE / f'レース結果_{rid}.csv'
    if not (sc_f.exists() and sm_f.exists() and rs_f.exists()):
        return None
    try:
        sc = pd.read_csv(sc_f, encoding='utf-8-sig')
    except Exception:
        sc = pd.read_csv(sc_f, encoding='cp932')
    sc.columns = [str(c).strip() for c in sc.columns]
    sc = sc[['馬名', '総合スコア']].dropna()
    sm = json.load(open(sm_f, encoding='utf-8'))['horses']
    est = {v['hname']: v.get('est_pop') for v in sm.values()}
    odt = {v['hname']: v.get('odds_tan') for v in sm.values()}
    rs = pd.read_csv(rs_f, encoding='cp932', header=2, on_bad_lines='skip')
    rs.columns = [str(c).strip() for c in rs.columns]
    rs = rs[pd.to_numeric(rs['入線順位'], errors='coerce').notna()].copy()
    rs['着順'] = pd.to_numeric(rs['入線順位'], errors='coerce')
    rs['単オッズ'] = pd.to_numeric(rs['単勝オッズ'], errors='coerce')
    rs['複下'] = pd.to_numeric(rs['複勝下限'], errors='coerce')
    res = {str(r['馬名']).strip(): (r['着順'], r['単オッズ'], r['複下']) for _, r in rs.iterrows()}

    rows = []
    for _, r in sc.iterrows():
        nm = str(r['馬名']).strip()
        if nm not in res or nm not in est:
            continue
        ep = est.get(nm)
        rows.append({
            'name': nm, 'score': float(r['総合スコア']),
            'est': (int(ep) if ep not in (None, '') else None),
            'odt': (float(odt[nm]) if odt.get(nm) not in (None, '') else None),
            'chaku': res[nm][0], 'tan': res[nm][1], 'fuku': res[nm][2],
        })
    if len(rows) < 5:
        return None
    df = pd.DataFrame(rows)
    df['p'] = win_probs(df['score'].values, df['odt'].values)
    df['dev'] = 50 + 10 * (df['score'] - df['score'].mean()) / (df['score'].std(ddof=0) or 1)
    return df.sort_values('p', ascending=False).reset_index(drop=True)


rids = sorted(f.stem.replace('レース結果_', '') for f in DONE.glob('レース結果_*.csv') if '_dup' not in f.name)
races = []
allrows = []
for rid in rids:
    d = load_race(rid)
    if d is None:
        continue
    races.append((rid, d))
    for _, r in d.iterrows():
        allrows.append({'est': r['est'], 'win': int(r['chaku'] == 1), 'plc': int(r['chaku'] <= 3)})

A = pd.DataFrame(allrows).dropna(subset=['est'])
print(f"検証対象 {len(races)}R / 全{len(A)}頭\n")

# ── 市場ベースライン: 想定人気別 実勝率/実複勝率 ──
print("=== 市場ベースライン（想定人気 est_pop 別 実績）===")
base_win, base_plc = {}, {}
for ep in range(1, 13):
    s = A[A['est'] == ep]
    if len(s) >= 8:
        base_win[ep] = s['win'].mean()
        base_plc[ep] = s['plc'].mean()
        print(f"  想定{ep:2d}番人気 n={len(s):4d} 勝率{s['win'].mean():.1%} 複勝率{s['plc'].mean():.1%}")
# 平滑化: 単調になるよう線形回帰でフォールバック
eps = sorted(base_win)
coef = np.polyfit(eps, [base_win[e] for e in eps], 2)


def mkt_win(ep):
    if ep in base_win:
        return base_win[ep]
    return max(0.01, float(np.polyval(coef, ep)))


print()


def axis_metrics(flagged):
    """flagged: list of (rid, axis_row). 軸単勝/複勝ROIと分布を返す。"""
    n = len(flagged)
    if n == 0:
        return None
    tan_ret = np.mean([(a['tan'] if a['chaku'] == 1 else 0) for _, a in flagged])
    fuku_ret = np.mean([(a['fuku'] if a['chaku'] <= 3 and not math.isnan(a['fuku']) else 0) for _, a in flagged])
    winr = np.mean([int(a['chaku'] == 1) for _, a in flagged])
    plcr = np.mean([int(a['chaku'] <= 3) for _, a in flagged])
    fav = np.mean([int((a['est'] or 99) == 1) for _, a in flagged])
    fav3 = np.mean([int((a['est'] or 99) <= 3) for _, a in flagged])
    return dict(n=n, tanROI=tan_ret * 100, fukuROI=fuku_ret * 100,
                win=winr * 100, plc=plcr * 100, fav1=fav * 100, fav3=fav3 * 100)


def show(label, flagged):
    m = axis_metrics(flagged)
    if not m:
        print(f"{label}: 0R")
        return
    print(f"{label}: {m['n']:3d}R  軸単勝ROI={m['tanROI']:5.0f}% 複勝ROI={m['fukuROI']:5.0f}% "
          f"勝率{m['win']:4.0f}% 複勝率{m['plc']:4.0f}% │ 軸が想定1人気{m['fav1']:3.0f}% ≤3人気{m['fav3']:3.0f}%")


# 各レースの軸情報
axinfo = []
for rid, d in races:
    a = d.iloc[0]
    wA = a['p']
    srcA = a['est'] if a['est'] else 99
    gap = wA - (d.iloc[1]['p'] if len(d) > 1 else 0)
    edge = wA - mkt_win(srcA if srcA <= 12 else 12)
    axinfo.append((rid, a, wA, srcA, gap, edge))

print("=== 全レース軸の基準値分布 ===")
wAs = [x[2] for x in axinfo]
edges = [x[5] for x in axinfo]
print(f"  wA: 中央{np.median(wAs):.2f} 25%{np.percentile(wAs,25):.2f} 75%{np.percentile(wAs,75):.2f}")
print(f"  edge: 中央{np.median(edges):+.2f} 25%{np.percentile(edges,25):+.2f} 75%{np.percentile(edges,75):+.2f}")
print(f"  軸の想定人気=1の割合: {np.mean([int((x[3] or 99)==1) for x in axinfo]):.0%}\n")

# ── ① 現行ルール ──
print("=== ① 現行ルール（wA絶対閾値）===")
cur_buy = [(rid, a) for rid, a, wA, srcA, gap, edge in axinfo if wA >= 0.18]
cur_skip = [(rid, a) for rid, a, wA, srcA, gap, edge in axinfo if wA < 0.18]
show("  買い(wA≥0.18)", cur_buy)
show("  見送り(wA<0.18)", cur_skip)
print()

# ── ② エッジルール（候補） ──
print("=== ② エッジルール候補（買い=edge≥τ かつ wA≥floor）===")
for floor in [0.08, 0.10, 0.12]:
    for tau in [0.00, 0.02, 0.04, 0.06]:
        buy = [(rid, a) for rid, a, wA, srcA, gap, edge in axinfo if edge >= tau and wA >= floor]
        m = axis_metrics(buy)
        if m and m['n'] >= 8:
            print(f"  floor={floor:.2f} τ={tau:.2f} → {m['n']:3d}R 単勝ROI{m['tanROI']:5.0f}% 複勝ROI{m['fukuROI']:5.0f}% "
                  f"勝率{m['win']:3.0f}% 複勝率{m['plc']:3.0f}% 軸想定1人気{m['fav1']:3.0f}%")
print()

print("=== 参考: 全レース軸を機械的に単勝/複勝した場合 ===")
show("  全R軸ベタ買い", [(rid, a) for rid, a, *_ in axinfo])

print("\n=== ③ 買い集合(edge≥0 & wA≥0.10) を想定人気帯で分解 ===")
buy = [(rid,a,wA,srcA,gap,edge) for rid,a,wA,srcA,gap,edge in axinfo if edge>=0 and wA>=0.10]
skip = [(rid,a,wA,srcA,gap,edge) for rid,a,wA,srcA,gap,edge in axinfo if not(edge>=0 and wA>=0.10)]
for lo,hi,nm in [(1,1,'想定1人気'),(2,3,'想定2-3人気'),(4,6,'想定4-6人気'),(7,99,'想定7人気以下')]:
    seg=[(rid,a) for rid,a,wA,srcA,gap,edge in buy if lo<=(srcA or 99)<=hi]
    show(f"  {nm}",seg)
print()
show("  ▼買い集合 全体", [(rid,a) for rid,a,*_ in buy])
show("  ▼見送り集合 全体", [(rid,a) for rid,a,*_ in skip])

print("\n=== ④ 高オッズ軸(妙味)の単勝ROI: 軸の実単勝オッズ帯別(買い集合内) ===")
for lo,hi,nm in [(0,5,'~5倍'),(5,10,'5-10倍'),(10,20,'10-20倍'),(20,999,'20倍~')]:
    seg=[(rid,a) for rid,a,wA,srcA,gap,edge in buy if lo<=(a['tan'] or 0)<hi]
    show(f"  {nm}",seg)

print("\n=== ⑤ '妙味'軸(srcA≥3 & edge≥0)だけ単勝で追ったら ===")
miyomi=[(rid,a) for rid,a,wA,srcA,gap,edge in axinfo if (srcA or 99)>=3 and edge>=0 and wA>=0.10]
show("  妙味軸 単勝",miyomi)

print("\n=== ⑥ 最終ルール検証 ===")
def mktWinF(ep):
    return {1:0.31,2:0.18,3:0.15,4:0.12,5:0.08,6:0.05}.get(min(ep,7),0.03)
def verdict(wA,srcA,edge):
    if wA<0.10: return 'skip','軸不在の混戦'
    if (srcA or 99)>=4: return 'skip','中穴軸の罠回避'
    if edge<0: return 'skip','人気どおりで妙味薄'
    if (srcA or 99) in (2,3): return 'buyA','妙味(市場2-3番手をモデル最上位)'
    return 'buyB','堅軸(市場以上に支持)'
buckets={'buyA':[],'buyB':[],'skip':[]}
for rid,a,wA,srcA,gap,e in axinfo:
    edge=wA-mktWinF(srcA if srcA<=12 else 12)
    v,_=verdict(wA,srcA,edge); buckets[v].append((rid,a))
show("  買い推奨(妙味) buyA",buckets['buyA'])
show("  買い推奨(堅軸) buyB",buckets['buyB'])
show("  買い合計",buckets['buyA']+buckets['buyB'])
show("  見送り",buckets['skip'])
