# -*- coding: utf-8 -*-
"""
bet_recommend.py — 勝率(softmax)から全券種の確率・フェアオッズ・軸流し買い目を算出する。

設計方針:
- モデル勝率 p_i（build_dashboard_v3 と同じ softmax を想定）を入力に、
  Harville(Plackett-Luce) で順序付き確率を厳密計算 → 各券種の的中確率を導出。
- 期待値(EV)判定には購入直前の実配当が必要なため、本モジュールは
  「モデル的中確率」と「モデル基準フェアオッズ(=1/確率, 控除前)」を返す。
  実オッズが与えられれば EV = 実オッズ×確率 − 1 を判定（calc_ev）。
- 軸流し中心。軸は呼び出し側で指定（妙味馬 or モデル本命）。

計算量制御: 列挙は上位 topN 頭に限定（既定7）。3連系は topN=7 で 7P3=210 通り。
"""
from itertools import permutations, combinations

BET_TYPES = ['単勝', '複勝', '馬連', '馬単', 'ワイド', '三連複', '三連単']


def harville_order_prob(seq, pv):
    """順序 seq（馬名タプル）が完全にその順で決まる確率（Plackett-Luce）。"""
    rem = 1.0
    pr = 1.0
    for h in seq:
        if rem <= 0:
            return 0.0
        pr *= pv[h] / rem
        rem -= pv[h]
    return pr


def compute_probs(names, win_probs, topN=7):
    """names/win_probs(合計1付近)から各種確率を返す dict。"""
    pairs = sorted(zip(names, win_probs), key=lambda x: -x[1])[:topN]
    nm = [n for n, _ in pairs]
    s = sum(p for _, p in pairs) or 1.0
    pv = {n: p / s for n, p in pairs}
    order3 = {seq: harville_order_prob(seq, pv) for seq in permutations(nm, 3)}
    win = {n: pv[n] for n in nm}
    place3 = {n: sum(p for seq, p in order3.items() if n in seq) for n in nm}
    umatan = {}
    for a, b in permutations(nm, 2):
        umatan[(a, b)] = pv[a] * pv[b] / (1 - pv[a]) if pv[a] < 1 else 0.0
    umaren = {frozenset((a, b)): umatan[(a, b)] + umatan[(b, a)]
              for a, b in combinations(nm, 2)}
    wide = {frozenset((a, b)): sum(p for seq, p in order3.items()
                                   if a in seq and b in seq)
            for a, b in combinations(nm, 2)}
    sanrenpuku = {frozenset((a, b, c)): sum(order3.get(s, 0) for s in permutations((a, b, c)))
                  for a, b, c in combinations(nm, 3)}
    return dict(win=win, place3=place3, umaren=umaren, umatan=umatan,
                wide=wide, sanrenpuku=sanrenpuku, sanrentan=dict(order3), names_used=nm)


def fair_odds(p):
    return (1.0 / p) if p and p > 0 else float('inf')


def calc_ev(prob, actual_odds):
    """EV = 実オッズ × 的中確率 − 1。actual_odds 不明時は None。"""
    if actual_odds is None or prob is None:
        return None
    return actual_odds * prob - 1.0


def _order_key(names):
    pos = {n: i for i, n in enumerate(names)}
    return lambda combo: '-'.join(sorted(combo, key=lambda x: pos.get(x, 99)))


def build_recommendations(names, win_probs, anchor, topN=7, n_wide=4, n_trio=4):
    """軸流し中心の買い目候補を券種別に返す（確率降順）。
    返り値: ({券種: [ {'buy':表示, 'prob':p, 'fair':fairodds}, ... ]}, probs_dict)
    """
    P = compute_probs(names, win_probs, topN=topN)
    nm = P['names_used']
    if anchor not in nm:
        anchor = nm[0]
    others = [n for n in nm if n != anchor]
    k = _order_key(names)
    out = {}
    out['単勝'] = [{'buy': anchor, 'prob': P['win'][anchor], 'fair': fair_odds(P['win'][anchor])}]
    out['複勝'] = [{'buy': anchor, 'prob': P['place3'][anchor], 'fair': fair_odds(P['place3'][anchor])}]
    ml = sorted(((frozenset((anchor, o)), P['umaren'][frozenset((anchor, o))]) for o in others),
                key=lambda x: -x[1])[:n_wide]
    out['馬連'] = [{'buy': k(c), 'prob': p, 'fair': fair_odds(p)} for c, p in ml]
    mt = sorted((((anchor, o), P['umatan'][(anchor, o)]) for o in others), key=lambda x: -x[1])[:n_wide]
    out['馬単'] = [{'buy': f'{a}→{b}', 'prob': p, 'fair': fair_odds(p)} for (a, b), p in mt]
    wl = sorted(((frozenset((anchor, o)), P['wide'][frozenset((anchor, o))]) for o in others),
                key=lambda x: -x[1])[:n_wide]
    out['ワイド'] = [{'buy': k(c), 'prob': p, 'fair': fair_odds(p)} for c, p in wl]
    tp = sorted(((frozenset((anchor, a, b)), P['sanrenpuku'][frozenset((anchor, a, b))])
                 for a, b in combinations(others, 2)), key=lambda x: -x[1])[:n_trio]
    out['三連複'] = [{'buy': k(c), 'prob': p, 'fair': fair_odds(p)} for c, p in tp]
    tt = sorted((((anchor, a, b), P['sanrentan'][(anchor, a, b)])
                 for a, b in permutations(others, 2)), key=lambda x: -x[1])[:n_trio]
    out['三連単'] = [{'buy': f'{seq[0]}→{seq[1]}→{seq[2]}', 'prob': p, 'fair': fair_odds(p)} for seq, p in tt]
    return out, P


if __name__ == '__main__':
    import math
    names = ['A', 'B', 'C', 'D', 'E', 'F']
    scores = [80, 70, 60, 55, 50, 40]
    mx = max(scores); ex = [math.exp((s - mx) / 20) for s in scores]; tot = sum(ex)
    wp = [e / tot for e in ex]
    reco, P = build_recommendations(names, wp, anchor='B')
    print('win sum=', round(sum(P['win'].values()), 4), ' place3 A=', round(P['place3']['A'], 3))
    for bt, items in reco.items():
        print(bt, [(it['buy'], round(it['prob'] * 100, 1), round(it['fair'], 1)) for it in items[:3]])
