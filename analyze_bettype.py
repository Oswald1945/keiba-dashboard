# -*- coding: utf-8 -*-
"""
analyze_bettype.py — 6/20,6/21 の予想(pred HTMLのEV_DATA)とレース結果(確定配当)を突き合わせ、
ダッシュボードのbet-panelロジックをPython移植して「モデルの買い目」を再構築し、
券種別・判定別に的中率/ROIを集計する。
"""
import re, json, glob, math, os, sys, itertools
import result_loader as RL

SD = os.path.dirname(os.path.abspath(__file__))
T = 20.0

# ---------- EV_DATA 抽出 ----------
def load_evdata(pred_path):
    h = open(pred_path, encoding='utf-8').read()
    m = re.search(r'EV_DATA\s*=\s*(\[.*?\]);\s*\n', h, re.S)
    if not m: return None
    return json.loads(m.group(1))

# ---------- 確率計算(JS移植) ----------
def softmax_winprobs(ev):
    scores = [h['スコア'] for h in ev]
    mx = max(scores)
    exps = [math.exp((s-mx)/T) for s in scores]
    sm = sum(exps)
    probs = [e/sm for e in exps]
    MR = 3.0
    capped = []
    for p, h in zip(probs, ev):
        o = h.get('オッズ')
        if not o or o <= 0: capped.append(p)
        else: capped.append(min(p, (1/o)*MR))
    s2 = sum(capped)
    return [p/s2 for p in capped]

def placeProb(probs, idx, k):
    pi = probs[idx]; n = len(probs)
    if k <= 1: return pi
    p2 = 0.0
    for j in range(n):
        if j == idx: continue
        p2 += probs[j]*pi/max(1e-9, 1-probs[j])
    if k <= 2: return min(1, pi+p2)
    p3 = 0.0
    for j in range(n):
        if j == idx: continue
        for mm in range(n):
            if mm == idx or mm == j: continue
            d = 1-probs[j]-probs[mm]
            if d <= 0: continue
            p3 += probs[j]*(probs[mm]/max(1e-9,1-probs[j]))*(pi/d)
    return min(1, pi+p2+p3)

def _num(x, default):
    if x is None: return default
    try:
        v = float(x)
        return v
    except: return default

