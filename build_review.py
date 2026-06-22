import pandas as pd, json, pathlib, math, argparse, re, os as _os

# 既定パスはスクリプト基準（run_new.py からは --result/--horses/--scores/--outdir で明示指定される）
_BASE   = _os.path.dirname(_os.path.abspath(__file__))
UPLOADS = _os.path.join(_BASE, 'input')
OUTPUTS = _BASE

ap = argparse.ArgumentParser()
ap.add_argument('--result',   default=f'{UPLOADS}/レース結果.xlsx')
ap.add_argument('--racedata', default=None,
                help='省略時は --result ファイルの先頭2行からレースデータを読み取る（統合形式）')
ap.add_argument('--horses',   default=f'{OUTPUTS}/horses_data.json')
ap.add_argument('--scores',   default=f'{OUTPUTS}/scores.csv')
ap.add_argument('--out',      default=None)
ap.add_argument('--outdir',   default=None)
args = ap.parse_args()

# ── CSV / Excel 自動判定ヘルパー ─────────────────────────────

# レース結果を CSV/Excel/HTML から統一ロード（HTML は回顧データ＋全券種配当を含む）
from result_loader import load_result
res, meta, _payouts = load_result(args.result, racedata=args.racedata)
# 払戻（配当）が取れた場合は haraimodoshi_{rid}.json に保存（将来の券種別回収率バックテスト用）
if _payouts:
    import json as _json3, os as _os3
    _rid3 = _os3.path.splitext(_os3.path.basename(args.result))[0].replace('レース結果_', '').replace('レース結果', '')
    _pdir3 = args.outdir or _os3.path.dirname(_os3.path.abspath(args.result))
    try:
        _os3.makedirs(_pdir3, exist_ok=True)
        with open(_os3.path.join(_pdir3, 'haraimodoshi_' + _rid3 + '.json'), 'w', encoding='utf-8') as _pf3:
            _json3.dump({k: [[c, a] for c, a in v] for k, v in _payouts.items()}, _pf3, ensure_ascii=False, indent=2)
        print('  [payout] haraimodoshi_' + _rid3 + '.json を保存しました')
    except Exception as _pe3:
        print('  [payout] 保存スキップ:', _pe3)
with open(args.horses, encoding='utf-8') as f:
    pred = json.load(f)

pred_map = {h['馬名']: {
    '予想順位': h['順位予想'],
    'スコア': round(h['総合スコア'], 1) if h['総合スコア'] is not None else None,
    '脚質': h['脚質'], '枠番': h.get('枠番'),
    '複勝下限': h.get('複勝下限'), '複勝上限': h.get('複勝上限'),
    '過去走なし': h.get('過去走なし', False),
} for h in pred['horses']}

rows = []
for _, r in res.sort_values('入線順位').iterrows():
    # 出走取消馬を除外（タイムがハイフンのみ・空、または単勝が'取消し'）
    _odds_raw = str(r['単勝オッズ']).strip()
    _time_raw = str(r['タイム']).strip()
    _is_scratch = (
        _odds_raw == '取消し'
        or not _time_raw
        or all(c == '-' for c in _time_raw)
    )
    if _is_scratch:
        continue
    name = str(r['馬名']).strip()
    p    = pred_map.get(name, {})
    bango = int(r['馬番'])
    waku  = p.get('枠番') or math.ceil(bango / 2)
    rows.append({
        '入線順位': int(r['入線順位']), '馬番': bango, '枠番': waku,
        '馬名': name,
        '人気': (int(r['人気']) if pd.notna(r['人気']) and str(r['人気']).replace('.','').isdigit() else None),
        '単勝オッズ': (float(r['単勝オッズ']) if pd.notna(r['単勝オッズ']) and str(r['単勝オッズ']) not in ('取消し','----','---','') else None),
        '決め手': str(r['決め手']).strip(), 'タイム': str(r['タイム']).strip(),
        '着差': str(r['着差']).strip() if pd.notna(r['着差']) else '0',
        '上り3F': (float(r['上り3F']) if pd.notna(r['上り3F']) and str(r['上り3F']) not in ('----','---','') else None),
        '通過1': (int(float(r['通過1'])) if pd.notna(r['通過1']) and str(r['通過1']) not in ('----','---','') else None),
        '通過2': (int(float(r['通過2'])) if pd.notna(r['通過2']) and str(r['通過2']) not in ('----','---','') else None),
        '通過3': (int(float(r['通過3'])) if pd.notna(r['通過3']) and str(r['通過3']) not in ('----','---','') else None),
        '通過4': (int(float(r['通過4'])) if pd.notna(r['通過4']) and str(r['通過4']) not in ('----','---','') else None),
        '体重': (int(float(r['体重'])) if pd.notna(r['体重']) and str(r['体重']) not in ('取消し','----','---','') else None),
        '増減': (int(float(r['増減'])) if pd.notna(r['増減']) and str(r['増減']) not in ('取消し','----','---','') else None),
        '予想順位': p.get('予想順位'), 'スコア': p.get('スコア'),
        '予想脚質': p.get('脚質', ''),
        '複勝下限': p.get('複勝下限'), '複勝上限': p.get('複勝上限'),
        '過去走なし': p.get('過去走なし', False),
    })

# ── 1着からの着差タイム計算（タイム列から直接算出）──────────────
def _parse_race_time(s):
    """タイム文字列を秒に変換: '1.48.3'→108.3, '34.5'→34.5"""
    if not s or str(s).strip() in ('', 'nan', 'None', '---'):
        return None
    s = str(s).strip()
    parts = s.split('.')
    try:
        if len(parts) == 3:          # 1.48.3 = 1分48秒3
            return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 10
        elif len(parts) == 2:        # 34.5 = 34.5秒
            return int(parts[0]) + int(parts[1]) / 10
    except (ValueError, IndexError):
        pass
    return None

# 1着の実走タイムを基準に各馬の着差_sec（実秒）を設定
_winner_time = None
for _r in rows:
    if _r['入線順位'] == 1:
        _winner_time = _parse_race_time(_r.get('タイム', ''))
        break

for _r in rows:
    _t = _parse_race_time(_r.get('タイム', ''))
    if _t is not None and _winner_time is not None:
        _r['着差_sec'] = round(_t - _winner_time, 1)
    else:
        _r['着差_sec'] = 99.0

# 全馬上り3F最速値（次走ヒント用）
_agari_best_val = min((r['上り3F'] for r in rows if r.get('上り3F') is not None), default=99)

def _str(v):
    """NaN/None を空文字に、それ以外は str に変換"""
    import math as _math
    if v is None: return ''
    try:
        if _math.isnan(float(v)): return ''
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return '' if s.lower() == 'nan' else s

race = {
    'レース名': _str(meta['レース名']), '場所': _str(meta['場所']),
    '距離': int(meta['距離']), '芝ダ': str(meta['芝・ダート']).strip(),
    '天候': str(meta['天候']).strip(), '馬場': str(meta['馬場状態']).strip(),
    '頭数': int(meta['頭数']), '前半3F': float(meta['通過3F']),
    '後半3F': float(meta['上り3F']), 'PCI': float(meta['レースPCI']),
    '前後差': float(meta['前後3F差']), '最速上3F': float(meta['最速上3F']),
    '通過ラップ': str(meta['通過ラップ表記']).strip(),
    '上りラップ': str(meta['上りラップ表記']).strip(),
    '1着タイム': str(res[res['入線順位']==1].iloc[0]['タイム']).strip(),
    'R': str(int(meta['R'])) if pd.notna(meta.get('R')) else '',
    'クラス名': str(meta.get('クラス名', '')).strip(),
    '年': str(int(meta['年'])), '月': str(int(meta['月'])), '日': str(int(meta['日'])),
}

data_js = json.dumps(rows, ensure_ascii=False)
race_js  = json.dumps(race, ensure_ascii=False)
pci = race['PCI']
pace_label = 'ハイペース（前傾）' if pci < 50 else 'スローペース（後傾）' if pci > 55 else 'ミドルペース'
pace_color = '#e74c3c' if pci < 48 else '#3498db' if pci > 53 else '#f39c12'
sa = race['前後差']


