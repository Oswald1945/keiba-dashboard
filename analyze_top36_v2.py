# -*- coding: utf-8 -*-
"""horses_data JSON + review HTML をマッチして top-3 vs top-6 比較"""
import re, json, glob, pathlib

BASE = pathlib.Path('/sessions/adoring-focused-galileo/mnt/keiba-dashboard')

def parse_review_html(fp):
    txt = pathlib.Path(fp).read_text(encoding='utf-8', errors='ignore')
    m = re.search(r'const DATA = (\[.*?\]);', txt)
    if not m: return None
    try: return json.loads(m.group(1))
    except: return None

def kairido(h):
    src = h.get('SmartRC推定人気順')
    if src is None: return None
    try: return int(src) - h.get('順位予想', 99)
    except: return None

# horses_data JSONと対応するreviewをマッチ
# JSON: horses_data_20260523_kt11.json → review: 20260523_KY11R_..._review.html
# 日付+開催場コードで対応づけ
venue_map = {'kt':'KY','kt':'KY','ng':'NG','tk':'TK','hs':'HS','fs':'FS','ck':'CK','nk':'NK','hn':'HN'}

json_files = sorted(glob.glob(str(BASE / 'horses_data_*.json')))

records = []
for jp in json_files:
    jname = pathlib.Path(jp).stem  # horses_data_20260523_kt11
    parts = jname.replace('horses_data_','').split('_')  # ['20260523','kt11']
    if len(parts) < 2: continue
    date_str = parts[0]       # 20260523
    venue_r  = parts[1]       # kt11
    venue_code = re.match(r'[a-z]+', venue_r)
    r_num      = re.search(r'\d+', venue_r)
    if not venue_code or not r_num: continue
    vc = venue_code.group().upper()
    rn = r_num.group()

    # 対応するreview HTMLを探す
    pattern = str(BASE / f'{date_str}_{vc}{rn}R_*_review.html')
    matches = glob.glob(pattern)
    if not matches:
        # KY/kt のマッピング揺れ対応
        alt = {'KT':'KY','KY':'KT'}.get(vc, vc)
        pattern2 = str(BASE / f'{date_str}_{alt}{rn}R_*_review.html')
        matches = glob.glob(pattern2)
    if not matches: continue

    rev_data = parse_review_html(matches[0])
    if not rev_data: continue

    with open(jp) as f:
        jdata = json.load(f)
    horses = jdata.get('horses', [])
    if not horses: continue

    # review_data から実際着順を取得（馬名で紐付け）
    act_map = {h['馬名']: h.get('入線順位', 99) for h in rev_data}
    winner_pop = next((h.get('人気',99) for h in rev_data if h.get('入線順位')==1), 99)

    records.append({
        'race': jname,
        'horses': horses,
        'act_map': act_map,
        'winner_pop': winner_pop,
        'n': len(horses),
    })

print(f'マッチ成功: {len(records)}レース\n')

def classify(horses, act_map, top_n, use_fav_condition=True):
    sorted_pred = sorted(horses, key=lambda h: h.get('順位予想', 99))
    top_n_horses = sorted_pred[:top_n]

    ks = [k for h in top_n_horses for k in [kairido(h)] if k is not None]
    mk = max(ks, default=0)

    # 1番人気スコア順位
    fav_rank = next((h.get('順位予想',99) for h in horses if h.get('人気')==1), 99)
    n = len(horses)
    thr = n // 2 if n <= 12 else 7
    fav_is_low = fav_rank > thr

    if mk >= 4:
        return '妙味有', mk, fav_rank
    elif mk >= 2:
        if use_fav_condition and fav_is_low:
            return '妙味有', mk, fav_rank
        return '要検討', mk, fav_rank
    else:
        return '妙味薄', mk, fav_rank

print('=' * 65)
for top_n in [3, 6]:
    cats = {'妙味有': [], '要検討': [], '妙味薄': []}
    for r in records:
        horses   = r['horses']
        act_map  = r['act_map']
        n        = r['n']

        cat, mk, fav_rank = classify(horses, act_map, top_n)

        pred1 = min(horses, key=lambda h: h.get('順位予想', 99))
        act1  = act_map.get(pred1['馬名'], 99)
        top_n_names = {h['馬名'] for h in sorted(horses, key=lambda h: h.get('順位予想',99))[:top_n]}
        winner_name = next((name for name,a in act_map.items() if a==1), None)
        hit = winner_name in top_n_names if winner_name else False

        cats[cat].append({'act1': act1, 'hit': hit, 'n': n, 'mk': mk,
                          'fav_rank': fav_rank, 'winner_pop': r['winner_pop']})

    print(f'── top-{top_n}頭 + 1番人気条件あり ──')
    total = sum(len(v) for v in cats.values())
    for cat in ['妙味有', '要検討', '妙味薄']:
        lst = cats[cat]
        if not lst:
            print(f'  {cat:6s}: 0レース')
            continue
        nr   = len(lst)
        win1 = sum(1 for x in lst if x['act1'] == 1)
        top3 = sum(1 for x in lst if x['act1'] <= 3)
        hitr = sum(1 for x in lst if x['hit'])
        avg_mk = sum(x['mk'] for x in lst) / nr
        print(f'  {cat:6s} ({nr:2d}R / {nr/total*100:.0f}%): '
              f'スコア1位勝率={win1/nr*100:.0f}%  複勝率={top3/nr*100:.0f}%  '
              f'top-{top_n}に1着={hitr/nr*100:.0f}%  平均乖離={avg_mk:.1f}')
    print()

# ── 条件なし（乖離のみ）との比較 ──────────────────────────────
print('=' * 65)
print('── top-3 / 乖離のみ（1番人気条件なし）vs 条件あり ──')
for use_fav in [False, True]:
    label = '1番人気条件あり' if use_fav else '乖離のみ    '
    cats = {'妙味有':0,'要検討':0,'妙味薄':0}
    for r in records:
        cat,_,_ = classify(r['horses'], r['act_map'], 3, use_fav)
        cats[cat] += 1
    total = sum(cats.values())
    print(f'  {label}: 妙味有={cats["妙味有"]}R  要検討={cats["要検討"]}R  妙味薄={cats["妙味薄"]}R')