# ---------- bet-panel ロジック移植 ----------
def reconstruct(ev):
    wp = softmax_winprobs(ev)
    mean = sum(h['スコア'] for h in ev)/len(ev)
    sd = math.sqrt(sum((h['スコア']-mean)**2 for h in ev)/len(ev)) or 1
    arr = []
    for i, h in enumerate(ev):
        p = wp[i]
        if p > 0 and h.get('馬番') is not None:
            arr.append(dict(name=h['馬名'], uma=h['馬番'], idx=i, p=p,
                            rank=h['順位予想'], src=h.get('SmartRC推定人気順'),
                            dev=50+10*(h['スコア']-mean)/sd))
    arr.sort(key=lambda x: -x['p']); arr = arr[:8]
    if len(arr) < 2: return None
    names = [x['name'] for x in arr]
    pv = {x['name']: x['p'] for x in arr}
    um = {x['name']: x['uma'] for x in arr}
    dv = {x['name']: x['dev'] for x in arr}
    sc = {x['name']: x['src'] for x in arr}
    gi = {x['name']: x['idx'] for x in arr}
    # o3: 上位3着順列確率(Harville)
    o3 = {}
    for seq in itertools.permutations(names, 3):
        rem = 1.0; pr = 1.0
        ok = True
        for nm in seq:
            if rem <= 1e-9: pr = 0; break
            pr *= pv[nm]/rem; rem -= pv[nm]
        o3['|'.join(seq)] = pr
    W = lambda n: pv[n]
    P2 = lambda n: placeProb(wp, gi[n], 2)
    P3 = lambda n: placeProb(wp, gi[n], 3)
    A = arr[0]['name']; wA = pv[A]
    srcA = float(sc[A]) if sc[A] is not None else 99
    # 相手選定
    cand = [n for n in names if n != A]
    cand.sort(key=lambda n: -pv[n])
    partners = []; cum = wA
    for n in cand:
        s2 = _num(sc[n], 99)
        live = (dv[n] >= 48) or (s2 <= 4) or (P2(n) >= 0.30)
        noHope = (dv[n] < 42) and (s2 > 6) and (P3(n) < 0.18)
        if noHope: continue
        if len(partners) >= 2 and cum >= 0.82 and not (s2 <= 2): break
        if live or len(partners) < 2:
            partners.append(n); cum += pv[n]
        if len(partners) >= 6: break
    if len(partners) < 1: partners = cand[:2]
    contend = [A]+partners
    # 判定
    def _mktWin(ep):
        return {1:.31,2:.18,3:.15,4:.12,5:.08,6:.05}.get(min(int(ep),7), .03)
    _srcA = srcA if srcA < 99 else 99
    _fav1Rank = 99; _anaH = None
    for h in ev:
        ep = _num(h.get('SmartRC推定人気順'), 0)
        pr = _num(h.get('順位予想'), 0)
        if ep == 1: _fav1Rank = pr
        if ep >= 5 and pr <= 3 and _anaH is None and pr > 0:
            _anaH = dict(uma=h['馬番'], ep=ep)
    _ana = _anaH is not None
    miyomi = False; boxMode = False
    if _srcA >= 4:
        verdict = '中穴軸'
    elif (_srcA == 2 or _srcA == 3) and (_fav1Rank >= 4 or _ana):
        miyomi = True; verdict = '買い妙味'
    elif wA < 0.18:
        boxMode = True; verdict = '混戦BOX'
    else:
        verdict = '見送り'
    # 妙味精製
    cutHorse = None
    if miyomi:
        topPop = [n for n in partners if sc[n] is not None and _num(sc[n],99) <= 3]
        hasAna = any(sc[n] is not None and _num(sc[n],99) >= 5 for n in partners)
        if topPop:
            cutHorse = min(topPop, key=lambda n: pv[n])
            partners = [n for n in partners if n != cutHorse]
            contend = [A]+partners
        elif not hasAna:
            miyomi = False; verdict = '見送り(妙味組めず)'
    # 列取捨
    col1 = [n for n in contend if n == A or W(n) >= 0.6*wA]
    col1.sort(key=lambda n: -W(n)); col1 = col1[:3]
    headFix = (len(col1) == 1)
    ex = (lambda n: n != A) if headFix else (lambda n: True)
    col2 = [n for n in contend if ex(n) and P2(n) >= 0.18]
    col2.sort(key=lambda n: -P2(n))
    if len(col2) < 2:
        col2 = sorted([n for n in contend if ex(n)], key=lambda n: -P2(n))[:2]
    col2 = col2[:5]
    col3 = sorted([n for n in contend if ex(n)], key=lambda n: -P3(n))
    return dict(A=A, umA=um[A], wA=wA, srcA=srcA, verdict=verdict, miyomi=miyomi,
                boxMode=boxMode, partners=partners, contend=contend,
                col1=col1, col2=col2, col3=col3, um=um, pv=pv, names=names,
                P3=P3(A))

# ---------- 結果突き合わせ ----------
def to_int(x):
    try: return int(float(x))
    except: return None

def parse_combo(s):
    return [to_int(p) for p in str(s).replace('=', '-').split('-')]

