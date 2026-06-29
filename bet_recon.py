# -*- coding: utf-8 -*-
"""
bet_recon.py — pred HTMLのEV_DATAからダッシュボードbet-panelの買い目(軸/相手/列/判定)を
Pythonで再構築し、確定配当(payouts)と突き合わせて券種別の的中/回収を返す。
build_review から回顧の「券種別 結果照合」パネル生成に使う。
採算オッズは内訳(その買い目1点ごとの的中率の逆数)で算定し、的中馬券ごとに期待値を判定する。
"""
import re, json, math, os, itertools

T = 20.0


def load_evdata(pred_path):
    h = open(pred_path, encoding='utf-8').read()
    m = re.search(r'EV_DATA\s*=\s*(\[.*?\]);\s*\n', h, re.S)
    return json.loads(m.group(1)) if m else None


def find_pred_html(rid, outdir):
    for c in (os.path.join(outdir, f'{rid}_pred.html'),
              os.path.join(outdir, f'pred_{rid}.html')):
        if os.path.exists(c):
            return c
    return None


def _num(x, default):
    if x is None:
        return default
    try:
        return float(x)
    except Exception:
        return default


def _softmax_winprobs(ev):
    scores = [h['スコア'] for h in ev]
    mx = max(scores)
    exps = [math.exp((s - mx) / T) for s in scores]
    sm = sum(exps)
    probs = [e / sm for e in exps]
    MR = 3.0
    capped = []
    for p, h in zip(probs, ev):
        o = h.get('オッズ')
        capped.append(p if (not o or o <= 0) else min(p, (1 / o) * MR))
    s2 = sum(capped)
    return [p / s2 for p in capped]


def _placeProb(probs, idx, k):
    pi = probs[idx]
    n = len(probs)
    if k <= 1:
        return pi
    p2 = 0.0
    for j in range(n):
        if j == idx:
            continue
        p2 += probs[j] * pi / max(1e-9, 1 - probs[j])
    if k <= 2:
        return min(1, pi + p2)
    p3 = 0.0
    for j in range(n):
        if j == idx:
            continue
        for mm in range(n):
            if mm == idx or mm == j:
                continue
            d = 1 - probs[j] - probs[mm]
            if d <= 0:
                continue
            p3 += probs[j] * (probs[mm] / max(1e-9, 1 - probs[j])) * (pi / d)
    return min(1, pi + p2 + p3)


