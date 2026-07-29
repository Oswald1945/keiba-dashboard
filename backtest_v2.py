# -*- coding: utf-8 -*-
"""買い判定バックテスト基盤 v2: pred EV_DATA から判定を再構築し、結果(着順/単勝/複勝)で
判定別の軸単勝/複勝ROI・的中率を集計。対象は pred+結果が揃う全レース(157R)。"""
import re, json, glob, os, math, itertools
import pandas as pd
SD = os.path.dirname(os.path.abspath(__file__))
T = 20.0

def load_ev(p):
    h = open(p, encoding='utf-8').read()
    m = re.search(r'EV_DATA\s*=\s*(\[.*?\]);\s*\n', h, re.S)
    return json.loads(m.group(1)) if m else None

def pred_path(rid):
    for c in (f'{rid}_pred.html', f'pred_{rid}.html'):
        if os.path.exists(os.path.join(SD, c)):
            return os.path.join(SD, c)
    return None

def _num(x, d):
    try: return float(x)
    except: return d

def softmax(scores):
    mx = max(scores); e = [math.exp((s-mx)/T) for s in scores]; s = sum(e)
    return [x/s for x in e]

def load_result_csv(rid):
    """結果(html/csv)→ {馬番:(着順,単勝オッズ,複勝下限)}。"""
    base = os.path.join(SD, 'input', 'done')
    for ext in ('.csv', '.html'):
        fp = os.path.join(base, f'レース結果_{rid}{ext}')
        if not os.path.exists(fp): continue
        try:
            if ext == '.csv':
                df = pd.read_csv(fp, encoding='cp932', header=2, on_bad_lines='skip')
            else:
                import result_loader as rl
                df, _, _ = rl.load_result(fp)
        except Exception:
            continue
        df.columns = [str(c).strip() for c in df.columns]
        col_o = '入線順位' if '入線順位' in df.columns else ('着順' if '着順' in df.columns else None)
        if col_o is None or '馬番' not in df.columns: continue
        df = df[pd.to_numeric(df[col_o], errors='coerce').notna()].copy()
        tan_c = '単勝オッズ' if '単勝オッズ' in df.columns else None
        fuk_c = '複勝下限' if '複勝下限' in df.columns else None
        out = {}
        for _, r in df.iterrows():
            u = _num(r['馬番'], None)
            if u is None: continue
            out[int(u)] = (int(_num(r[col_o], 99)),
                           _num(r[tan_c], None) if tan_c else None,
                           _num(r[fuk_c], None) if fuk_c else None)
        if out: return out
    return None

def analyze(ev):
    """EV_DATAから 軸/偏差値/推定人気/現行判定 を返す。"""
    sc_raw = [h['スコア'] for h in ev]
    wp = softmax(sc_raw)
    mean = sum(sc_raw)/len(sc_raw)
    sd = math.sqrt(sum((s-mean)**2 for s in sc_raw)/len(sc_raw)) or 1
    arr = []
    for i, h in enumerate(ev):
        if wp[i] > 0 and h.get('馬番') is not None:
            arr.append(dict(uma=h['馬番'], p=wp[i], dev=50+10*(h['スコア']-mean)/sd,
                            src=h.get('SmartRC推定人気順'), rank=h.get('順位予想')))
    arr.sort(key=lambda x: -x['p'])
    arr = arr[:8]
    if len(arr) < 2: return None
    A = arr[0]
    srcA = _num(A['src'], 99)
    devA = A['dev']; dev2 = arr[1]['dev']
    gapA = devA - dev2
    dev4 = arr[3]['dev'] if len(arr) >= 4 else arr[-1]['dev']
    spread = devA - dev4
    # 現行判定
    fav1 = 99; ana = False
    for h in ev:
        ep = _num(h.get('SmartRC推定人気順'), 0); pr = _num(h.get('順位予想'), 0)
        if ep == 1: fav1 = pr
        if ep >= 5 and pr <= 3 and pr > 0: ana = True
    if srcA >= 4: cur = '中穴軸'
    elif srcA in (2, 3) and (fav1 >= 4 or ana): cur = '買い妙味'
    elif A['p'] < 0.18: cur = '混戦BOX'
    else: cur = '見送り'
    return dict(umA=A['uma'], wA=A['p'], srcA=srcA, devA=devA, gapA=gapA,
               spread=spread, cur=cur)

# ── 全レース集計 ──
rows = []
for r in glob.glob(os.path.join(SD,'input','done','レース結果_*.html')) + glob.glob(os.path.join(SD,'input','done','レース結果_*.csv')):
    m = re.search(r'レース結果_(\d{8}_[a-z0-9]+)\.', os.path.basename(r))
    if not m: continue
    rid = m.group(1)
    pp = pred_path(rid)
    if not pp: continue
    ev = load_ev(pp)
    if not ev: continue
    a = analyze(ev)
    if a is None: continue
    res = load_result_csv(rid)
    if not res or a['umA'] not in res: continue
    fin, tan, fuk = res[a['umA']]
    a.update(rid=rid, fin=fin, tan=tan, fuk=fuk)
    rows.append(a)

print(f'集計対象 {len(rows)}R\n')
from collections import defaultdict
def roi(bucket):
    n = len(bucket)
    if n == 0: return None
    win = sum(1 for x in bucket if x['fin'] == 1)
    plc = sum(1 for x in bucket if x['fin'] <= 3)
    tan_ret = sum((x['tan'] if x['fin']==1 and x['tan'] else 0) for x in bucket)
    fuk_ret = sum((x['fuk']/100 if x['fin']<=3 and x['fuk'] else 0) for x in bucket)
    return dict(n=n, win=win/n*100, plc=plc/n*100, tanROI=tan_ret/n*100, fukROI=fuk_ret/n*100)
print('=== 現行判定別 軸成績（157R）===')
for v in ['買い妙味','中穴軸','混戦BOX','見送り']:
    b=[x for x in rows if x['cur']==v]; m=roi(b)
    if m: print(f'  {v:6} {m["n"]:3d}R 勝率{m["win"]:4.0f}% 複勝率{m["plc"]:4.0f}% 軸単ROI{m["tanROI"]:4.0f}% 軸複ROI{m["fukROI"]:4.0f}%')
buy=[x for x in rows if x['cur'] in ('買い妙味','中穴軸')]; sk=[x for x in rows if x['cur'] in ('見送り','混戦BOX')]
print('\n=== 買い側(妙味+中穴) vs 見送り側(見送り+BOX) ===')
for lbl,b in [('買い側',buy),('見送り側',sk)]:
    m=roi(b); print(f'  {lbl} {m["n"]:3d}R 勝率{m["win"]:4.0f}% 複勝率{m["plc"]:4.0f}% 軸単ROI{m["tanROI"]:4.0f}% 軸複ROI{m["fukROI"]:4.0f}%')
# 偏差値分布(閾値の当たりをつける)
import statistics as st
print('\n=== 偏差値指標の分布(全157R) ===')
for key in ['gapA','spread']:
    vals=sorted(x[key] for x in rows)
    print(f'  {key}: 中央{st.median(vals):.1f} 25%{vals[len(vals)//4]:.1f} 75%{vals[len(vals)*3//4]:.1f} min{vals[0]:.1f} max{vals[-1]:.1f}')
json.dump([{k:(round(v,3) if isinstance(v,float) else v) for k,v in x.items()} for x in rows],
          open(os.path.join(SD,'backtest_v2_rows.json'),'w'), ensure_ascii=False)
print('\n-> backtest_v2_rows.json 保存')
