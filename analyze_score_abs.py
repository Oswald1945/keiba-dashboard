# -*- coding: utf-8 -*-
"""スコア1位の絶対値と実際着順の相関分析"""
import re, json, glob, pathlib

BASE = pathlib.Path('/sessions/adoring-focused-galileo/mnt/keiba-dashboard')

def parse_review(fp):
    txt = pathlib.Path(fp).read_text(encoding='utf-8', errors='ignore')
    m = re.search(r'const DATA = (\[.*?\]);', txt)
    if not m: return None
    try: return json.loads(m.group(1))
    except: return None

json_files = sorted(glob.glob(str(BASE / 'horses_data_*.json')))
records = []
for jp in json_files:
    jname = pathlib.Path(jp).stem
    parts = jname.replace('horses_data_','').split('_')
    if len(parts) < 2: continue
    date_str, venue_r = parts[0], parts[1]
    import re as re2
    vc = re2.match(r'[a-z]+', venue_r)
    rn = re2.search(r'\d+', venue_r)
    if not vc or not rn: continue
    vc2 = vc.group().upper()
    rn2 = rn.group()
    alts = [vc2, {'KT':'KY','KY':'KT','TK':'TK','NG':'NG'}.get(vc2, vc2)]
    matches = []
    for a in alts:
        matches += glob.glob(str(BASE / f'{date_str}_{a}{rn2}R_*_review.html'))
    if not matches: continue
    rev = parse_review(matches[0])
    if not rev: continue
    with open(jp) as f: jdata = json.load(f)
    horses = jdata.get('horses', [])
    if not horses: continue
    act_map = {h['馬名']: h.get('入線順位', 99) for h in rev}
    records.append({'horses': horses, 'act_map': act_map})

print(f'対象: {len(records)}レース\n')

# スコア1位馬の絶対スコア vs 実際着順
data_points = []
for r in records:
    horses = r['horses']
    pred1 = min(horses, key=lambda h: h.get('順位予想', 99))
    act1  = r['act_map'].get(pred1['馬名'], 99)
    score = pred1.get('総合スコア', 0)
    n     = len(horses)
    # 偏差値（レース内相対）
    scores_all = [h.get('総合スコア',0) for h in horses]
    mu  = sum(scores_all)/len(scores_all)
    sig = (sum((s-mu)**2 for s in scores_all)/len(scores_all))**0.5 or 1
    dev = round((score - mu)/sig*10+50)
    # スコア2位との差
    sorted_h = sorted(horses, key=lambda h: h.get('順位予想',99))
    score2 = sorted_h[1].get('総合スコア', 0) if len(sorted_h) > 1 else 0
    gap = score - score2
    data_points.append({'score': score, 'dev': dev, 'act': act1,
                        'gap': gap, 'n': n})

# ── 絶対スコア帯別 ─────────────────────────────────────────
print('【スコア1位の絶対スコア帯別 成績】')
bands = [
    ('S (≥60)',  60, 999),
    ('A (50-59)', 50, 59.9),
    ('B (40-49)', 40, 49.9),
    ('C (30-39)', 30, 39.9),
    ('D (<30)',    0, 29.9),
]
for label, lo, hi in bands:
    sub = [x for x in data_points if lo <= x['score'] <= hi]
    if not sub: continue
    n   = len(sub)
    w   = sum(1 for x in sub if x['act']==1)
    t3  = sum(1 for x in sub if x['act']<=3)
    avg = sum(x['act'] for x in sub)/n
    print(f'  {label:12s}: {n:2d}R  勝率={w/n*100:.0f}%  複勝率={t3/n*100:.0f}%  平均着順={avg:.1f}')

# ── 偏差値帯別 ────────────────────────────────────────────
print('\n【スコア1位の偏差値帯別 成績】')
dev_bands = [
    ('偏差≥65',  65, 999),
    ('偏差60-64', 60, 64),
    ('偏差55-59', 55, 59),
    ('偏差50-54', 50, 54),
    ('偏差<50',    0, 49),
]
for label, lo, hi in dev_bands:
    sub = [x for x in data_points if lo <= x['dev'] <= hi]
    if not sub: continue
    n   = len(sub)
    w   = sum(1 for x in sub if x['act']==1)
    t3  = sum(1 for x in sub if x['act']<=3)
    avg = sum(x['act'] for x in sub)/n
    print(f'  {label:12s}: {n:2d}R  勝率={w/n*100:.0f}%  複勝率={t3/n*100:.0f}%  平均着順={avg:.1f}')

# ── スコア差（1位-2位）帯別 ───────────────────────────────────
print('\n【スコア1位-2位の差（リード幅）別 成績】')
gap_bands = [
    ('差≥15pt',  15, 999),
    ('差10-14pt', 10, 14.9),
    ('差 5-9pt',   5,  9.9),
    ('差 0-4pt',   0,  4.9),
]
for label, lo, hi in gap_bands:
    sub = [x for x in data_points if lo <= x['gap'] <= hi]
    if not sub: continue
    n   = len(sub)
    w   = sum(1 for x in sub if x['act']==1)
    t3  = sum(1 for x in sub if x['act']<=3)
    avg = sum(x['act'] for x in sub)/n
    print(f'  {label:12s}: {n:2d}R  勝率={w/n*100:.0f}%  複勝率={t3/n*100:.0f}%  平均着順={avg:.1f}')

# ── 組み合わせ：乖離×スコア ──────────────────────────────────
print('\n【推奨度×スコア絶対値の組み合わせ】')
def kairido_max(horses, top_n=3):
    sp = sorted(horses, key=lambda h: h.get('順位予想',99))[:top_n]
    ks = []
    for h in sp:
        src = h.get('SmartRC推定人気順')
        if src:
            try: ks.append(int(src) - h.get('順位予想',99))
            except: pass
    return max(ks, default=0)

combos = {}
for r in records:
    horses = r['horses']
    pred1  = min(horses, key=lambda h: h.get('順位予想',99))
    act1   = r['act_map'].get(pred1['馬名'], 99)
    score  = pred1.get('総合スコア', 0)
    mk     = kairido_max(horses)
    n      = len(horses)
    fav_rank = next((h.get('順位予想',99) for h in horses if h.get('人気')==1), 99)
    thr = n//2 if n<=12 else 7
    fav_low = fav_rank > thr
    if mk >= 4: rec = '妙味有'
    elif mk >= 2: rec = '妙味有' if fav_low else '要検討'
    else: rec = '妙味薄'
    s_rank = 'S/A(≥50)' if score >= 50 else 'B以下(<50)'
    key = f'{rec} × {s_rank}'
    if key not in combos: combos[key] = []
    combos[key].append(act1)

for key, acts in sorted(combos.items()):
    n  = len(acts)
    w  = sum(1 for a in acts if a==1)
    t3 = sum(1 for a in acts if a<=3)
    print(f'  {key:22s}: {n:2d}R  勝率={w/n*100:.0f}%  複勝率={t3/n*100:.0f}%')
