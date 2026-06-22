# -*- coding: utf-8 -*-
"""
bet_recon.py — pred HTMLのEV_DATAからダッシュボードbet-panelの買い目(軸/相手/列/判定)を
Pythonで再構築し、確定配当(payouts)と突き合わせて券種別の的中/回収を返す。
build_review から回顧の「券種別 結果照合」パネル生成に使う。
analyze_bettype.py と同一ロジック（検証済み）。
"""
import re, json, math, os, itertools

T = 20.0


def load_evdata(pred_path):
    h = open(pred_path, encoding='utf-8').read()
    m = re.search(r'EV_DATA\s*=\s*(\[.*?\]);\s*\n', h, re.S)
    return json.loads(m.group(1)) if m else None


def find_pred_html(rid, outdir):
    """rid=YYYYMMDD_venueN に対応する pred HTML を新旧命名両対応で探す。"""
    cands = [os.path.join(outdir, f'{rid}_pred.html'),
             os.path.join(outdir, f'pred_{rid}.html')]
    for c in cands:
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
    miyomi = False
    boxMode = False
    if _srcA >= 4:
        verdict = '中穴軸'
    elif (_srcA == 2 or _srcA == 3) and (_fav1Rank >= 4 or _ana):
        miyomi = True
        verdict = '買い妙味'
    elif wA < 0.18:
        boxMode = True
        verdict = '混戦BOX'
    else:
        verdict = '見送り'
    if miyomi:
        topPop = [n for n in partners if sc[n] is not None and _num(sc[n], 99) <= 3]
        hasAna = any(sc[n] is not None and _num(sc[n], 99) >= 5 for n in partners)
        if topPop:
            cutHorse = min(topPop, key=lambda n: pv[n])
            partners = [n for n in partners if n != cutHorse]
            contend = [A] + partners
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
    return dict(A=A, umA=um[A], wA=wA, srcA=srcA, verdict=verdict, miyomi=miyomi,
                boxMode=boxMode, col1=col1, col2=col2, col3=col3, um=um,
                names=names)


def _to_int(x):
    try:
        return int(float(x))
    except Exception:
        return None


def _parse_combo(s):
    return [_to_int(p) for p in str(s).replace('=', '-').split('-')]


def eval_race(rec, res_df, payouts):
    um = rec['um']
    df = res_df[[c for c in ['入線順位', '馬番'] if c in res_df.columns]].dropna().copy()
    df['_o'] = df['入線順位'].apply(_to_int)
    df['_u'] = df['馬番'].apply(_to_int)
    df = df.dropna(subset=['_o', '_u']).sort_values('_o')
    order = [int(u) for u in df['_u'].tolist()]
    if len(order) < 3:
        return None

    def pay(key, fn):
        for combo, amt in payouts.get(key, []):
            if fn(_parse_combo(combo)):
                return amt
        return None
    tansho = {_to_int(c): a for c, a in payouts.get('tansho', [])}
    fuku = {_to_int(c): a for c, a in payouts.get('fukusho', [])}
    umA = rec['umA']
    A = rec['A']
    top1 = order[0]
    bets = {}
    if rec['boxMode']:
        bx = rec['names'][:min(4, len(rec['names']))]
        bxu = sorted(um[n] for n in bx)
        bets['複勝BOX'] = (len(bxu), sum(fuku.get(u, 0) for u in bxu))
        pairs = list(itertools.combinations(bxu, 2))
        ret = 0
        for c in pairs:
            cs = set(c)
            for combo, amt in payouts.get('wide', []):
                if set(_parse_combo(combo)) == cs:
                    ret += amt
        bets['ワイドBOX'] = (len(pairs), ret)
        ret = sum((pay('umaren', lambda nums, cs=set(c): set(nums) == cs) or 0) for c in pairs)
        bets['馬連BOX'] = (len(pairs), ret)
        tri = list(itertools.combinations(bxu, 3))
        ret = sum((pay('sanrenpuku', lambda nums, cs=set(c): set(nums) == cs) or 0) for c in tri)
        bets['三連複BOX'] = (len(tri), ret)
        return dict(order=order, bets=bets, box=True, axis_uma=umA,
                    axis_fin=order.index(umA) + 1 if umA in order else None)

    col1u = [um[n] for n in rec['col1']]
    col2u = [um[n] for n in rec['col2']]
    col3u = [um[n] for n in rec['col3']]
    uren = [um[n] for n in rec['col2'] if n != A]
    wd = [um[n] for n in rec['col3'] if n != A]
    bets['単勝'] = (1, tansho.get(umA, 0) if umA == top1 else 0)
    bets['複勝'] = (1, fuku.get(umA, 0))
    ret = sum((pay('umaren', lambda nums, cs={umA, o}: set(nums) == cs) or 0) for o in uren)
    bets['馬連'] = (len(uren), ret)
    ret = 0
    for o in wd:
        cs = {umA, o}
        for combo, amt in payouts.get('wide', []):
            if set(_parse_combo(combo)) == cs:
                ret += amt
    bets['ワイド'] = (len(wd), ret)
    pts = 0
    ret = 0
    for i in col1u:
        for j in col2u:
            if i != j:
                pts += 1
                a = pay('umatan', lambda nums, i=i, j=j: nums[0] == i and nums[1] == j)
                if a:
                    ret += a
    bets['馬単'] = (pts, ret)
    tri = list(itertools.combinations(wd, 2))
    ret = sum((pay('sanrenpuku', lambda nums, cs={umA, c[0], c[1]}: set(nums) == cs) or 0) for c in tri)
    bets['三連複'] = (len(tri), ret)
    pts = 0
    ret = 0
    for i in col1u:
        for j in col2u:
            for k in col3u:
                if i != j and j != k and i != k:
                    pts += 1
                    a = pay('sanrentan', lambda nums, i=i, j=j, k=k: nums == [i, j, k])
                    if a:
                        ret += a
    bets['三連単'] = (pts, ret)
    return dict(order=order, bets=bets, box=False, axis_uma=umA,
                axis_fin=order.index(umA) + 1 if umA in order else None)