def reconstruct(ev):
    wp = _softmax_winprobs(ev)
    mean = sum(h['スコア'] for h in ev) / len(ev)
    sd = math.sqrt(sum((h['スコア'] - mean) ** 2 for h in ev) / len(ev)) or 1
    waku = {h['馬番']: int(h.get('枠番') or 0) for h in ev if h.get('馬番') is not None}
    arr = []
    for i, h in enumerate(ev):
        p = wp[i]
        if p > 0 and h.get('馬番') is not None:
            arr.append(dict(name=h['馬名'], uma=h['馬番'], idx=i, p=p,
                            rank=h['順位予想'], src=h.get('SmartRC推定人気順'),
                            dev=50 + 10 * (h['スコア'] - mean) / sd))
    arr.sort(key=lambda x: -x['p'])
    arr = arr[:8]
    if len(arr) < 2:
        return None
    names = [x['name'] for x in arr]
    pv = {x['name']: x['p'] for x in arr}
    um = {x['name']: x['uma'] for x in arr}
    dv = {x['name']: x['dev'] for x in arr}
    sc = {x['name']: x['src'] for x in arr}
    gi = {x['name']: x['idx'] for x in arr}
    W = lambda n: pv[n]
    P2 = lambda n: _placeProb(wp, gi[n], 2)
    P3 = lambda n: _placeProb(wp, gi[n], 3)
    A = arr[0]['name']
    wA = pv[A]
    srcA = float(sc[A]) if sc[A] is not None else 99
    cand = [n for n in names if n != A]
    cand.sort(key=lambda n: -pv[n])
    partners = []
    cum = wA
    for n in cand:
        s2 = _num(sc[n], 99)
        live = (dv[n] >= 48) or (s2 <= 4) or (P2(n) >= 0.30)
        noHope = (dv[n] < 42) and (s2 > 6) and (P3(n) < 0.18)
        if noHope:
            continue
        if len(partners) >= 2 and cum >= 0.82 and not (s2 <= 2):
            break
        if live or len(partners) < 2:
            partners.append(n)
            cum += pv[n]
        if len(partners) >= 6:
            break
    if len(partners) < 1:
        partners = cand[:2]
    contend = [A] + partners
    _srcA = srcA if srcA < 99 else 99
    _fav1Rank = 99
    _anaH = None
    for h in ev:
        ep = _num(h.get('SmartRC推定人気順'), 0)
        pr = _num(h.get('順位予想'), 0)
        if ep == 1:
            _fav1Rank = pr
        if ep >= 5 and pr <= 3 and _anaH is None and pr > 0:
            _anaH = dict(uma=h['馬番'], ep=ep)
    _ana = _anaH is not None
    # 偏差値ベースの混戦判定: 上位4頭が僅差(spread小) かつ 軸が2位に抜けていない(gapA小)＝1強不在
    _S_BOX = 4.0      # 軸-4位の偏差値差。これ以内＝上位4頭僅差
    _GAP_LEAD = 2.0   # 軸-2位の偏差値差。これ超＝軸が抜けた1強→混戦ではない(頭固定/見送り側)
    _dev4 = dv[arr[3]['name']] if len(arr) >= 4 else dv[arr[-1]['name']]
    spread = dv[A] - _dev4
    _gapA = dv[A] - dv[arr[1]['name']]
    miyomi = False
    boxMode = False
    if _srcA >= 4:
        verdict = '中穴軸'
    elif (_srcA == 2 or _srcA == 3) and (_fav1Rank >= 4 or _ana):
        miyomi = True
        verdict = '買い妙味'
    elif spread <= _S_BOX and _gapA <= _GAP_LEAD:
        boxMode = True
        verdict = '混戦BOX'
    else:
        verdict = '見送り'
    # 妙味精製: 偏差値で相手の切りを判断（明確に離れた相手は実力で切る／僅差混戦は過剰人気を割り切り／根拠弱ければ妙味組めず見送り）
    if miyomi:
        _D_CLEAR = 5.0   # 切る候補が残す最強相手より偏差値で5以上低い→実力差で切る
        _D_CLOSE = 2.0   # 相手間の偏差値レンジ≤2→僅差混戦→過剰人気を割り切り
        topPop = [n for n in partners if sc[n] is not None and _num(sc[n], 99) <= 3]
        hasAna = any(sc[n] is not None and _num(sc[n], 99) >= 5 for n in partners)
        if topPop:
            cand = min(topPop, key=lambda n: dv[n])   # 人気相手で偏差値最低=切る候補
            others = [n for n in partners if n != cand]
            bestOther = max((dv[n] for n in others), default=dv[A])
            rng = (max(dv[n] for n in partners) - min(dv[n] for n in partners)) if len(partners) >= 2 else 0.0
            if bestOther - dv[cand] >= _D_CLEAR:
                partners = [n for n in partners if n != cand]   # 実力差で切り
                contend = [A] + partners
            elif rng <= _D_CLOSE:
                overpop = min(topPop, key=lambda n: _num(sc[n], 99))   # 最人気の相手を割り切り
                partners = [n for n in partners if n != overpop]
                contend = [A] + partners
            else:
                miyomi = False                          # 切る根拠弱い→妙味組めず
                verdict = '見送り'
        elif not hasAna:
            miyomi = False
            verdict = '見送り'
    col1 = [n for n in contend if n == A or W(n) >= 0.6 * wA]
    col1.sort(key=lambda n: -W(n))
    col1 = col1[:3]
    headFix = (len(col1) == 1)
    ex = (lambda n: n != A) if headFix else (lambda n: True)
    col2 = [n for n in contend if ex(n) and P2(n) >= 0.18]
    col2.sort(key=lambda n: -P2(n))
    if len(col2) < 2:
        col2 = sorted([n for n in contend if ex(n)], key=lambda n: -P2(n))[:2]
    col2 = col2[:5]
    col3 = sorted([n for n in contend if ex(n)], key=lambda n: -P3(n))
    # 予想ダッシュボードと同じく、各列は最終的に馬番(若い順)で表示・組成する
    col1 = sorted(col1, key=lambda n: um[n])
    col2 = sorted(col2, key=lambda n: um[n])
    col3 = sorted(col3, key=lambda n: um[n])
    # 内訳採算オッズ算定用: 馬番キーの単勝確率・複勝確率・3着順列確率(Harville)
    o3 = {}
    for seq in itertools.permutations(names, 3):
        rem = 1.0; pr = 1.0
        for nm in seq:
            if rem <= 1e-9:
                pr = 0; break
            pr *= pv[nm] / rem; rem -= pv[nm]
        o3[seq] = pr
    pv_uma = {um[n]: pv[n] for n in names}
    p3_uma = {um[n]: _placeProb(wp, gi[n], 3) for n in names}
    o3_uma = {tuple(um[n] for n in seq): v for seq, v in o3.items()}
    return dict(A=A, umA=um[A], wA=wA, srcA=srcA, verdict=verdict, miyomi=miyomi,
                boxMode=boxMode, col1=col1, col2=col2, col3=col3, um=um,
                names=names, waku=waku, pv_uma=pv_uma, p3_uma=p3_uma, o3_uma=o3_uma)


