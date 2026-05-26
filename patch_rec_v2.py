# -*- coding: utf-8 -*-
"""推奨度ロジック v2 パッチ
  - 乖離2-3 + 1番人気低スコア → 妙味有 に昇格
  - 妙味有 + (偏差値≥65 OR リード幅≥15pt) → 「自信あり」バッジ追加
"""
import pathlib, re

src = pathlib.Path(__file__).parent / 'build_dashboard_v3.py'
data = src.read_bytes()

# ──────────────────────────────────────────────────────────────
# 旧レース推奨度ブロック全体を新しいものに置換
# ──────────────────────────────────────────────────────────────
OLD_BLOCK = '''\
# ── レース推奨度計算（スコア上位3頭 vs SmartRC推定人気の乖離） ────────────
_rc_top3 = sorted(
    [h for h in horses if not h.get('過去走なし', False)],
    key=lambda h: h.get('順位予想', 99)
)[:3]
_rc_candidates = []
for _h in _rc_top3:
    _src = _h.get('SmartRC推定人気順')
    if _src is not None:
        try:
            _kairido = int(_src) - _h.get('順位予想', 99)
            _rc_candidates.append({
                '馬名':        _h['馬名'],
                '乖離':        _kairido,
                '予想順位':    _h.get('順位予想', 99),
                'SmartRC推定': int(_src),
                '人気':        _h.get('人気'),
                'オッズ':      _h.get('単勝オッズ'),
            })
        except Exception:
            pass

_max_kairido = max((_v['乖離'] for _v in _rc_candidates), default=0)
_best_val = (max(_rc_candidates, key=lambda x: x['乖離'])
             if _rc_candidates else None)

if _max_kairido >= 4:
    _rec_badge  = '🟢 妙味有'
    _rec_color  = '#27ae60'
    _rec_bg     = '#1a3a28'
    _rec_reason = f'SmartRC推定より{_max_kairido}順位上の穴馬候補あり（大きな市場乖離）'
elif _max_kairido >= 2:
    _rec_badge  = '🟡 要検討'
    _rec_color  = '#f39c12'
    _rec_bg     = '#3a2e10'
    _rec_reason = f'SmartRC推定より{_max_kairido}順位上の乖離（中穴の可能性）'
else:
    _rec_badge  = '🔴 妙味薄'
    _rec_color  = '#e74c3c'
    _rec_bg     = '#3a1a1a'
    _rec_reason = 'スコア上位3頭とSmartRC推定が概ね一致（妙味薄め）'

_best_html = ''
if _best_val and _best_val['乖離'] >= 2:
    _odds_str = (f'{_best_val["オッズ"]:.1f}倍'
                 if _best_val.get('オッズ') else '-')
    _best_html = (
        f'<span style="margin-left:14px;padding:3px 10px;'
        f'background:#2c3e50;border-radius:4px;font-size:12px;">'
        f'💎 注目馬: <b style="color:#f1c40f">{_best_val["馬名"]}</b>'
        f'（予想{_best_val["予想順位"]}位 / SmartRC{_best_val["SmartRC推定"]}番人気'
        f' / 乖離+{_best_val["乖離"]} / 単勝{_odds_str}）'
        f'</span>'
    )
'''.encode('utf-8')

