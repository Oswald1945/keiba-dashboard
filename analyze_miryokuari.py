# -*- coding: utf-8 -*-
import re, json, glob, pathlib

BASE = pathlib.Path('/sessions/adoring-focused-galileo/mnt/keiba-dashboard')

def parse_review(fp):
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

def classify_race(horses):
    """現行ロジックで推奨度を分類"""
    rc_top3 = sorted(
        [h for h in horses if not h.get('過去走なし', False)],
        key=lambda h: h.get('順位予想', 99)
    )[:3]
    candidates = []
    for h in rc_top3:
        k = kairido(h)
        if k is not None:
            candidates.append({'馬名': h['馬名'], '乖離': k,
                                '予想順位': h.get('順位予想', 99),
                                'SmartRC推定': int(h.get('SmartRC推定人気順', 99)),
                                'オッズ': h.get('単勝オッズ')})

    max_k = max((c['乖離'] for c in candidates), default=0)
    best  = max(candidates, key=lambda x: x['乖離']) if candidates else None

    # 1番人気スコア順位
    n = len(horses)
    fav_rank = next((h.get('順位予想', 99) for h in horses if h.get('人気') == 1), 99)
    thr = n // 2 if n <= 12 else 7
    fav_is_low = fav_rank > thr

    if max_k >= 4:
        rec = '妙味有'
    elif max_k >= 2:
        rec = '妙味有' if fav_is_low else '要検討'
    else:
        rec = '妙味薄'

    # 自信あり判定
    sorted_v = sorted([h for h in horses if not h.get('過去走なし')],
                      key=lambda h: h.get('順位予想', 99))
    pred1 = sorted_v[0] if sorted_v else None
    pred2 = sorted_v[1] if len(sorted_v) > 1 else None
    pred1_dev   = 0
    score_lead  = 0
    if pred1:
        scores = [h.get('総合スコア', 0) for h in horses]
        mu = sum(scores)/len(scores); sig = (sum((s-mu)**2 for s in scores)/len(scores))**0.5 or 1
        pred1_dev  = round((pred1.get('総合スコア', 0) - mu) / sig * 10 + 50)
        score_lead = pred1.get('総合スコア', 0) - (pred2.get('総合スコア', 0) if pred2 else 0)
        pred1_smartrc = int(pred1.get('SmartRC推定人気順') or 99)
        pred1_is_fav  = (pred1_smartrc == 1)
    else:
        pred1_is_fav = False
    jishin = ((pred1_dev >= 65 or score_lead >= 15) and not pred1_is_fav and rec == '妙味有')

    return rec, jishin, max_k, best, pred1

# JSONとreviewをマッチ
json_files = sorted(glob.glob(str(BASE / 'horses_data_*.json')))
records = []
for jp in json_files:
    jname = pathlib.Path(jp).stem
    parts = jname.replace('horses_data_','').split('_')
    if len(parts) < 2: continue
    date_str, venue_r = parts[0], parts[1]
    vc = re.match(r'[a-z]+', venue_r)
    rn = re.search(r'\d+', venue_r)
    if not vc or not rn: continue
    vc2, rn2 = vc.group().upper(), rn.group()
    matches = []
    for alt in [vc2, {'KT':'KY','KY':'KT'}.get(vc2, vc2)]:
        matches += glob.glob(str(BASE / f'{date_str}_{alt}{rn2}R_*_review.html'))
    if not matches: continue
    rev = parse_review(matches[0])
    if not rev: continue
    with open(jp) as f: jdata = json.load(f)
    horses = jdata.get('horses', [])
    if not horses: continue
    act_map = {h['馬名']: h.get('入線順位', 99) for h in rev}
    winner  = next((h for h in rev if h.get('入線順位') == 1), None)
    records.append({'horses': horses, 'act_map': act_map,
                    'winner': winner, 'race': jname})

print(f'分析対象: {len(records)}レース\n')

# ── カテゴリ別成績 ────────────────────────────────────────────
cats = {'妙味有（自信あり）': [], '妙味有（通常）': [], '要検討': [], '妙味薄': []}

for r in records:
    horses  = r['horses']
    act_map = r['act_map']
    rec, jishin, max_k, best, pred1 = classify_race(horses)

    if rec == '妙味有':
        cat = '妙味有（自信あり）' if jishin else '妙味有（通常）'
    else:
        cat = rec

    pred1_act = act_map.get(pred1['馬名'], 99) if pred1 else 99
    top3_names = {h['馬名'] for h in sorted(horses, key=lambda h: h.get('順位予想',99))[:3]}
    winner_name = r['winner']['馬名'] if r['winner'] else None
    hit3 = winner_name in top3_names if winner_name else False
    winner_pop  = r['winner'].get('人気', 99) if r['winner'] else 99

    # 注目馬（乖離が最大の馬）の成績
    best_act = act_map.get(best['馬名'], 99) if best else 99
    best_odds = best.get('オッズ') if best else None

    cats[cat].append({
        'pred1_act': pred1_act, 'hit3': hit3,
        'winner_pop': winner_pop, 'race': r['race'],
        'best_act': best_act, 'best_odds': best_odds,
        'best': best,
    })

print('=' * 65)
print('【カテゴリ別 スコア1位の成績】')
total = sum(len(v) for v in cats.values())
for cat in ['妙味有（自信あり）','妙味有（通常）','要検討','妙味薄']:
    lst = cats[cat]
    if not lst:
        print(f'  {cat}: 0レース')
        continue
    n   = len(lst)
    w1  = sum(1 for x in lst if x['pred1_act'] == 1)
    t2  = sum(1 for x in lst if x['pred1_act'] <= 2)
    t3  = sum(1 for x in lst if x['pred1_act'] <= 3)
    h3  = sum(1 for x in lst if x['hit3'])
    print(f'  {cat} ({n}R):  勝率={w1/n*100:.0f}%  連対率={t2/n*100:.0f}%  複勝率={t3/n*100:.0f}%  上位3頭に1着={h3/n*100:.0f}%')

print()
print('【注目馬（乖離最大馬）の成績】')
for cat in ['妙味有（自信あり）','妙味有（通常）','要検討']:
    lst = [x for x in cats[cat] if x['best'] and x['best_act'] < 90]
    if not lst: continue
    n   = len(lst)
    w1  = sum(1 for x in lst if x['best_act'] == 1)
    t3  = sum(1 for x in lst if x['best_act'] <= 3)
    print(f'  {cat} ({n}R):  注目馬勝率={w1/n*100:.0f}%  注目馬複勝率={t3/n*100:.0f}%')

print()
print('【妙味有レースの1着馬人気分布】')
miryoku = cats['妙味有（自信あり）'] + cats['妙味有（通常）']
pop_dist = {}
for x in miryoku:
    p = x['winner_pop']
    k = f'{p}番人気' if p <= 5 else '6番人気以上'
    pop_dist[k] = pop_dist.get(k, 0) + 1
for k in ['1番人気','2番人気','3番人気','4番人気','5番人気','6番人気以上']:
    c = pop_dist.get(k, 0)
    print(f'  {k}: {"█"*c} {c}回')

print()
print('【妙味有（自信あり）レース詳細】')
for x in cats['妙味有（自信あり）']:
    b = x['best']
    odds_str = f'{b["オッズ"]:.1f}倍' if b and b.get('オッズ') else '-'
    print(f'  {x["race"]}  スコア1位:{x["pred1_act"]}着  '
          f'注目馬({b["馬名"] if b else "-"} 乖離+{b["乖離"] if b else "-"} {odds_str}):{x["best_act"]}着  '
          f'1着馬:{x["winner_pop"]}番人気')