def _combo_prob(bt, combo, pv_uma, o3_uma, p3_uma):
    """その買い目1点(combo=馬番リスト)の的中率を内訳ロジックで返す。"""
    base = bt[:-3] if bt.endswith('BOX') else bt
    if base == '単勝':
        return pv_uma.get(combo[0], 0)
    if base == '複勝':
        return p3_uma.get(combo[0], 0)
    if base == '馬連':
        x, y = combo[0], combo[1]
        return pv_uma[x] * pv_uma[y] / max(1e-9, 1 - pv_uma[x]) + pv_uma[y] * pv_uma[x] / max(1e-9, 1 - pv_uma[y])
    if base == 'ワイド':
        x, y = combo[0], combo[1]
        s = 0
        for key, v in o3_uma.items():
            if x in key and y in key:
                s += v
        return s
    if base == '馬単':
        i, j = combo[0], combo[1]
        return pv_uma[i] * pv_uma[j] / max(1e-9, 1 - pv_uma[i])
    if base == '三連複':
        s = 0
        for seq in itertools.permutations(combo, 3):
            s += o3_uma.get(seq, 0)
        return s
    if base == '三連単':
        return o3_uma.get(tuple(combo), 0)
    return 0


def _to_int(x):
    try:
        return int(float(x))
    except Exception:
        return None


def _parse_combo(s):
    return [_to_int(p) for p in str(s).replace('=', '-').split('-')]


