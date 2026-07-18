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
    A = arr[0]['name']                      # 軸 = スコア(偏差値)1位
    wA = pv[A]
    srcA = float(sc[A]) if sc[A] is not None else 99
    devA = dv[A]
    n_runners = sum(1 for h in ev if h.get('馬番') is not None)
    # ③-1,2 相手候補: 軸との偏差値差 ≤ 20、上限 min(6, 頭数//3)、さらに断層カット
    cand = [x['name'] for x in arr if x['name'] != A and (devA - dv[x['name']]) <= 20.0]
    cand.sort(key=lambda nm: -dv[nm])
    cap = min(6, n_runners // 3)
    # ③-2b 断層カット: 偏差値降順で連続ギャップが 5.0 超ならそこで打ち切り（上限と併用）
    _GAP = 5.0
    partners = []
    _prev = None
    for _nm in cand:
        if len(partners) >= cap:
            break
        if partners and (_prev - dv[_nm]) > _GAP:
            break
        partners.append(_nm)
        _prev = dv[_nm]
    # ③-3 偏差値バンドで列1/2/3（軸との差 ≤3 / ≤10 / ≤20）
    _B1, _B2 = 3.0, 10.0
    col1 = ([A] + [nm for nm in partners if (devA - dv[nm]) <= _B1])[:3]
    col2 = [A] + [nm for nm in partners if (devA - dv[nm]) <= _B2]   # 軸も2着列に（頭固定でない）
    col3 = [A] + list(partners)                                       # 軸も3着列に
    contend = [A] + partners
    # 軸のコース特徴pts
    kt_axis = None
    for h in ev:
        if h.get('馬名') == A:
            kt_axis = _num(h.get('コース特徴pts'), None); break
    # ② 購入推奨ゲート（全条件AND / 推定人気ベース）
    _pop = lambda nm: _num(sc[nm], 99)
    _top3 = sum(1 for nm in contend if _pop(nm) in (1, 2, 3))
    cond1 = _top3 <= 2                                                   # 1-3番人気は最大2頭
    cond2 = True if _pop(A) not in (1, 2) else all(_pop(nm) not in (1, 2, 3, 4) for nm in partners)  # 軸が1/2番人気なら相手に1-4番人気なし
    cond3 = (kt_axis is not None and kt_axis > 0)                        # 軸のコース特徴pts>0
    _pops_ct = [_pop(nm) for nm in contend]
    _only123  = all(p in (1, 2, 3) for p in _pops_ct)                    # フォーメーションが1-3番人気のみ
    _all123in = all(r in _pops_ct for r in (1, 2, 3))                    # 1-3番人気を全て軸+相手が総取り
    cond4 = not (_only123 or _all123in)                                  # 上記は妙味皆無→非推奨
    verdict = '購入推奨' if (len(partners) >= 1 and cond1 and cond2 and cond3 and cond4) else '購入非推奨'
    # 表示は馬番順
    col1 = sorted(col1, key=lambda nm: um[nm])
    col2 = sorted(col2, key=lambda nm: um[nm])
    col3 = sorted(col3, key=lambda nm: um[nm])
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
    return dict(A=A, umA=um[A], wA=wA, srcA=srcA, verdict=verdict,
                col1=col1, col2=col2, col3=col3, um=um, partners=partners,
                cond=dict(c1=cond1, c2=cond2, c3=cond3), kt_axis=kt_axis,
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
    bets = {}
    col1u = [um[n] for n in rec['col1']]
    col2u = [um[n] for n in rec['col2']]
    col3u = [um[n] for n in rec['col3']]
    uren = [um[n] for n in rec['col2'] if n != A]
    wd = [um[n] for n in rec['col3'] if n != A]
    hits = []; ret = 0
    for o in uren:
        for cs, a in umaren:
            if cs == {umA, o}:
                hits.append((sorted([umA, o]), a)); ret += a
    bets['馬連'] = (len(uren), ret, hits)
    hits = []; ret = 0
    for o in wd:
        for cs, a in wide:
            if cs == {umA, o}:
                hits.append((sorted([umA, o]), a)); ret += a
    bets['ワイド'] = (len(wd), ret, hits)
    pts = 0; ret = 0; hits = []
    for i in col1u:
        for j in col2u:
            if i != j:
                pts += 1
                for combo, a in umatan:
                    if combo == [i, j]:
                        hits.append(([i, j], a)); ret += a
    bets['馬単'] = (pts, ret, hits)
    hits = []; ret = 0
    for c in itertools.combinations(wd, 2):
        for cs, a in s3p:
            if cs == {umA, c[0], c[1]}:
                hits.append((sorted([umA, c[0], c[1]]), a)); ret += a
    bets['三連複'] = (len(list(itertools.combinations(wd, 2))), ret, hits)
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
    '購入推奨': ('#27ae60', '#1a3a28', '#5DCAA5'),
    '購入非推奨': ('#e74c3c', '#3a1a1a', '#F09595'),
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
    uren = [um[n] for n in rec['col2'] if n != rec['A']]
    wd = [um[n] for n in rec['col3'] if n != rec['A']]
    col1u = [um[n] for n in rec['col1']]
    col2u = [um[n] for n in rec['col2']]
    col3u = [um[n] for n in rec['col3']]
    return [
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
