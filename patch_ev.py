# -*- coding: utf-8 -*-
"""build_dashboard_v3.py にレース推奨度パネルを追加するパッチスクリプト"""
import pathlib

src = pathlib.Path(__file__).parent / 'build_dashboard_v3.py'
data = src.read_bytes()

# ──────────────────────────────────────────────────────────────────
# ステップ2: 補正チャートデータブロックの前にレース推奨度計算ブロックを挿入
# ──────────────────────────────────────────────────────────────────
CHART_HEADER = '# ── 補正積み上げチャートデータ ──────────────────────────────────'.encode('utf-8')
assert data.count(CHART_HEADER) == 1, f"CHART_HEADER count={data.count(CHART_HEADER)}"

REC_BLOCK = '''\
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
    _rec_badge  = '🟢 購入検討'
    _rec_color  = '#27ae60'
    _rec_bg     = '#1a3a28'
    _rec_reason = f'SmartRC推定より{_max_kairido}順位上の穴馬候補あり（大きな市場乖離）'
elif _max_kairido >= 2:
    _rec_badge  = '🟡 要検討'
    _rec_color  = '#f39c12'
    _rec_bg     = '#3a2e10'
    _rec_reason = f'SmartRC推定より{_max_kairido}順位上の乖離（中穴の可能性）'
else:
    _rec_badge  = '⚪ 市場一致'
    _rec_color  = '#7f8c8d'
    _rec_bg     = '#1e2535'
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

data = data.replace(CHART_HEADER, REC_BLOCK + CHART_HEADER, 1)
print('step2 OK')

# ──────────────────────────────────────────────────────────────────
# ステップ3: EVパネルの <h2> 直後に推奨度バナーを挿入
# ──────────────────────────────────────────────────────────────────
old3 = '    <h2>💰 期待値シミュレーター</h2>\n    <div class="temp-slider">'.encode('utf-8')
assert data.count(old3) == 1, f"old3 count={data.count(old3)}"

new3 = '''\
    <h2>💰 期待値シミュレーター</h2>
    <!-- レース推奨度バナー -->
    <div style="display:flex;align-items:center;flex-wrap:wrap;gap:8px;
                padding:10px 16px;margin-bottom:14px;border-radius:8px;
                background:{_rec_bg};border:1px solid {_rec_color};">
      <span style="font-size:15px;font-weight:900;color:{_rec_color};
                   padding:3px 14px;border-radius:5px;border:2px solid {_rec_color};">
        {_rec_badge}
      </span>
      <span style="color:#ccc;font-size:12px;">{_rec_reason}</span>
      {_best_html}
    </div>
    <div class="temp-slider">'''.encode('utf-8')

data = data.replace(old3, new3, 1)
print('step3 OK')

# ──────────────────────────────────────────────────────────────────
# ステップ4: EVテーブルに「乖離度」列ヘッダを追加
# ──────────────────────────────────────────────────────────────────
old4 = ('            <th data-col="src_ninki" onclick="sortEV(this)" '
        'title="SmartRC推定人気順">推定人気</th>').encode('utf-8')
assert data.count(old4) == 1, f"old4 count={data.count(old4)}"

new4 = ('            <th data-col="src_ninki" onclick="sortEV(this)" '
        'title="SmartRC推定人気順">推定人気</th>\n'
        '            <th data-col="kairido" onclick="sortEV(this)" '
        'title="SmartRC推定人気順 − スコア順位（プラスほど穴馬）">乖離度</th>').encode('utf-8')

data = data.replace(old4, new4, 1)
print('step4 OK')

# ──────────────────────────────────────────────────────────────────
# ステップ5: colVal に乖離度ケースを追加
# ──────────────────────────────────────────────────────────────────
old5 = "    case 'rank':  return h['順位予想'];".encode('utf-8')
assert data.count(old5) == 1, f"old5 count={data.count(old5)}"

new5 = ("    case 'rank':    return h['順位予想'];\n"
        "    case 'kairido': return h['乖離度'] != null ? h['乖離度'] : -99;").encode('utf-8')
data = data.replace(old5, new5, 1)
print('step5 OK')

# ──────────────────────────────────────────────────────────────────
# ステップ6: renderRows に乖離度セルを追加（推定人気セルの直後）
# ──────────────────────────────────────────────────────────────────
old6 = '      <td style="text-align:center;white-space:nowrap">${{srcNinkiCell}}</td>'.encode('utf-8')
assert data.count(old6) == 1, f"old6 count={data.count(old6)}"

new6 = '''\
      <td style="text-align:center;white-space:nowrap">${{srcNinkiCell}}</td>
      <td style="text-align:center;white-space:nowrap">${{
        (() => {{
          const k = h['乖離度'];
          if (k == null) return '<span style="color:#555">-</span>';
          const col = k >= 4 ? '#27ae60' : k >= 2 ? '#f39c12' : k >= 0 ? '#95a5a6' : '#e74c3c';
          const pf  = k > 0 ? '+' : '';
          const lbl = k >= 4 ? '大穴↑' : k >= 2 ? '中穴↑' : k >= 0 ? '±' : '割高↓';
          return `<span style="font-weight:700;color:${{col}}">${{pf}}${{k}}</span>`
               + `<span style="font-size:9px;color:${{col}};margin-left:2px">${{lbl}}</span>`;
        }})()
      }}</td>'''.encode('utf-8')

data = data.replace(old6, new6, 1)
print('step6 OK')

src.write_bytes(data)
print('=== 全パッチ完了 ===')