def eval_race(rec, res_df, payouts):
    um = rec['um']
    # 着順→馬番
    order = []
    df = res_df.copy()
    df = df[[c for c in ['入線順位','馬番'] if c in df.columns]].dropna()
    df['_o'] = df['入線順位'].apply(to_int)
    df['_u'] = df['馬番'].apply(to_int)
    df = df.dropna(subset=['_o','_u']).sort_values('_o')
    order = [int(u) for u in df['_u'].tolist()]
    if len(order) < 3: return None
    top1, top2, top3 = order[0], order[1], order[2]
    top2set = {top1, top2}; top3set = {top1, top2, top3}

    def pay(key, combo_target_fn):
        for combo, amt in payouts.get(key, []):
            nums = parse_combo(combo)
            if combo_target_fn(nums): return amt
        return None
    tansho = {to_int(c): a for c, a in payouts.get('tansho', [])}
    fuku = {to_int(c): a for c, a in payouts.get('fukusho', [])}

    bets = {}  # bettype -> (points, return_yen)
    umA = rec['umA']
    A = rec['A']
    col1u = [um[n] for n in rec['col1']]
    col2u = [um[n] for n in rec['col2']]
    col3u = [um[n] for n in rec['col3']]

    if rec['boxMode']:
        bx = rec['names'][:min(4, len(rec['names']))]
        bxu = sorted(um[n] for n in bx)
        # 複勝BOX(各1点)
        pts = len(bxu); ret = sum(fuku.get(u, 0) for u in bxu)
        bets['複勝BOX'] = (pts, ret)
        # ワイドBOX
        pairs = list(itertools.combinations(bxu, 2))
        ret = 0
        for c in pairs:
            cs = set(c)
            for combo, amt in payouts.get('wide', []):
                if set(parse_combo(combo)) == cs: ret += amt
        bets['ワイドBOX'] = (len(pairs), ret)
        # 馬連BOX
        ret = 0
        for c in pairs:
            cs = set(c)
            a = pay('umaren', lambda nums: set(nums) == cs)
            if a: ret += a
        bets['馬連BOX'] = (len(pairs), ret)
        # 三連複BOX
        tri = list(itertools.combinations(bxu, 3))
        ret = 0
        for c in tri:
            cs = set(c)
            a = pay('sanrenpuku', lambda nums: set(nums) == cs)
            if a: ret += a
        bets['三連複BOX'] = (len(tri), ret)
        return dict(order=order, bets=bets, box=True, axis_uma=umA,
                    axis_fin=order.index(umA)+1 if umA in order else None)

    uren = [um[n] for n in rec['col2'] if n != A]
    wd = [um[n] for n in rec['col3'] if n != A]
    # 単勝
    bets['単勝'] = (1, tansho.get(umA, 0) if umA == top1 else 0)
    # 複勝
    bets['複勝'] = (1, fuku.get(umA, 0))
    # 馬連 A-uren
    ret = 0
    for o in uren:
        cs = {umA, o}
        a = pay('umaren', lambda nums: set(nums) == cs)
        if a: ret += a
    bets['馬連'] = (len(uren), ret)
    # ワイド A-wd
    ret = 0
    for o in wd:
        cs = {umA, o}
        for combo, amt in payouts.get('wide', []):
            if set(parse_combo(combo)) == cs: ret += amt
    bets['ワイド'] = (len(wd), ret)
    # 馬単 col1->col2
    pts = 0; ret = 0
    for i in col1u:
        for j in col2u:
            if i != j:
                pts += 1
                a = pay('umatan', lambda nums: nums[0] == i and nums[1] == j)
                if a: ret += a
    bets['馬単'] = (pts, ret)
    # 三連複 軸-wd2
    tri = list(itertools.combinations(wd, 2))
    ret = 0
    for c in tri:
        cs = {umA, c[0], c[1]}
        a = pay('sanrenpuku', lambda nums: set(nums) == cs)
        if a: ret += a
    bets['三連複'] = (len(tri), ret)
    # 三連単 col1->col2->col3
    pts = 0; ret = 0
    for i in col1u:
        for j in col2u:
            for k in col3u:
                if i != j and j != k and i != k:
                    pts += 1
                    a = pay('sanrentan', lambda nums: nums == [i, j, k])
                    if a: ret += a
    bets['三連単'] = (pts, ret)
    return dict(order=order, bets=bets, box=False, axis_uma=umA,
                axis_fin=order.index(umA)+1 if umA in order else None)


def main():
    preds = sorted(glob.glob(os.path.join(SD, 'pred_2026062[01]_*.html')))
    rows = []
    for pp in preds:
        rid = re.search(r'pred_(\d{8}_[a-z]+\d+)\.html', pp).group(1)
        res_path = os.path.join(SD, 'input', 'done', f'レース結果_{rid}.html')
        if not os.path.exists(res_path):
            print('NO RESULT', rid); continue
        ev = load_evdata(pp)
        rec = reconstruct(ev)
        if rec is None:
            print('REC FAIL', rid); continue
        res_df, meta, payouts = RL.load_result(res_path)
        ev_eval = eval_race(rec, res_df, payouts)
        if ev_eval is None:
            print('EVAL FAIL', rid); continue
        rows.append(dict(rid=rid, meta=dict(meta), rec=rec, ev=ev_eval))
    json.dump_default = str
    # 保存(後段集計用)
    out = []
    for r in rows:
        out.append(dict(rid=r['rid'],
                        venue=r['meta'].get('場所',''), R=r['meta'].get('R',''),
                        rname=r['meta'].get('レース名',''),
                        verdict=r['rec']['verdict'], miyomi=r['rec']['miyomi'],
                        box=r['ev']['box'], axis_uma=r['rec']['umA'],
                        srcA=r['rec']['srcA'], wA=round(r['rec']['wA'],3),
                        axis_fin=r['ev']['axis_fin'],
                        order=r['ev']['order'],
                        bets={k:[v[0],v[1]] for k,v in r['ev']['bets'].items()}))
    json.dump(out, open(os.path.join(SD,'bettype_eval.json'),'w'), ensure_ascii=False, indent=1, default=str)
    print(f'\n集計対象 {len(out)}R -> bettype_eval.json')

if __name__ == '__main__':
    main()