_VERDICT_STYLE = {
    '買い妙味': ('#27ae60', '#1a3a28', '#5DCAA5'),
    '中穴軸':   ('#f1c40f', '#3a2e10', '#f1c40f'),
    '混戦BOX':  ('#f1c40f', '#3a2e10', '#f1c40f'),
    '見送り':   ('#e74c3c', '#3a1a1a', '#F09595'),
}


def render_panel(rec, ev_eval):
    """回顧用の『券種別 結果照合』セクションHTMLを返す。"""
    bc, bg, tx = _VERDICT_STYLE.get(rec['verdict'], ('#7f8c8d', '#222', '#bbb'))
    fin = ev_eval['axis_fin']
    fin_str = f'{fin}着' if fin else '—'
    order = ev_eval['order']
    inv = sum(p * 100 for p, _ in ev_eval['bets'].values())
    ret = sum(r for _, r in ev_eval['bets'].values())
    roi = (ret / inv * 100) if inv else 0
    hit_badge = ('#27ae60', '○ 回収プラス') if roi >= 100 else ('#e74c3c', '× 回収マイナス')
    rows = ''
    for bt, (pts, r) in ev_eval['bets'].items():
        if pts < 1:
            continue
        cost = pts * 100
        hit = r > 0
        br = (r / cost * 100) if cost else 0
        mark = '<span style="color:#5DCAA5">○</span>' if hit else '<span style="color:#7a8694">×</span>'
        pay_s = f'&yen;{r:,}' if hit else '<span style="color:#7a8694">—</span>'
        roi_c = '#5DCAA5' if br >= 100 else ('#bdc3c7' if br > 0 else '#7a8694')
        rows += (f'<tr><td style="font-weight:700">{bt}</td>'
                 f'<td style="text-align:right">{pts}</td>'
                 f'<td style="text-align:center">{mark}</td>'
                 f'<td style="text-align:right">{pay_s}</td>'
                 f'<td style="text-align:right;color:{roi_c};font-weight:700">{br:.0f}%</td></tr>')
    total_c = '#5DCAA5' if roi >= 100 else '#F09595'
    note = ('軸固定の券種は軸が3着内に来ないと連鎖で外れます。'
            if not ev_eval['box'] else '軸不在の混戦としてBOX評価。')
    return f'''<div class="section" id="section-bettype">
  <h2>&#127915; 券種別 結果照合</h2>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
    <span style="background:{bg};color:{tx};border:1px solid {bc};border-radius:6px;padding:3px 10px;font-size:12px;font-weight:700">予想時判定: {rec['verdict']}</span>
    <span style="background:#16202b;color:{hit_badge[0]};border:1px solid {hit_badge[0]};border-radius:6px;padding:3px 10px;font-size:12px;font-weight:700">{hit_badge[1]}</span>
    <span style="font-size:12px;color:#9fb3c8">軸 {rec['umA']}番 &rarr; <b style="color:#e0e0e0">{fin_str}</b>（推定{rec['srcA']:.0f}番人気）</span>
    <span style="font-size:11px;color:#7f8c8d;margin-left:auto">着順 {'-'.join(str(x) for x in order[:3])}…</span>
  </div>
  <div style="overflow-x:auto"><table>
    <thead><tr><th>券種</th><th style="text-align:right">点数</th><th style="text-align:center">的中</th><th style="text-align:right">確定配当(100円)</th><th style="text-align:right">回収率</th></tr></thead>
    <tbody>{rows}
    <tr style="border-top:2px solid #2c3e50"><td style="font-weight:700">合計（各1点ずつ）</td><td style="text-align:right">{inv//100}</td><td></td><td style="text-align:right">&yen;{ret:,}</td><td style="text-align:right;color:{total_c};font-weight:700">{roi:.0f}%</td></tr>
    </tbody>
  </table></div>
  <div class="note">予想ダッシュボードが提案する各券種フォーメーションを、この結果の確定配当で照合（各組1点ずつ）。{note} 合計回収率は全券種を1点ずつ買った場合の理論値です。</div>
</div>'''


def build_panel_for_review(rid, outdir, res_df, payouts):
    """build_review から呼ぶ高水準関数。失敗時は空文字を返す（回顧生成は止めない）。"""
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