def eval_race(rec, res_df, payouts):
    """各券種について (点数, 払戻合計, [(的中組番, 配当), ...]) を返す。"""
    um = rec['um']
    df = res_df[[c for c in ['入線順位', '馬番'] if c in res_df.columns]].dropna().copy()
    df['_o'] = df['入線順位'].apply(_to_int)
    df['_u'] = df['馬番'].apply(_to_int)
    df = df.dropna(subset=['_o', '_u']).sort_values('_o')
    order = [int(u) for u in df['_u'].tolist()]
    if len(order) < 3:
        return None
    tansho = {_to_int(c): a for c, a in payouts.get('tansho', [])}
    fuku = {_to_int(c): a for c, a in payouts.get('fukusho', [])}
    umaren = [(set(_parse_combo(c)), a) for c, a in payouts.get('umaren', [])]
    wide = [(set(_parse_combo(c)), a) for c, a in payouts.get('wide', [])]
    umatan = [(_parse_combo(c), a) for c, a in payouts.get('umatan', [])]
    s3p = [(set(_parse_combo(c)), a) for c, a in payouts.get('sanrenpuku', [])]
    s3t = [(_parse_combo(c), a) for c, a in payouts.get('sanrentan', [])]
    umA = rec['umA']
    A = rec['A']
    top1 = order[0]
    bets = {}
    if rec['boxMode']:
        bx = rec['names'][:min(4, len(rec['names']))]
        bxu = sorted(um[n] for n in bx)
        hits = [([u], fuku[u]) for u in bxu if u in fuku]
        bets['複勝BOX'] = (len(bxu), sum(p for _, p in hits), hits)
        pairs = list(itertools.combinations(bxu, 2))
        hits = []; ret = 0
        for c in pairs:
            for cs, a in wide:
                if cs == set(c):
                    hits.append((sorted(c), a)); ret += a
        bets['ワイドBOX'] = (len(pairs), ret, hits)
        hits = []; ret = 0
        for c in pairs:
            for cs, a in umaren:
                if cs == set(c):
                    hits.append((sorted(c), a)); ret += a
        bets['馬連BOX'] = (len(pairs), ret, hits)
        tri = list(itertools.combinations(bxu, 3))
        hits = []; ret = 0
        for c in tri:
            for cs, a in s3p:
                if cs == set(c):
                    hits.append((sorted(c), a)); ret += a
        bets['三連複BOX'] = (len(tri), ret, hits)
        return dict(order=order, bets=bets, box=True, axis_uma=umA,
                    axis_fin=order.index(umA) + 1 if umA in order else None)

    col1u = [um[n] for n in rec['col1']]
    col2u = [um[n] for n in rec['col2']]
    col3u = [um[n] for n in rec['col3']]
    uren = [um[n] for n in rec['col2'] if n != A]
    wd = [um[n] for n in rec['col3'] if n != A]
    # 単勝
    if umA == top1:
        bets['単勝'] = (1, tansho.get(umA, 0), [([umA], tansho.get(umA, 0))])
    else:
        bets['単勝'] = (1, 0, [])
    # 複勝
    if umA in fuku:
        bets['複勝'] = (1, fuku[umA], [([umA], fuku[umA])])
    else:
        bets['複勝'] = (1, 0, [])
    # 馬連
    hits = []; ret = 0
    for o in uren:
        for cs, a in umaren:
            if cs == {umA, o}:
                hits.append((sorted([umA, o]), a)); ret += a
    bets['馬連'] = (len(uren), ret, hits)
    # ワイド
    hits = []; ret = 0
    for o in wd:
        for cs, a in wide:
            if cs == {umA, o}:
                hits.append((sorted([umA, o]), a)); ret += a
    bets['ワイド'] = (len(wd), ret, hits)
    # 馬単 col1->col2
    pts = 0; ret = 0; hits = []
    for i in col1u:
        for j in col2u:
            if i != j:
                pts += 1
                for combo, a in umatan:
                    if combo == [i, j]:
                        hits.append(([i, j], a)); ret += a
    bets['馬単'] = (pts, ret, hits)
    # 三連複 軸-相手2頭
    hits = []; ret = 0
    for c in itertools.combinations(wd, 2):
        for cs, a in s3p:
            if cs == {umA, c[0], c[1]}:
                hits.append((sorted([umA, c[0], c[1]]), a)); ret += a
    bets['三連複'] = (len(list(itertools.combinations(wd, 2))), ret, hits)
    # 三連単 col1->col2->col3
    pts = 0; ret = 0; hits = []
    for i in col1u:
        for j in col2u:
            for k in col3u:
                if i != j and j != k and i != k:
                    pts += 1
                    for combo, a in s3t:
                        if combo == [i, j, k]:
                            hits.append(([i, j, k], a)); ret += a
    bets['三連単'] = (pts, ret, hits)
    return dict(order=order, bets=bets, box=False, axis_uma=umA,
                axis_fin=order.index(umA) + 1 if umA in order else None)


_VERDICT_STYLE = {
    '買い妙味': ('#27ae60', '#1a3a28', '#5DCAA5'),
    '中穴軸': ('#f1c40f', '#3a2e10', '#f1c40f'),
    '混戦BOX': ('#f1c40f', '#3a2e10', '#f1c40f'),
    '見送り': ('#e74c3c', '#3a1a1a', '#F09595'),
}
_WAKU_BG = {1: '#f4f4f4', 2: '#2b2b2b', 3: '#d63a3a', 4: '#3a66d6',
            5: '#f5d300', 6: '#2b9b46', 7: '#f08a24', 8: '#f2a0c0'}