NEW_BLOCK = '''\
# ── レース推奨度計算（スコア上位3頭 vs SmartRC推定人気の乖離） ────────────
_rc_top3 = sorted(
    [h for h in horses if not h.get('過去走なし', False)],
    key=lambda h: h.get('順位予想', 99)
)[:3]
_rc_candidates = []
for _h in _rc_top3:
    _src = _h.get('SmartRC推定人気順')
    if _src is not None:
        try:
            _kairido = int(_src) - _h.get('順位予想', 99)
            _rc_candidates.append({
                '馬名':        _h['馬名'],
                '乖離':        _kairido,
                '予想順位':    _h.get('順位予想', 99),
                'SmartRC推定': int(_src),
                '人気':        _h.get('人気'),
                'オッズ':      _h.get('単勝オッズ'),
            })
        except Exception:
            pass

_max_kairido = max((_v['乖離'] for _v in _rc_candidates), default=0)
_best_val = (max(_rc_candidates, key=lambda x: x['乖離'])
             if _rc_candidates else None)

# ── 1番人気の低スコア判定（乖離2-3の昇格条件） ───────────────
_n_horses = len(horses)
_fav1_score_rank = next(
    (h.get('順位予想', 99) for h in horses if h.get('人気') == 1), 99
)
_fav_thr = _n_horses // 2 if _n_horses <= 12 else 7
_fav1_is_low = _fav1_score_rank > _fav_thr

# ── 自信あり判定（偏差値≥65 OR スコアリード≥15pt） ─────────────
_sorted_valid = sorted(
    [h for h in horses if not h.get('過去走なし', False)],
    key=lambda h: h.get('順位予想', 99)
)
_pred1_name  = _sorted_valid[0]['馬名'] if _sorted_valid else ''
_pred1_score = _sorted_valid[0].get('総合スコア', 0) if _sorted_valid else 0
_pred2_score = _sorted_valid[1].get('総合スコア', 0) if len(_sorted_valid) > 1 else 0
_score_lead  = _pred1_score - _pred2_score
_pred1_dev   = _dev_map.get(_pred1_name, 50)
_jishin_flag = (_pred1_dev >= 65) or (_score_lead >= 15)

# ── 推奨度判定 ───────────────────────────────────────────────
if _max_kairido >= 4:
    _rec_badge  = '🟢 妙味有'
    _rec_color  = '#27ae60'
    _rec_bg     = '#1a3a28'
    _rec_reason = f'SmartRC推定より{_max_kairido}順位上の穴馬候補あり（大きな市場乖離）'
elif _max_kairido >= 2:
    if _fav1_is_low:
        _rec_badge  = '🟢 妙味有'
        _rec_color  = '#27ae60'
        _rec_bg     = '#1a3a28'
        _rec_reason = (f'SmartRC推定より{_max_kairido}順位の乖離 '
                       f'+ 1番人気スコア{_fav1_score_rank}位（閾値{_fav_thr}超）')
    else:
        _rec_badge  = '🟡 要検討'
        _rec_color  = '#f39c12'
        _rec_bg     = '#3a2e10'
        _rec_reason = f'SmartRC推定より{_max_kairido}順位上の乖離（中穴の可能性）'
else:
    _rec_badge  = '🔴 妙味薄'
    _rec_color  = '#e74c3c'
    _rec_bg     = '#3a1a1a'
    _rec_reason = 'スコア上位3頭とSmartRC推定が概ね一致（妙味薄め）'

# ── 自信ありバッジ（妙味有 かつ 偏差値≥65 or リード≥15pt） ────
_jishin_html = ''
if _jishin_flag and '妙味有' in _rec_badge:
    _reasons = []
    if _pred1_dev >= 65:
        _reasons.append(f'偏差値{_pred1_dev}')
    if _score_lead >= 15:
        _reasons.append(f'リード{_score_lead:.1f}pt')
    _jishin_html = (
        f'<span style="display:inline-flex;align-items:center;gap:5px;'
        f'margin-left:10px;padding:4px 12px;border-radius:6px;'
        f'background:linear-gradient(135deg,#f39c12,#e67e22);'
        f'color:#fff;font-size:13px;font-weight:900;'
        f'box-shadow:0 0 8px rgba(243,156,18,0.6);">'
        f'⭐ 自信あり'
        f'<span style="font-size:10px;font-weight:400;opacity:0.9">'
        f'（{" / ".join(_reasons)}）</span>'
        f'</span>'
    )

_best_html = ''
if _best_val and _best_val['乖離'] >= 2:
    _odds_str = (f'{_best_val["オッズ"]:.1f}倍'
                 if _best_val.get('オッズ') else '-')
    _best_html = (
        f'<span style="margin-left:14px;padding:3px 10px;'
        f'background:#2c3e50;border-radius:4px;font-size:12px;">'
        f'💎 注目馬: <b style="color:#f1c40f">{_best_val["馬名"]}</b>'
        f'（予想{_best_val["予想順位"]}位 / SmartRC{_best_val["SmartRC推定"]}番人気'
        f' / 乖離+{_best_val["乖離"]} / 単勝{_odds_str}）'
        f'</span>'
    )
'''.encode('utf-8')

cnt = data.count(OLD_BLOCK)
print(f'推奨度ブロック: {cnt}件')
assert cnt == 1
data = data.replace(OLD_BLOCK, NEW_BLOCK, 1)
print('step1 OK')

# ── バナーHTMLに _jishin_html を追加 ────────────────────────
OLD_BANNER = (
    '      <span style="color:#ccc;font-size:12px;">{_rec_reason}</span>\n'
    '      {_best_html}\n'
    '    </div>'
).encode('utf-8')

NEW_BANNER = (
    '      <span style="color:#ccc;font-size:12px;">{_rec_reason}</span>\n'
    '      {_jishin_html}\n'
    '      {_best_html}\n'
    '    </div>'
).encode('utf-8')

cnt2 = data.count(OLD_BANNER)
print(f'バナーHTML: {cnt2}件')
assert cnt2 == 1
data = data.replace(OLD_BANNER, NEW_BANNER, 1)
print('step2 OK')

src.write_bytes(data)
print('=== パッチ完了 ===')
