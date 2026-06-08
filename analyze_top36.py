# -*- coding: utf-8 -*-
"""top-3 vs top-6 判定の比較分析"""
import re, json, glob, pathlib

files = sorted(glob.glob('/sessions/adoring-focused-galileo/mnt/keiba-dashboard/*review*.html'))
races = []
for fp in files:
    txt = pathlib.Path(fp).read_text(encoding='utf-8', errors='ignore')
    m_data = re.search(r'const DATA = (\[.*?\]);', txt)
    if not m_data: continue
    try:
        data = json.loads(m_data.group(1))
        races.append(data)
    except: pass

print(f'対象: {len(races)}レース\n')

def kairido(h):
    src = h.get('SmartRC推定人気順') if hasattr(h,'get') else None
    if src is None: return None
    try: return int(src) - h.get('予想順位', 99)
    except: return None

def race_max_kairido(data, top_n):
    sorted_pred = sorted(data, key=lambda h: h.get('予想順位', 99))[:top_n]
    ks = [k for h in sorted_pred for k in [kairido(h)] if k is not None]
    return max(ks, default=0)

def fav1_score_rank(data):
    for h in data:
        if h.get('人気') == 1:
            return h.get('予想順位', 99)
    return 99

# ── 分類ごとの実際の成績 ──────────────────────────────────────
print('=' * 60)
print('【top-3 vs top-6 推奨レース分類の比較】')
print()

for top_n in [3, 6]:
    cats = {'妙味有': [], '要検討': [], '妙味薄': []}
    for data in races:
        mk = race_max_kairido(data, top_n)
        n  = len(data)
        fav_rank = fav1_score_rank(data)
        thr = n // 2 if n <= 12 else 7
        fav_is_low = fav_rank > thr

        # 判定
        if mk >= 4:
            cat = '妙味有'
        elif mk >= 2:
            cat = '妙味有' if fav_is_low else '要検討'
        else:
            cat = '妙味薄'

        # スコア1位の実際着順
        pred1 = min(data, key=lambda h: h.get('予想順位', 99))
        act1  = pred1.get('入線順位', 99)
        # top-N内に1着馬がいるか
        top_n_names = {h['馬名'] for h in sorted(data, key=lambda h: h.get('予想順位',99))[:top_n]}
        winner = next((h for h in data if h.get('入線順位') == 1), None)
        hit = winner and winner['馬名'] in top_n_names

        cats[cat].append({'act1': act1, 'hit': hit, 'n': n})

    print(f'  ── top-{top_n}頭で判定 ──')
    total = sum(len(v) for v in cats.values())
    for cat in ['妙味有', '要検討', '妙味薄']:
        lst = cats[cat]
        if not lst:
            print(f'  {cat}: 0レース')
            continue
        n_r   = len(lst)
        win1  = sum(1 for x in lst if x['act1'] == 1)
        top3  = sum(1 for x in lst if x['act1'] <= 3)
        hit_r = sum(1 for x in lst if x['hit'])
        print(f'  {cat} ({n_r}R / {n_r/total*100:.0f}%): '
              f'スコア1位勝率={win1/n_r*100:.0f}%  複勝率={top3/n_r*100:.0f}%  '
              f'top-{top_n}内に1着={hit_r/n_r*100:.0f}%')
    print()

# ── 乖離度2-3かつ1番人気低評価の追加分析 ──────────────────────
print('=' * 60)
print('【乖離2-3 + 1番人気低スコア = 妙味有 に昇格するレース数】')
print()
upgrade_count = 0
for data in races:
    mk3 = race_max_kairido(data, 3)
    n   = len(data)
    fav_rank = fav1_score_rank(data)
    thr = n // 2 if n <= 12 else 7
    if 2 <= mk3 <= 3 and fav_rank > thr:
        upgrade_count += 1
        pred1 = min(data, key=lambda h: h.get('予想順位', 99))
        winner = next((h for h in data if h.get('入線順位') == 1), None)
        w_pop  = winner.get('人気', '?') if winner else '?'
        print(f'  頭数{n:2d} | 1番人気スコア{fav_rank}位(閾値{thr}) | 乖離{mk3} | '
              f'1着={pred1.get("入線順位","?")}着 | 1着馬人気{w_pop}番人気')
print(f'\n  計 {upgrade_count}レースが「要検討→妙味有」に昇格')