_WAKU_FG = {1: '#000', 2: '#fff', 3: '#fff', 4: '#fff',
            5: '#000', 6: '#fff', 7: '#000', 8: '#000'}


def _chip(u, waku):
    w = int(waku.get(u, 0) or 0)
    bg = _WAKU_BG.get(w, '#5a6776')
    fg = _WAKU_FG.get(w, '#fff')
    return (f'<span style="display:inline-flex;align-items:center;justify-content:center;'
            f'width:20px;height:20px;border-radius:50%;background:{bg};color:{fg};'
            f'font-weight:700;font-size:11px;margin:1px;box-shadow:0 0 0 1px rgba(255,255,255,0.15)">{u}</span>')


def _sep_html(sep):
    if sep == '-':
        return '<span style="margin:0 3px;color:#9ab">-</span>'
    if sep == '→':
        return '<span style="margin:0 3px;color:#9ab">&rarr;</span>'
    return ''


def _cols_html(cols, sep, waku):
    parts = []
    for col in cols:
        parts.append('<span style="display:inline-flex;flex-wrap:wrap;align-items:center">'
                     + ''.join(_chip(u, waku) for u in col) + '</span>')
    return ('<span style="display:flex;justify-content:flex-start;align-items:center;flex-wrap:wrap">'
            + _sep_html(sep).join(parts) + '</span>')


def _combo_chips(combo, sep, waku):
    return _sep_html(sep).join(_chip(u, waku) for u in combo)


def _stack(entries, justify):
    """的中馬券ごとのサブ行を縦に積む(各行 高さ揃え)。"""
    if not entries:
        entries = ['<span style="color:#7a8694">&mdash;</span>']
    return ''.join(
        f'<div style="min-height:26px;display:flex;align-items:center;justify-content:{justify}">{e}</div>'
        for e in entries)


def _forms(rec):
    um = rec['um']
    A = rec['umA']
    if rec['boxMode']:
        bxu = sorted(um[n] for n in rec['names'][:min(4, len(rec['names']))])
        return [('複勝BOX', [bxu], ''), ('ワイドBOX', [bxu], '-'),
                ('馬連BOX', [bxu], '-'), ('三連複BOX', [bxu], '-')]
    uren = [um[n] for n in rec['col2'] if n != rec['A']]
    wd = [um[n] for n in rec['col3'] if n != rec['A']]
    col1u = [um[n] for n in rec['col1']]
    col2u = [um[n] for n in rec['col2']]
    col3u = [um[n] for n in rec['col3']]
    return [
        ('単勝', [[A]], ''),
        ('複勝', [[A]], ''),
        ('馬連', [[A], uren], '-'),
        ('ワイド', [[A], wd], '-'),
        ('馬単', [col1u, col2u], '→'),
        ('三連複', [[A], wd], '-'),
        ('三連単', [col1u, col2u, col3u], '→'),
    ]