# ── 改善点パネル 自動生成 ───────────────────────────────────────
def _item(icon, title, body):
    return (f'<div class="improve-item">'
            f'<div class="improve-title">{icon} {title}</div>'
            f'<div class="improve-body">{body}</div></div>')

_improve_items = []
# rows は取消馬除外済みのリスト（辞書形式）を入線順にソート
_pred_rows = [(r, pred_map.get(r['馬名'], {})) for r in sorted(rows, key=lambda x: x['入線順位'])]

# ① 的中：予想上位3頭 × 実際3着以内
_hits = [(r, p) for r, p in _pred_rows
         if int(r['入線順位']) <= 3 and p.get('予想順位') and int(p['予想順位']) <= 3]
if _hits:
    _hit_str = '・'.join(f"{r['馬名']}（予想{int(p['予想順位'])}位→実際{int(r['入線順位'])}着）"
                         for r, p in sorted(_hits, key=lambda x: int(x[1]['予想順位'])))
    _improve_items.append(_item('✓', f'的中：上位予想の{len(_hits)}頭が3着内に好走', _hit_str + ' を正しく上位評価できた。'))
else:
    _improve_items.append(_item('△', '的中なし：予想上位3頭に3着内馬なし',
        '上位3頭以外から3着内が出た。スコア上位グループの拡大や人気との比較分析が有効かもしれない。'))

# ② 大外れ（予想上位5頭で着順が8着以下）
_misses = [(r, p) for r, p in _pred_rows
           if p.get('予想順位') and int(p['予想順位']) <= 5 and int(r['入線順位']) >= 8]
for r, p in sorted(_misses, key=lambda x: int(x[1]['予想順位'])):
    diff = int(r['入線順位']) - int(p['予想順位'])
    _improve_items.append(_item('⚠', f"課題：{r['馬名']}（予想{int(p['予想順位'])}位→実際{int(r['入線順位'])}着, +{diff}）",
        f"脚質:{r['決め手']} 上り3F:{r['上り3F']}秒。スコアが過大評価だった可能性。補正要因を回顧で確認してください。"))

# ③ 見落とし（予想6位以下が実際3着以内）
_surprises = [(r, p) for r, p in _pred_rows
              if int(r['入線順位']) <= 3 and (not p.get('予想順位') or int(p['予想順位']) > 5)]
for r, p in _surprises:
    pred_str = f"予想{int(p['予想順位'])}位" if p.get('予想順位') else '予想対象外'
    _improve_items.append(_item('⚠', f"見落とし：{r['馬名']}（{pred_str}→実際{int(r['入線順位'])}着）",
        f"脚質:{r['決め手']} 上り3F:{r['上り3F']}秒。スコアが過小評価だった可能性。臨戦・調教・コース適性補正を再確認。"))

# ④ 脚質傾向（取消馬除外済みrowsを使用）
_top5 = pd.DataFrame([r for r in rows if r['入線順位'] <= 5])
_style_cnt = _top5['決め手'].value_counts() if not _top5.empty else pd.Series(dtype=str)
_style_str = '・'.join(f"{s}:{c}頭" for s, c in _style_cnt.items())
_pace_str = f"PCI={race['PCI']:.1f}（{pace_label}）"
_improve_items.append(_item('📌', f'脚質傾向：{_pace_str}', f'5着以内の脚質構成：{_style_str}。ペース予測と実際の脚質傾向を次回に活かすこと。'))

# ⑤ 臨戦補正の有効性（臨戦pts <= -5 の馬が実際に下位か確認）
_sc_df = None
try:
    import pandas as _pd
    _sc_df = _pd.read_csv(args.scores)
    _heavy_pen = _sc_df[_sc_df['臨戦pts'] <= -5][['馬名','臨戦pts']]
    for _, hp in _heavy_pen.iterrows():
        _actual_rank = res[res['馬名'] == hp['馬名']]['入線順位'].values
        if len(_actual_rank):
            _ar = int(_actual_rank[0])
            _valid = '✓ リスク評価が有効（下位に沈んだ）' if _ar >= 10 else '△ 補正を受けたが好走'
            _improve_items.append(_item('📋',
                f"長期休養明け補正({hp['馬名']}  臨戦{int(hp['臨戦pts'])}pt→{_ar}着）",
                f"{_valid}。"))
except Exception:
    pass

# ── 改善点パネル KPI統計ブロック ──────────────────────────────────
_pw = [(r, pred_map.get(r['馬名'], {})) for r in rows
       if pred_map.get(r['馬名'], {}).get('予想順位')]
_top3_pred    = [(r, p) for r, p in _pw if int(p['予想順位']) <= 3]
_top3_hit     = sum(1 for r, p in _top3_pred if r['入線順位'] <= 3)
_honmei_rank  = next((r['入線順位'] for r, p in _pw if int(p['予想順位']) == 1), None)
_avg_err      = (sum(abs(int(p['予想順位']) - r['入線順位']) for r, p in _pw) / len(_pw)) if _pw else None
_top5_pred    = [(r, p) for r, p in _pw if int(p['予想順位']) <= 5]
_top5_avg_rank = (sum(r['入線順位'] for r, p in _top5_pred) / len(_top5_pred)) if _top5_pred else None

def _kc(v, good, ok):
    """KPI color helper: green/yellow/red"""
    if v is None: return '#7f8c8d'
    return '#2ecc71' if v <= good else '#f39c12' if v <= ok else '#e74c3c'

_hit_color = '#2ecc71' if _top3_hit >= 2 else '#f39c12' if _top3_hit == 1 else '#e74c3c'
_hm_color  = '#2ecc71' if _honmei_rank and _honmei_rank <= 3 else '#f39c12' if _honmei_rank and _honmei_rank <= 5 else '#e74c3c'
_hm_txt    = str(_honmei_rank) + '着' if _honmei_rank else '—'
_err_txt   = f'{_avg_err:.1f}位' if _avg_err is not None else '—'
_t5_txt    = f'{_top5_avg_rank:.1f}着' if _top5_avg_rank is not None else '—'

_kpi_html = (
    '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px">'
    f'<div class="kpi"><div class="kpi-val" style="color:{_hit_color}">{_top3_hit}/3</div>'
    '<div class="kpi-lbl">予想上位3頭<br>3着内的中数</div></div>'
    f'<div class="kpi"><div class="kpi-val" style="color:{_hm_color}">{_hm_txt}</div>'
    '<div class="kpi-lbl">本命馬（予想1位）<br>実際着順</div></div>'
    f'<div class="kpi"><div class="kpi-val" style="color:{_kc(_avg_err, 2, 4)}">{_err_txt}</div>'
    '<div class="kpi-lbl">全馬平均<br>着順誤差</div></div>'
    f'<div class="kpi"><div class="kpi-val" style="color:{_kc(_top5_avg_rank, 4, 6)}">{_t5_txt}</div>'
    '<div class="kpi-lbl">予想上位5頭<br>平均実際着順</div></div>'
    '</div>'
)

improve_html = '<div class="section"><h2>&#128161; 次回への改善点</h2>' + _kpi_html + ''.join(_improve_items) + '</div>'

# ── ピックアップ馬パネル生成 ─────────────────────────────────────
def _find_pickup_horses(rows, race):
    """展開不利・末脚光った馬（次走注目）を厳選して最大3頭抽出する"""
    pci = race['PCI']
    n   = race['頭数']
    front_styles = {'逃げ', '先行'}
    rear_styles  = {'差し', '追込', '後方', '中団'}

    top3 = [r for r in rows if r['入線順位'] <= 3]
    top3_front = sum(1 for r in top3 if r['決め手'] in front_styles)
    top3_rear  = sum(1 for r in top3 if r['決め手'] in rear_styles)

    # ── 展開タイプ判定（PCI境界を対称化・厳格化） ──────────────────
    # 前有利: 逃げ/先行が3着内に2頭以上 OR 明確スロー(PCI>57)かつ1頭以上
    #         OR 3着内が全員前め(top3_front==3)で圧倒的前有利
    is_front_race = (
        (top3_front >= 2) or
        (pci > 57 and top3_front >= 1) or
        (top3_front == 3)
    )
    # 後方有利: 差し/追込が3着内に2頭以上 OR 明確ハイ(PCI<43)かつ1頭以上
    #           OR 3着内が全員後ろめ(top3_rear==3)で圧倒的後方有利
    is_rear_race = (
        (top3_rear >= 2) or
        (pci < 43 and top3_rear >= 1) or
        (top3_rear == 3)
    )

    # 全馬の上り3F ソート（小さい=速い）
    agari_list = sorted([r['上り3F'] for r in rows if r.get('上り3F') is not None])
    top25_threshold = agari_list[max(0, len(agari_list)//4 - 1)] if agari_list else 99  # 上位25%
    top33_threshold = agari_list[max(0, len(agari_list)//3 - 1)] if agari_list else 99  # 上位33%
    agari_best = agari_list[0] if agari_list else 99

    candidates = []
    for r in rows:
        pos  = r['入線順位']
        if pos <= 3:            continue   # 3着内は既に評価済み
        if pos > min(9, n//2):  continue   # 後半グループは除外（10着以降も除外）
        if r.get('過去走なし'):  continue   # 参考スコア馬は除外

        style   = r['決め手']
        agari   = r.get('上り3F')
        c4      = r.get('通過4')
        pred    = r.get('予想順位') or pos
        gap_sec = r.get('着差_sec', 99.0)
        score   = 0
        reasons = []
        has_main = False   # ①展開不利 or ②上位末脚 のどちらかが必須

        # ── 判定①: 展開の向かい風の中で好走（メイン判定） ───────────
        if is_front_race and style in rear_styles:
            score += 3
            has_main = True
            reasons.append(
                f"前有利の流れ（先行勢が3着内を占拠）にもかかわらず、{style}策で{pos}着に食い込む")
        elif is_rear_race and style in front_styles:
            score += 3
            has_main = True
            reasons.append(
                f"後方有利の流れ（差し・追込勢が台頭）の中、{style}策から{pos}着まで粘り込む")

        # ── 判定②: フィールド上位の上り3F（メイン判定） ──────────────
        if agari is not None:
            if agari == agari_best:
                score += 3
                has_main = True
                reasons.append(f"上り3F {agari}秒はこのレースの最速タイム")
            elif agari <= top25_threshold:
                score += 2
                has_main = True
                reasons.append(f"上り3F {agari}秒（出走馬の上位4分の1に入る鋭い末脚）")
            elif agari <= top33_threshold:
                score += 1
                reasons.append(f"上り3F {agari}秒（出走馬の上位3分の1に入る末脚）")

        # ── 判定③: 4角から大幅追い込み ──────────────────────────────
        if c4 is not None and pos is not None:
            gained = c4 - pos
            # 頭数比で相対評価（大きく上がるほど高評価）
            if gained >= max(6, int(n * 0.4)):
                score += 3
                reasons.append(f"4角{c4}番手から直線で{gained}頭をかわして{pos}着（大幅追い込み）")
            elif gained >= 4:
                score += 2
                reasons.append(f"4角{c4}番手から{gained}頭差し切って{pos}着")
            elif gained >= 2:
                score += 1
                reasons.append(f"4角{c4}番手から直線で{gained}頭分ポジションを上げて{pos}着")

        # ── 判定④: 低評価から大幅に上回る好走 ──────────────────────
        if pred and pos:
            outperform = int(pred) - int(pos)
            if outperform >= 7:
                score += 2
                reasons.append(f"予想{pred}位と低評価だったが{pos}着に大幅上回る好走")
            elif outperform >= 4:
                score += 1
                reasons.append(f"予想{pred}位から{pos}着と評価以上の走り")

        # ── 判定⑤: 前め脚質でも速い上り（スタミナ証明） ────────────
        if style in front_styles and agari is not None and agari <= top33_threshold:
            if score > 0:
                score += 1
                reasons.append(
                    f"{style}で前半を消耗しながらも上り3F {agari}秒の末脚を維持（スタミナ面で優秀）")

        # ── 判定⑥: 1着との着差（補助判定・単独では候補入り不可） ────
        # 着差だけでメイン判定なしの場合はスキップ
        if gap_sec <= 0.1:
            score += 3
            reasons.append(f"1着との差はわずか{gap_sec:.1f}秒（ほぼ差なし）。展開の不利を吸収した内容")
        elif gap_sec <= 0.3:
            score += 2
            reasons.append(f"1着と{gap_sec:.1f}秒差の僅差。着順以上に中身のある競馬")
        elif gap_sec <= 0.5:
            score += 1
            reasons.append(f"1着と{gap_sec:.1f}秒差。着順ほどの差はなく次走巻き返し圏内")

        # ── 候補入り条件（B案：メイン判定必須・閾値4点） ────────────
        # 必須: ①展開不利 or ②上位末脚（上位25%以内or最速）のどちらかが入っていること
        # 必須: 合計スコア4点以上
        if score >= 4 and has_main and reasons:
            candidates.append({'horse': r, 'score': score, 'reasons': reasons,
                                'agari_best': agari_best})

    # スコア降順、同点なら着順が良い馬を優先
    candidates.sort(key=lambda x: (-x['score'], x['horse']['入線順位']))

    # 最大3頭に厳選
    return candidates[:3]

_WAKU_BG = {1:'#fff',2:'#555',3:'#ee3333',4:'#4488ff',5:'#dddd00',6:'#22bb22',7:'#ff8822',8:'#ffaacc'}
_WAKU_FG = {1:'#111',2:'#eee',3:'#fff',4:'#fff',5:'#111',6:'#fff',7:'#111',8:'#111'}

def _pickup_html(candidates, race):
    if not candidates:
        return ''
    pci  = race['PCI']
    pace = 'ハイペース' if pci < 50 else 'スロー' if pci > 55 else 'ミドル'
    out  = (f'''<div class="section">
<h2>&#127919; 次走注目馬ピックアップ</h2>
<div class="pickup-note">
  このレースの展開（PCI={pci:.1f}・{pace}ペース）を考慮し、
  <b>不利な流れの中でも底力を発揮した馬</b>をピックアップしました。<br>
  次走でペースや位置取りが好転した際に、さらなる上積みが期待できます。
</div>''')
    for c in candidates:
        r  = c['horse']
        wb = _WAKU_BG.get(r['枠番'], '#888')
        wf = _WAKU_FG.get(r['枠番'], '#fff')
        reason_lines = '<br>'.join(f'・{rs}' for rs in c['reasons'])
        _gap = r.get('着差_sec')
        _gap_str = f' ／ 1着と<b style="color:#f39c12">{_gap:.1f}秒差</b>' if (_gap is not None and _gap < 99.0) else ''

        # ── 次走条件ヒント自動生成 ──────────────────────────────
        _hints = []
        _wt = r.get('増減')
        if _wt is not None:
            if _wt > 8:
                _hints.append(f'前走+{_wt}kg増量。馬体が絞れれば次走で上積みが期待できる。')
            elif _wt < -8:
                _hints.append(f'前走{_wt}kg減量。体重が戻れば本来の力が発揮される可能性あり。')
        _agari = r.get('上り3F')
        _ab = c.get('agari_best', 99)
        if _agari is not None and _agari == _ab:
            _hints.append('末脚は今回レース最速。直線の長いコースやスローペースでさらに活きる。')
        _c4v = r.get('通過4')
        _posv = r['入線順位']
        if _c4v is not None and (_c4v - _posv) >= 4:
            _hints.append('直線での追い込み力が際立つ。差しが決まりやすいコース・ペースで注目。')
        _gv = r.get('着差_sec', 99.0)
        if _gv is not None and _gv <= 0.5:
            _hints.append(f'1着と{_gv:.1f}秒差の僅差。展開が向けば勝ち負け可能なポテンシャル。')
        hint_html = (
            '<div style="margin-top:8px;padding:8px 10px;background:#1a2332;border-radius:6px;border-left:3px solid #27ae60">'
            '<div style="font-size:11px;color:#2ecc71;font-weight:700;margin-bottom:4px">🔍 次走注目ポイント</div>'
            + '<br>'.join(f'<span style="font-size:11px;color:#bdc3c7">・{h}</span>' for h in _hints)
            + '</div>'
        ) if _hints else ''

        out += f'''<div class="pickup-card">
  <div class="pickup-header">
    <div class="waku-pill" style="background:{wb};color:{wf};">{r['枠番']}枠{r['馬番']}番</div>
    <div class="pickup-name"><b>{r['馬名']}</b></div>
    <div class="pickup-meta">{r['入線順位']}着 ／ {r['決め手']} ／ 上り3F {r['上り3F']}秒{_gap_str} ／ {r['人気']}人気 {r['単勝オッズ']}倍</div>
  </div>
  <div class="pickup-reason">{reason_lines}</div>
  {hint_html}
</div>'''
    out += '</div>'
    return out

_pickup_candidates = _find_pickup_horses(rows, race)
pickup_html = _pickup_html(_pickup_candidates, race)

# ── 次走注目メモセクション生成 ──────────────────────────────────
# ピックアップ候補の馬名セット（初期選択状態にする）
_pickup_names = {c['horse']['馬名'] for c in _pickup_candidates}
# 着順順に全馬リスト（着順でソート済みの rows を利用）
_memo_rows_sorted = sorted(rows, key=lambda x: x['入線順位'])

def _memo_section_html(memo_rows, pickup_names, race):
    """次走注目メモ管理セクションのHTMLを生成"""
    _r = race
    _date_str = f"{_r['年']}/{int(_r['月']):02d}/{int(_r['日']):02d}"
    _place = _r.get('場所','')
    _rnum  = _r.get('R','')
    _rname = _r.get('レース名','')
    _cls   = _r.get('クラス名','')
    # JS埋め込み用のレース情報JSON
    _race_info_js = json.dumps({
        '日付': _date_str,
        '場所': _place,
        'R':    int(_rnum) if str(_rnum).isdigit() else _rnum,
        'レース名': _rname if str(_rname) not in ('nan','None','') else '',
        'クラス': _cls,
    }, ensure_ascii=False)
    # 馬リスト（初期選択フラグ付き）
    _horse_chips = ''
    for r in memo_rows:
        name = r['馬名']
        rank = r['入線順位']
        checked = 'true' if name in pickup_names else 'false'
        pre_class = ' memo-pre-selected' if name in pickup_names else ''
        _horse_chips += (
            f'<div class="memo-chip{pre_class}" id="chip-{name}" '
            f'data-name="{name}" data-rank="{rank}" data-selected="{checked}" '
            f'onclick="toggleMemoChip(this)">'
            f'<span class="memo-chip-rank">{rank}着</span>'
            f'<span class="memo-chip-name">{name}</span>'
            + ('<span class="memo-chip-auto">★ 自動</span>' if name in pickup_names else '')
            + '</div>'
        )
    return f'''<div class="section" id="memo-section">
<h2>&#128204; 次走注目馬メモ</h2>
<div style="font-size:12px;color:#bdc3c7;margin-bottom:12px;line-height:1.7;
     padding:10px;background:#0d1117;border-radius:6px;border-left:3px solid #8e44ad">
  ★印はシステムが自動ピックアップした馬です。クリックで選択・解除できます。<br>
  選択後「メモに保存」ボタンを押すと <b>memo_horses.json</b> に追記されます。
</div>
<div id="memo-chips" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px">
  {_horse_chips}
</div>
<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
  <button onclick="saveMemoToFile({_race_info_js})"
     style="padding:8px 20px;background:linear-gradient(135deg,#8e44ad,#6c3483);
            color:#fff;border:none;border-radius:6px;font-size:13px;font-weight:700;
            cursor:pointer;box-shadow:0 0 8px rgba(142,68,173,0.4)">
    &#128204; メモに保存（memo_horses.json へ書き込み）
  </button>
  <button onclick="selectAllMemo(true)"
     style="padding:6px 14px;background:#243447;color:#bdc3c7;border:1px solid #2c3e50;
            border-radius:5px;font-size:12px;cursor:pointer">全選択</button>
  <button onclick="selectAllMemo(false)"
     style="padding:6px 14px;background:#243447;color:#bdc3c7;border:1px solid #2c3e50;
            border-radius:5px;font-size:12px;cursor:pointer">全解除</button>
  <span id="memo-save-msg" style="font-size:12px;color:#2ecc71;display:none;margin-left:8px"></span>
</div>
<div id="memo-browser-warn" style="display:none;margin-top:10px;padding:8px 12px;
     background:#3a1a1a;border-radius:6px;font-size:12px;color:#e74c3c">
  ⚠ このブラウザはFile System Access APIに対応していません。<br>
  「JSONをダウンロード」ボタンでファイルを保存し、keiba-dashboardフォルダの
  memo_horses.jsonに手動でマージしてください。
  <br><button onclick="downloadMemoJson({_race_info_js})"
    style="margin-top:6px;padding:5px 12px;background:#c0392b;color:#fff;
           border:none;border-radius:4px;font-size:12px;cursor:pointer">
    JSONをダウンロード
  </button>
</div>
</div>
<script>
(function(){{
  var MEMO_RACE_INFO = {_race_info_js};
  // チップの選択状態切り替え
  window.toggleMemoChip = function(el) {{
    var sel = el.getAttribute('data-selected') === 'true';
    el.setAttribute('data-selected', sel ? 'false' : 'true');
    el.style.opacity = sel ? '0.4' : '1';
    el.style.boxShadow = sel ? 'none' : '0 0 0 2px #8e44ad';
  }};
  window.selectAllMemo = function(flag) {{
    document.querySelectorAll('.memo-chip').forEach(function(el) {{
      el.setAttribute('data-selected', flag ? 'true' : 'false');
      el.style.opacity = flag ? '1' : '0.4';
      el.style.boxShadow = flag ? '0 0 0 2px #8e44ad' : 'none';
    }});
  }};
  // 初期スタイル適用
  document.querySelectorAll('.memo-chip').forEach(function(el) {{
    var sel = el.getAttribute('data-selected') === 'true';
    el.style.opacity = sel ? '1' : '0.4';
    el.style.boxShadow = sel ? '0 0 0 2px #8e44ad' : 'none';
  }});
  // 選択馬を収集してエントリ配列を返す
  function collectEntries(raceInfo) {{
    var today = new Date().toISOString().slice(0,10);
    var entries = [];
    document.querySelectorAll('.memo-chip[data-selected="true"]').forEach(function(el) {{
      entries.push({{
        '馬名':   el.getAttribute('data-name'),
        '登録日': today,
        '元レース': raceInfo,
        'メモ': ''
      }});
    }});
    return entries;
  }}
  // File System Access API で memo_horses.json に追記保存
  window.saveMemoToFile = async function(raceInfo) {{
    if (!window.showOpenFilePicker) {{
      document.getElementById('memo-browser-warn').style.display = 'block';
      return;
    }}
    var newEntries = collectEntries(raceInfo);
    if (!newEntries.length) {{
      alert('注目馬が選択されていません。');
      return;
    }}
    try {{
      var [fh] = await showOpenFilePicker({{
        types: [{{ description: 'JSON', accept: {{'application/json': ['.json']}} }}],
        multiple: false
      }});
      var f = await fh.getFile();
      var existing = [];
      try {{ existing = JSON.parse(await f.text()); }} catch(e) {{ existing = []; }}
      // 同レースの同名馬は重複登録しない
      var existingKeys = new Set(existing.map(function(e) {{
        return e['馬名'] + '|' + (e['元レース']||{{}})['日付'] + '|' + (e['元レース']||{{}})['R'];
      }}));
      newEntries.forEach(function(e) {{
        var key = e['馬名'] + '|' + (e['元レース']||{{}})['日付'] + '|' + (e['元レース']||{{}})['R'];
        if (!existingKeys.has(key)) {{ existing.push(e); }}
      }});
      var writable = await fh.createWritable();
      await writable.write(JSON.stringify(existing, null, 2));
      await writable.close();
      var msg = document.getElementById('memo-save-msg');
      msg.textContent = '✅ ' + newEntries.length + '頭を保存しました！';
      msg.style.display = 'inline';
      setTimeout(function(){{ msg.style.display='none'; }}, 4000);
    }} catch(e) {{
      if (e.name !== 'AbortError') alert('保存エラー: ' + e.message);
    }}
  }};
  // フォールバック: JSONダウンロード
  window.downloadMemoJson = function(raceInfo) {{
    var entries = collectEntries(raceInfo);
    var blob = new Blob([JSON.stringify(entries, null, 2)], {{type:'application/json'}});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'memo_additions.json';
    a.click();
  }};
}})();
</script>'''

memo_section_html = _memo_section_html(_memo_rows_sorted, _pickup_names, race)

# ── 日付・ファイル名 動的生成 ──────────────────────────────────
import datetime as _dt, re as _re2
_rd = _dt.date(int(race['年']), int(race['月']), int(race['日']))
_dow = ['月','火','水','木','金','土','日'][_rd.weekday()]
race_date_str  = f"{_rd.year}年{_rd.month}月{_rd.day}日（{_dow}）"
race_date_short = f"{_rd.year}/{_rd.month:02d}/{_rd.day:02d}"

# ── HTML生成 ──────────────────────────────────────────────────
race_name = race['レース名']
_display_name = (race_name if race_name and str(race_name) not in ('nan','None','')
                 else f"{race['場所']}{race.get('R','')}R {race.get('クラス名','')}")
lap_h1 = race['前半3F'] * 18
lap_h2 = race['後半3F'] * 18

# 券種別 結果照合パネル（pred HTMLのEV_DATA + 確定配当で照合）
try:
    import bet_recon as _br
    import os as _osbt
    _rid_bt = _osbt.path.splitext(_osbt.path.basename(args.result))[0].replace('レース結果_', '').replace('レース結果', '')
    _outdir_bt = args.outdir or _osbt.path.dirname(_osbt.path.abspath(args.result))
    bettype_panel_html = _br.build_panel_for_review(_rid_bt, _outdir_bt, res, _payouts)
except Exception as _bte:
    bettype_panel_html = ''

head = f"""<!DOCTYPE html>
<html lang="ja"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&display=swap" rel="stylesheet">
<title>レース回顧 {_display_name} {race_date_short}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d1117;color:#e0e0e0;
      font-family:"Noto Sans JP","Hiragino Kaku Gothic ProN","Yu Gothic UI","Yu Gothic",Meiryo,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      font-size:14px;line-height:1.5;padding:16px;max-width:1100px;margin:0 auto}}
h1{{font-size:24px;color:#f1c40f;margin-bottom:4px;font-weight:700}} .subtitle{{font-size:13px;color:#7f8c8d;margin-bottom:20px}}
h2{{font-size:18px;color:#f1c40f;margin-bottom:12px;border-left:3px solid #f1c40f;padding-left:8px;font-weight:700}}
.section{{background:#1a2332;border-radius:10px;padding:16px;margin-bottom:16px}}
.grid3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}}
.kpi{{background:#0d1117;border-radius:8px;padding:12px;text-align:center}}
.kpi-val{{font-size:26px;font-weight:700;color:#f1c40f}} .kpi-lbl{{font-size:11px;color:#7f8c8d;margin-top:2px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{background:#243447;color:#7f8c8d;padding:7px 8px;text-align:left;border-bottom:1px solid #2c3e50;white-space:nowrap}}
td{{padding:7px 8px;border-bottom:1px solid #1e2d3d;vertical-align:middle}}
tr:hover td{{background:#1f2f42}}
.hit{{color:#2ecc71;font-weight:700}} .miss{{color:#e74c3c}} .mid{{color:#f39c12}}
.badge{{display:inline-block;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600}}
.chart-wrap-lg{{position:relative;height:420px}} .note{{font-size:11px;color:#7f8c8d;margin-top:8px;line-height:1.6}}
.improve-item{{background:#0d1117;border-radius:6px;padding:10px 12px;margin-bottom:8px;border-left:3px solid #f39c12}}
.improve-title{{font-weight:700;color:#f1c40f;font-size:13px;margin-bottom:4px}}
.improve-body{{font-size:12px;color:#bdc3c7;line-height:1.6}}
.lap-row{{display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:13px}}
.lap-seg{{height:20px;border-radius:3px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:11px;font-weight:600;min-width:60px}}
.corner-legend{{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;padding:10px;background:#0d1117;border-radius:6px}}
.legend-item{{display:flex;align-items:center;gap:5px;font-size:11px;color:#bdc3c7}}
.waku-circle{{width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;flex-shrink:0;border:1px solid #333}}
.ev-pos{{color:#2ecc71;font-weight:700}} .ev-neg{{color:#e74c3c}}
.ev-summary{{display:flex;gap:12px;margin-bottom:10px;flex-wrap:wrap}}
.ev-card{{background:#0d1117;border-radius:6px;padding:8px 14px;font-size:12px;flex:1;min-width:140px}}
.ev-card-val{{font-size:20px;font-weight:700;color:#f1c40f}} .ev-card-lbl{{color:#7f8c8d;font-size:11px;margin-top:2px}}
.pickup-note{{font-size:12px;color:#bdc3c7;line-height:1.7;margin-bottom:14px;padding:10px;background:#0d1117;border-radius:6px;border-left:3px solid #9b59b6}}
.pickup-card{{background:#0d1117;border-radius:8px;padding:12px 14px;margin-bottom:10px;border-left:4px solid #9b59b6}}
.pickup-header{{display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap}}
.pickup-name{{font-size:15px;font-weight:700;color:#e0e0e0}}
.pickup-meta{{font-size:11px;color:#7f8c8d;margin-left:auto}}
.waku-pill{{padding:2px 8px;border-radius:10px;font-size:11px;font-weight:700;border:1px solid #333}}
.pickup-reason{{font-size:12px;color:#bdc3c7;line-height:1.8;padding-left:4px}}
.memo-chip{{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:8px;
  background:#243447;border:1px solid #2c3e50;cursor:pointer;transition:all 0.15s;
  font-size:12px;color:#e0e0e0;user-select:none}}
.memo-chip:hover{{background:#2c3e50}}
.memo-chip-rank{{font-size:11px;color:#7f8c8d;min-width:24px}}
.memo-chip-name{{font-weight:700}}
.memo-chip-auto{{font-size:10px;color:#f1c40f;font-weight:700;margin-left:2px}}
.memo-pre-selected{{border-color:#8e44ad}}
</style></head><body>
<h1>&#127943; レース回顧 &#8212; {_display_name}</h1>
<div class="subtitle">{race_date_str}・{race['場所']}競馬場 {race['芝ダ']}{race['距離']}m ・{race['クラス名']} ・{race['頭数']}頭立て</div>
<div class="section"><h2>&#128203; レース概要</h2>
  <div class="grid3" style="margin-bottom:14px">
    <div class="kpi"><div class="kpi-val">{race['1着タイム']}</div><div class="kpi-lbl">勝ちタイム</div></div>
    <div class="kpi"><div class="kpi-val" style="color:{pace_color}">{pace_label}</div><div class="kpi-lbl">ペース判定（PCI={pci}）</div></div>
    <div class="kpi"><div class="kpi-val">{race['天候']} / {race['馬場']}</div><div class="kpi-lbl">天候 / 馬場状態</div></div>
  </div>
  <div style="margin-bottom:10px">
    <div style="font-size:12px;color:#7f8c8d;margin-bottom:6px">ラップ構成（600m区間）</div>
    <div class="lap-row"><span style="width:60px;color:#7f8c8d;font-size:12px">前半3F</span>
      <div class="lap-seg" style="width:{lap_h1:.0f}px;background:#e74c3c">{race['前半3F']}秒</div></div>
    <div class="lap-row"><span style="width:60px;color:#7f8c8d;font-size:12px">後半3F</span>
      <div class="lap-seg" style="width:{lap_h2:.0f}px;background:#3498db">{race['後半3F']}秒</div></div>
    <div style="font-size:11px;color:#7f8c8d;margin-top:4px">前後差 +{sa:.1f}秒 ／最速上がり {race['最速上3F']:.1f}秒</div>
  </div>
  <div style="font-size:12px;color:#7f8c8d">通過ラップ: {race['通過ラップ']} → 上りラップ: {race['上りラップ']}</div>
</div>
<div class="section"><h2>&#128202; 全馬成績詳細</h2>
  <div style="overflow-x:auto"><table>
    <thead><tr><th>着順</th><th>枠/馬番</th><th>馬名</th><th>人気/単勝</th><th>決め手</th><th>走破タイム</th><th>通過順位</th><th>上り3F</th><th>予想順位</th><th>スコア</th><th>順位差</th><th>予想精度</th></tr></thead>
    <tbody id="detailBody"></tbody>
  </table></div>
</div>
{bettype_panel_html}
<div class="section"><h2>&#128205; コーナー通過順の変化</h2>
  <div class="chart-wrap-lg"><canvas id="cornerChart"></canvas></div>
  <div class="corner-legend" id="cornerLegend"></div>
  <div class="note">各馬の1〜4コーナー通過順位と最終着順の推移。円の色は枠番カラー、数字は馬番。値が小さいほど前のポジション。</div>
</div>
<div class="section"><h2>&#9889; 上がり3F比較（速い順）</h2>
  <div id="agariViz" style="padding:4px 0"></div>
  <div class="note">バーが長いほど末脚が速い（最速: {race['最速上3F']:.1f}秒）。色は枠番カラー、右の数字は実際の着順。</div>
</div>
<div class="section"><h2>&#128176; 期待値分析（予測勝率 vs 市場オッズ）</h2>
  <div class="ev-summary" id="evSummary"></div>
  <div style="overflow-x:auto" id="evTableWrap"></div>
  <div class="note">予測勝率 = スコアをsoftmax変換（温度T=20）した確率。市場確率 = 1÷単勝オッズ。<br>期待値 = 予測勝率 × 単勝オッズ − 1（プラスなら理論上のプラスEV馬）。過去走データなし等の理由で予想対象外となった馬はこのパネルから除外されます。</div>
</div>
{improve_html}
{pickup_html}
{memo_section_html}"""


js = """
<script>
const DATA = """ + data_js + """;
const RACE = """ + race_js + """;
const WAKU_BG = {1:'#ffffff',2:'#555555',3:'#ee3333',4:'#4488ff',5:'#dddd00',6:'#22bb22',7:'#ff8822',8:'#ffaacc'};
const WAKU_FG = {1:'#111',2:'#eee',3:'#fff',4:'#fff',5:'#111',6:'#fff',7:'#111',8:'#111'};
function wBg(w){return WAKU_BG[w]||'#888';}
function wFg(w){return WAKU_FG[w]||'#fff';}
function rColor(r){return r===1?'#f1c40f':r<=3?'#2ecc71':r<=6?'#f39c12':'#7f8c8d';}
function lColor(l){return({'先行':'#f39c12','逃げ':'#e74c3c','差し':'#3498db','後方':'#9b59b6','中団':'#1abc9c'})[l]||'#7f8c8d';}

// コーナー通過順 カスタムプラグイン（枠番カラー + 馬番）
const bangoPlugin={id:'bangoPlugin',afterDatasetsDraw(chart){
  const ctx=chart.ctx;
  chart.data.datasets.forEach((ds,i)=>{
    const meta=chart.getDatasetMeta(i);
    const bg=wBg(ds.waku),fg=wFg(ds.waku);
    meta.data.forEach(pt=>{
      ctx.save();ctx.beginPath();ctx.arc(pt.x,pt.y,10,0,Math.PI*2);
      ctx.fillStyle=bg;ctx.fill();
      ctx.strokeStyle='#0d1117';ctx.lineWidth=1.5;ctx.stroke();
      ctx.fillStyle=fg;ctx.font='bold 8px sans-serif';
      ctx.textAlign='center';ctx.textBaseline='middle';
      ctx.fillText(ds.bango,pt.x,pt.y);ctx.restore();
    });
  });
}};

const cornerCtx=document.getElementById('cornerChart').getContext('2d');
// 有効なコーナー列を動的に判定（nullのみの列はスキップ）
const _cKeys=['通過1','通過2','通過3','通過4'];
const _cLbls=['1角','2角','3角','4角'];
const _activeCols=_cKeys.filter(k=>DATA.some(h=>h[k]!==null&&h[k]!==undefined));
const _chartLabels=[..._activeCols.map(k=>_cLbls[_cKeys.indexOf(k)]),'着順'];
const cornerDS=DATA.map(h=>{
  const w=h['枠番']||Math.ceil(h['馬番']/2);
  const pts=[..._activeCols.map(k=>h[k]),h['入線順位']];
  return{label:h['馬番']+'番 '+h['馬名'],bango:h['馬番'],waku:w,
    data:pts,
    borderColor:wBg(w),backgroundColor:'transparent',
    borderWidth:h['入線順位']<=3?3:1.2,pointRadius:0,tension:0.25};
});
new Chart(cornerCtx,{type:'line',
  data:{labels:_chartLabels,datasets:cornerDS},
  options:{responsive:true,maintainAspectRatio:false,
    scales:{
      y:{reverse:true,min:1,max:DATA.length,ticks:{color:'#7f8c8d',stepSize:2},grid:{color:'#2c3e50'},
         title:{display:true,text:'通過順位（小=前）',color:'#7f8c8d'}},
      x:{ticks:{color:'#bdc3c7',font:{size:13}},grid:{color:'#2c3e50'}}
    },
    plugins:{legend:{display:false},
      tooltip:{callbacks:{label:ctx=>`${ctx.dataset.label}: ${ctx.parsed.y}番手`}}}
  },plugins:[bangoPlugin]});

// 凡例
document.getElementById('cornerLegend').innerHTML=
  [...DATA].sort((a,b)=>a['馬番']-b['馬番']).map(h=>{
    const w=h['枠番']||Math.ceil(h['馬番']/2);
    return `<div class="legend-item"><div class="waku-circle" style="background:${wBg(w)};color:${wFg(w)}">${h['馬番']}</div><span>${h['馬名']}</span></div>`;
  }).join('');

// 上がり3F CSS棒グラフ
const agS=[...DATA].sort((a,b)=>a['上り3F']-b['上り3F']);
const minA=Math.min(...agS.map(h=>h['上り3F'])),maxA=Math.max(...agS.map(h=>h['上り3F']));
const rngA=maxA-minA||1;
document.getElementById('agariViz').innerHTML=agS.map((h,i)=>{
  const pct=((1-(h['上り3F']-minA)/rngA)*70+15).toFixed(0);
  const w=h['枠番']||Math.ceil(h['馬番']/2);
  const barBg=wBg(w);
  const barFg=wFg(w);
  // バーが短い(40%未満)場合はテキストをバー外(右側)に白で表示して視認性を確保
  const shortBar=Number(pct)<40;
  const timeLabel=`${h['上り3F'].toFixed(1)}秒${i===0?' ★最速':''}`;
  const innerSpan=shortBar?''
    :`<span style="position:absolute;left:10px;top:50%;transform:translateY(-50%);font-size:11px;color:${barFg};font-weight:700;text-shadow:0 0 3px rgba(0,0,0,0.5)">${timeLabel}</span>`;
  const outerSpan=shortBar
    ?`<span style="font-size:11px;color:#ecf0f1;font-weight:600;margin-left:4px;white-space:nowrap">${timeLabel}</span>`
    :'';
  return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">
    <div style="width:26px;height:26px;border-radius:50%;background:${barBg};color:${barFg};font-size:10px;font-weight:bold;display:flex;align-items:center;justify-content:center;flex-shrink:0;border:1.5px solid #444">${h['馬番']}</div>
    <div style="width:110px;font-size:11px;color:#bdc3c7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${h['馬名']}</div>
    <div style="flex:1;background:#243447;border-radius:4px;height:22px;position:relative;overflow:visible;display:flex;align-items:center">
      <div style="height:100%;width:${pct}%;background:${barBg};opacity:0.9;border-radius:4px;position:relative;flex-shrink:0">${innerSpan}</div>
      ${outerSpan}
    </div>
    <div style="width:32px;font-size:12px;color:${rColor(h['入線順位'])};font-weight:700;text-align:right">${h['入線順位']}着</div>
  </div>`;
}).join('');

// 期待値分析（参考スコアのみの馬＝過去走なしは除外してsoftmax計算）
const T=20;
const sc=DATA.filter(h=>h['スコア']!==null&&!h['過去走なし']&&h['単勝オッズ']>0);
const mxS=Math.max(...sc.map(h=>h['スコア']));
const ep=sc.map(h=>Math.exp((h['スコア']-mxS)/T));
const sm=ep.reduce((a,b)=>a+b,0);
sc.forEach((h,i)=>{h._p=ep[i]/sm;h._mp=1/h['単勝オッズ'];h._ev=h._p*h['単勝オッズ']-1;});
const evS=[...sc].sort((a,b)=>b._ev-a._ev);
const posEV=sc.filter(h=>h._ev>0);
const hit1=posEV.filter(h=>h['入線順位']===1);
const tb=posEV.length*100,tr2=hit1.reduce((s,h)=>s+h['単勝オッズ']*100,0);
const pf=(tr2-tb).toFixed(0),roi=tb>0?((tr2/tb-1)*100).toFixed(1):'—';
// 期待値判別成功の集計（2×2マトリクス）
const evByRatio0=[...sc].sort((a,b)=>(b._p/b._mp)-(a._p/a._mp));
const successEV=sc.filter(h=>(h._p/h._mp)>1&&h['入線順位']<h['人気']);
const overEV   =sc.filter(h=>(h._p/h._mp)>1&&h['入線順位']>=h['人気']);
const missEV   =sc.filter(h=>(h._p/h._mp)<=1&&h['入線順位']<h['人気']);
const cutEV    =sc.filter(h=>(h._p/h._mp)<=1&&h['入線順位']>=h['人気']);
const posCount =sc.filter(h=>(h._p/h._mp)>1).length;
const successRate=posCount>0?(successEV.length/posCount*100).toFixed(0):'—';
// 期待値判定成功 = ◎（高評価×好走）＋ ○（低評価×凡走）
const totalSuccess=successEV.length+cutEV.length;
const totalRate=(totalSuccess/sc.length*100).toFixed(0);
document.getElementById('evSummary').innerHTML=`
  <div class="ev-card"><div class="ev-card-val" style="color:#f1c40f">${totalSuccess}頭</div><div class="ev-card-lbl">期待値判定成功<br><small>◎高評価×好走 ＋ ○低評価×凡走</small></div></div>
  <div class="ev-card"><div class="ev-card-val" style="color:#f1c40f">${totalRate}%</div><div class="ev-card-lbl">期待値判定成功率<br><small>（全出走馬中）</small></div></div>
  <div class="ev-card"><div class="ev-card-val" style="color:#f1c40f">${successEV.length}頭</div><div class="ev-card-lbl">◎ 高評価×好走<br><small>確率比>1 かつ 人気超え好走</small></div></div>
  <div class="ev-card"><div class="ev-card-val" style="color:#2ecc71">${cutEV.length}頭</div><div class="ev-card-lbl">○ 低評価×凡走<br><small>確率比≤1 かつ 人気どおり凡走</small></div></div>
  <div class="ev-card"><div class="ev-card-val" style="color:#e74c3c">${overEV.length}頭</div><div class="ev-card-lbl">△ 過大評価<br><small>確率比>1 だが 人気どおり</small></div></div>
  <div class="ev-card"><div class="ev-card-val" style="color:#95a5a6">${missEV.length}頭</div><div class="ev-card-lbl">✕ 見落とし<br><small>確率比≤1 だが 人気超え好走</small></div></div>`;
// 確率比（予測÷市場）でソート：モデルが市場より高く評価した順
const evByRatio=[...sc].sort((a,b)=>(b._p/b._mp)-(a._p/a._mp));
const barMax=Math.max(...sc.map(h=>Math.max(h._p,h._mp)));
const legend2='<div style="display:flex;gap:16px;margin-bottom:10px;font-size:11px;color:#7f8c8d;flex-wrap:wrap">'
  +'<span style="display:flex;align-items:center;gap:5px"><span style="display:inline-block;width:28px;height:10px;border-radius:3px;background:#f1c40f"></span>予測勝率（モデル）</span>'
  +'<span style="display:flex;align-items:center;gap:5px"><span style="display:inline-block;width:28px;height:10px;border-radius:3px;background:#4a6080"></span>市場確率（1÷オッズ）</span>'
  +'<span style="margin-left:8px">確率比＝予測÷市場 / 1.0超＝モデルが市場より高く評価（黄背景）</span>'
  +'</div>';
const rows2=evByRatio.map(h=>{
  const ratio=h._p/h._mp;
  const isOver=ratio>1.0;
  const evPct=(h._ev*100).toFixed(1);
  const w=h['枠番']||Math.ceil(h['馬番']/2);
  const mk=h['入線順位']===1?'🥇':h['入線順位']===2?'🥈':h['入線順位']===3?'🥉':'';
  const pW=((h._p/barMax)*100).toFixed(1);
  const mW=((h._mp/barMax)*100).toFixed(1);
  // 人気以上に好走 = 入線順位 < 人気（市場期待以上のパフォーマンス）
  const outperform=h['入線順位']<h['人気'];
  // ◎ 高評価×好走 ／ ○ 低評価×凡走 → どちらも期待値判定成功
  const jdg=isOver&&outperform  ?'<b style="color:#f1c40f">◎期待値判定成功</b>'
            :!isOver&&!outperform?'<span style="color:#2ecc71;font-size:10px">○期待値判定成功</span>'
            :isOver&&!outperform ?'<span style="color:#e74c3c;font-size:10px">△過大評価</span>'
            :                    '<span style="color:#95a5a6;font-size:10px">✕見落とし</span>';
  const rc2=ratio>=1.5?'#f1c40f':ratio>=1.0?'#e8d07a':ratio>=0.7?'#7f8c8d':'#e74c3c';
  return '<div style="display:flex;align-items:center;gap:8px;margin-bottom:7px;padding:7px 10px;border-radius:7px;'
    +'background:'+(isOver?'rgba(241,196,15,0.07)':'rgba(255,255,255,0.02)')+'\">'
    +'<div style="width:26px;height:26px;border-radius:50%;background:'+wBg(w)+';color:'+wFg(w)
    +';font-size:10px;font-weight:bold;display:flex;align-items:center;justify-content:center;flex-shrink:0;border:1.5px solid #333">'+h['馬番']+'</div>'
    +'<div style="width:108px;font-size:12px;color:#e0e0e0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex-shrink:0"><b>'+h['馬名']+'</b></div>'
    +'<div style="flex:1;min-width:100px">'
      +'<div style="display:flex;align-items:center;gap:5px;margin-bottom:3px">'
        +'<div style="height:11px;background:#f1c40f;border-radius:2px;width:'+pW+'%;min-width:2px"></div>'
        +'<span style="font-size:10px;color:#f1c40f;white-space:nowrap">'+(h._p*100).toFixed(1)+'%</span>'
      +'</div>'
      +'<div style="display:flex;align-items:center;gap:5px">'
        +'<div style="height:11px;background:#4a6080;border-radius:2px;width:'+mW+'%;min-width:2px"></div>'
        +'<span style="font-size:10px;color:#7f8c8d;white-space:nowrap">'+(h._mp*100).toFixed(1)+'%</span>'
      +'</div>'
    +'</div>'
    +'<div style="width:54px;text-align:center;font-size:13px;font-weight:700;color:'+rc2+'">x'+ratio.toFixed(2)+'</div>'
    +'<div style="width:46px;text-align:right;font-size:11px;font-weight:700;color:'+(isOver?'#2ecc71':'#e74c3c')+'">'+(isOver?'+':'')+evPct+'%</div>'
    +'<div style="width:80px;text-align:right;font-size:11px;line-height:1.4">'
    +'<span style="color:#7f8c8d">'+h['人気']+'人気</span>'
    +'<span style="color:'+(outperform?'#2ecc71':'#e74c3c')+';font-weight:700"> → </span>'
    +'<span style="color:'+rColor(h['入線順位'])+';font-weight:700">'+mk+h['入線順位']+'着</span>'
    +'</div>'
    +'<div style="width:60px;text-align:center;font-size:11px">'+jdg+'</div>'
    +'</div>';
}).join('');
document.getElementById('evTableWrap').innerHTML=legend2+rows2;

// 全馬成績詳細
document.getElementById('detailBody').innerHTML=
  [...DATA].sort((a,b)=>a['入線順位']-b['入線順位']).map(h=>{
    const isTarget=h['スコア']!==null;
    const isRef=h['過去走なし']===true;  // 参考スコア（過去走データなし）
    const d=isTarget&&h['予想順位']?h['予想順位']-h['入線順位']:null;
    const ds=d===null?'—':d>0?'+'+d:d===0?'±0':String(d);
    const dc=d===null?'':d>=3?'class="hit"':d<=-3?'class="miss"':'class="mid"';
    const ev2=!isTarget?'<span style="font-size:10px;color:#7f8c8d">対象外</span>'
             :isRef?'<span style="font-size:10px;color:#7f8c8d">参考</span>'
             :d===null?'—'
             :Math.abs(d)<=1?'<span class="badge" style="background:#27ae60">◎</span>'
             :Math.abs(d)<=3?'<span class="badge" style="background:#f39c12">△</span>'
             :'<span class="badge" style="background:#e74c3c">✕</span>';
    const predCell=!isTarget?'<span style="font-size:10px;color:#7f8c8d">対象外</span>'
                  :isRef?'<span style="font-size:10px;color:#7f8c8d">参考'+h['予想順位']+'位</span>'
                  :h['予想順位']?h['予想順位']+'位':'—';
    const scoreCell=!isTarget?'<span style="font-size:10px;color:#7f8c8d">—</span>'
                   :isRef?'<span style="font-size:10px;color:#7f8c8d">'+h['スコア'].toFixed(1)+'(参考)</span>'
                   :h['スコア'].toFixed(1);
    const rowBg=h['入線順位']===1?'background:rgba(241,196,15,0.12)':h['入線順位']<=3?'background:rgba(46,204,113,0.08)':h['入線順位']<=5?'background:rgba(243,156,18,0.06)':'';
    const rankTxt=h['入線順位']<=5?`color:${rColor(h['入線順位'])}`:'color:inherit';
    // 走破タイム + 着差
    const gapSec=h['着差_sec'];
    const gapStr=(gapSec!==null&&gapSec>0)?`<span style="font-size:10px;color:#e67e22"> +${gapSec.toFixed(1)}秒</span>`:'';
    const timeCell=`${h['タイム']}${gapStr}`;
    // 通過順位（null除外してハイフン連結）
    const passes=[h['通過1'],h['通過2'],h['通過3'],h['通過4']].filter(v=>v!==null&&v!==undefined);
    const passCell=passes.length>0?passes.join('-'):'—';
    const wn=h['枠番']||Math.ceil(h['馬番']/2);
    const wakuCell=`<div style="display:flex;align-items:center;gap:4px;white-space:nowrap">
      <div style="width:20px;height:20px;border-radius:3px;background:${wBg(wn)};color:${wFg(wn)};font-size:10px;font-weight:bold;display:flex;align-items:center;justify-content:center;border:1px solid #555;flex-shrink:0">${wn}</div>
      <div style="width:20px;height:20px;border-radius:50%;background:${wBg(wn)};color:${wFg(wn)};font-size:10px;font-weight:bold;display:flex;align-items:center;justify-content:center;border:1px solid #555;flex-shrink:0">${h['馬番']}</div>
    </div>`;
    return `<tr style="${rowBg}"><td><b style="${rankTxt}">${h['入線順位']}着</b></td>
      <td>${wakuCell}</td>
      <td><b>${h['馬名']}</b></td><td>${h['人気']}人気 / ${h['単勝オッズ']}倍</td>
      <td style="color:${lColor(h['決め手'])}">${h['決め手']}</td>
      <td style="white-space:nowrap">${timeCell}</td><td style="font-size:12px;color:#ccc;letter-spacing:0.5px">${passCell}</td>
      <td>${h['上り3F'].toFixed(1)}秒</td><td>${predCell}</td><td>${scoreCell}</td>
      <td ${dc}>${ds}</td><td>${ev2}</td></tr>`;
  }).join('');
</script></body></html>"""

html = head + js

# 命名: {race_id}_review.html  (race_id=YYYYMMDD_{venue_code_lower}{N}) 例 20260621_tk10_review.html
import unicodedata as _uc, pykakasi as _pkk

_CLASS_CODE = {
    '未勝利':'Maiden','1勝':'C1','2勝':'C2','3勝':'C3',
    'オープン':'Open','ｵｰﾌﾟﾝ':'Open',
    'OP(L)':'Listed','OP（L）':'Listed',
    'Ｇ１':'G1','Ｇ２':'G2','Ｇ３':'G3',
    'G1':'G1','G2':'G2','G3':'G3',
}
_RACE_NAME_MAP = {
    '大阪杯':'OsakaHai','フラワーカップ':'FlowerCup','バイオレットS':'VioletS',
    'NHKマイルカップ':'NHKMileCup','メトロポリタンS':'MetropolitanS',
    '荒川峡特別':'ArakawakyoTokubetsu','讃岐特別':'SanukiTokubetsu',
}
_kks = _pkk.kakasi()
def _rname_to_romaji(s):
    sn = _uc.normalize('NFKC', s)
    if sn in _RACE_NAME_MAP: return _RACE_NAME_MAP[sn]
    parts = []
    for item in _kks.convert(sn):
        h = item.get('hepburn','') or item.get('orig','')
        if h:
            parts.append(h if item.get('orig','').isascii() else h.capitalize())
    return re.sub(r'[^A-Za-z0-9]','',''.join(parts)) or None

_rname_raw = str(race_name).strip()
_horses_stem = pathlib.Path(args.horses).stem  # horses_data_20260614_hd11
_race_id_m = re.search(r'(\d{8}_[a-zA-Z]+\d+)$', _horses_stem)
_race_id_p = _race_id_m.group(1) if _race_id_m else _horses_stem.replace('horses_data_', '')
_cls_raw = str(race.get('クラス名', '')).strip()
_cls_n   = _uc.normalize('NFKC', _cls_raw)
_cls_p   = _CLASS_CODE.get(_cls_n, _CLASS_CODE.get(_cls_raw, re.sub(r'[^A-Za-z0-9]','',_cls_n)))
_rname_p = _rname_to_romaji(_rname_raw)
_stem_parts = [p for p in [_race_id_p, _cls_p, _rname_p] if p]
_stem    = '_'.join(_stem_parts)
_auto_name = f'{_race_id_p}_review.html' if _race_id_p else 'review.html'

if args.out:
    out_path = pathlib.Path(args.out)
elif args.outdir:
    out_path = pathlib.Path(args.outdir) / _auto_name
else:
    out_path = pathlib.Path(_auto_name)

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(html, encoding='utf-8')
_sz = out_path.stat().st_size
print(f'\u2192 {out_path} \u3092\u751f\u6210\u3057\u307e\u3057\u305f ({_sz:,} bytes)')