def render_panel(rec, ev_eval):
    bc, bg, tx = _VERDICT_STYLE.get(rec['verdict'], ('#7f8c8d', '#222', '#bbb'))
    waku = rec.get('waku', {})
    pv_uma = rec.get('pv_uma', {})
    o3_uma = rec.get('o3_uma', {})
    p3_uma = rec.get('p3_uma', {})
    fin = ev_eval['axis_fin']
    fin_str = f'{fin}着' if fin else '—'
    order = ev_eval['order']
    rows = ''
    vmid = 'vertical-align:middle;'
    for bt, cols, sep in _forms(rec):
        if bt not in ev_eval['bets']:
            continue
        pts, total_ret, hitlist = ev_eval['bets'][bt]
        if pts < 1:
            continue
        cost = pts * 100
        hit = total_ret > 0
        roi = (total_ret / cost * 100) if cost else 0
        mark = '<span style="color:#5DCAA5">&#9711;</span>' if hit else '<span style="color:#7a8694">&times;</span>'
        roi_c = '#5DCAA5' if roi >= 100 else ('#bdc3c7' if roi > 0 else '#7a8694')
        # 的中馬券ごとのサブ行
        fm_e, pay_e, be_e, ev_e = [], [], [], []
        for combo, payout in hitlist:
            fm_e.append(_combo_chips(combo, sep, waku))
            pay_e.append(f'&yen;{payout:,}')
            Pc = _combo_prob(bt, combo, pv_uma, o3_uma, p3_uma)
            be = (1.0 / Pc) if Pc and Pc > 0 else None
            be_e.append(f'<span style="color:#f1c40f">{be:.1f}倍</span>' if be else '<span style="color:#7a8694">&mdash;</span>')
            if be and (payout / 100.0) >= be:
                ev_e.append('<span style="color:#5DCAA5;font-weight:700">&#9678; 期待値プラス</span>')
            else:
                ev_e.append('<span style="color:#e67e22;font-weight:700">&#9651; 期待値マイナス</span>')
        rows += (f'<tr>'
                 f'<td style="font-weight:700;white-space:nowrap;{vmid}">{bt}</td>'
                 f'<td style="{vmid}">{_cols_html(cols, sep, waku)}</td>'
                 f'<td style="text-align:right;{vmid}">{pts}</td>'
                 f'<td style="text-align:center;{vmid}">{mark}</td>'
                 f'<td style="padding:0">{_stack(fm_e, "flex-start")}</td>'
                 f'<td style="padding:0;white-space:nowrap">{_stack(pay_e, "flex-end")}</td>'
                 f'<td style="text-align:right;color:{roi_c};font-weight:700;{vmid}">{roi:.0f}%</td>'
                 f'<td style="padding:0;white-space:nowrap">{_stack(be_e, "flex-end")}</td>'
                 f'<td style="padding:0;white-space:nowrap">{_stack(ev_e, "center")}</td>'
                 f'</tr>')
    note = ('軸固定の券種は軸が3着内に来ないと連鎖で外れます。'
            if not ev_eval['box'] else '軸不在の混戦としてBOX評価。')
    return f'''<div class="section" id="section-bettype">
  <h2>&#127915; 券種別 結果照合</h2>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
    <span style="background:{bg};color:{tx};border:1px solid {bc};border-radius:6px;padding:3px 10px;font-size:12px;font-weight:700">予想時判定: {rec['verdict']}</span>
    <span style="font-size:12px;color:#9fb3c8">軸 {rec['umA']}番 &rarr; <b style="color:#e0e0e0">{fin_str}</b>（推定{rec['srcA']:.0f}番人気）</span>
    <span style="font-size:11px;color:#7f8c8d;margin-left:auto">着順 {'-'.join(str(x) for x in order[:3])}…</span>
  </div>
  <div style="overflow-x:auto"><table>
    <thead><tr><th>券種</th><th>推奨フォーメーション</th><th style="text-align:right">点数</th><th style="text-align:center">的中</th><th>的中フォーメーション</th><th style="text-align:right">確定配当(100円)</th><th style="text-align:right">回収率</th><th style="text-align:right">採算オッズ</th><th style="text-align:center">期待値</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  <div class="note">予想ダッシュボードが提案する各券種フォーメーションを、この結果の確定配当で照合（各組1点ずつ）。{note} 採算オッズ＝1÷その買い目の的中率（内訳の個別採算オッズ）。的中馬券ごとに確定配当が採算オッズを上回れば期待値プラス。回収率はフォーメーション全体（総払戻÷総投資）。馬番バッジの色は枠番カラー。</div>
</div>'''


def build_panel_for_review(rid, outdir, res_df, payouts):
    try:
        pred = find_pred_html(rid, outdir)
        if not pred:
            return ''
        ev = load_evdata(pred)
        if not ev:
            return ''
        rec = reconstruct(ev)
        if rec is None:
            return ''
        ee = eval_race(rec, res_df, payouts)
        if ee is None:
            return ''
        return render_panel(rec, ee)
    except Exception as e:
        import sys
        print(f'  [bettype] パネル生成スキップ: {e}', file=sys.stderr)
        return ''
