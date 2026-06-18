# -*- coding: utf-8 -*-
"""HTML ダッシュボード生成スクリプト v3
スコアバー, 過去走ドリルダウン, 期待値シミュレーター

使い方:
    python build_dashboard_v3.py [--json horses_data.json] [--out 競馬予想ダッシュボード.html]
"""

import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument('--json',   default='horses_data.json')
parser.add_argument('--out',    default=None)   # 出力ファイルのフルパス
parser.add_argument('--outdir', default=None)   # 出力ディレクトリ（--out未指定時に使用）
parser.add_argument('--baba-json', default=None, dest='baba_json',
                    help='馬場情報JSON (fetch_baba.py --out で生成)')
args, _ = parser.parse_known_args()

# 馬場情報ロード
_baba_info = {}
if args.baba_json:
    try:
        import pathlib as _pl
        _baba_info = json.loads(_pl.Path(args.baba_json).read_text(encoding='utf-8'))
    except Exception as _e:
        print(f'[baba_json] 読み込み失敗: {_e}')

with open(args.json, encoding='utf-8') as f:
    data = json.load(f)

horses = data['horses']
meta   = data['meta']

# ── メモ馬リスト読み込み（_date_p 確定後に実施）─────────────
import pathlib as _memo_pl
_memo_path = _memo_pl.Path(args.json).parent / 'memo_horses.json'
try:
    with open(_memo_path, encoding='utf-8') as _mf:
        _memo_list = json.load(_mf)
except Exception:
    _memo_list = []
# ※ _memo_map は _date_p 確定後（下部）で構築する
_memo_map = {}  # placeholder（後で上書き）

# ── レース情報（出馬表から取得、なければデフォルト）───────────
_ri          = meta.get('race_info') or {}
race_name    = _ri.get('レース名', 'レース名不明')
_display_title = (race_name if race_name and str(race_name) not in ('nan','None','','レース名不明')
                  else '')
race_place   = _ri.get('場所', '')
race_track   = _ri.get('芝ダ', '')
def _toint(v):
    try: return str(int(float(v)))
    except (TypeError, ValueError): return str(v)
race_dist    = _toint(_ri.get('距離', ''))
race_heads   = _toint(_ri.get('頭数', len(horses)))
race_class   = _ri.get('クラス名', '')
race_r       = _toint(_ri.get('R', ''))
race_course  = f"{race_place}{'ダート' if race_track == 'ダート' else '芝'}{race_dist}m"
_year  = _toint(_ri.get('年', '') or '')
_month = _toint(_ri.get('月', '') or '')
_day   = _toint(_ri.get('日', '') or '')
race_date_str = f"{_year}年{_month}月{_day}日" if _year else ''

# 出力ファイル名: --out 未指定時は案3形式で自動生成
# YYYYMMDD_[VenueCode][N]R_[Class]_[RaceNameRomaji]_pred.html
import re as _re, unicodedata as _uc
import pykakasi as _pkk

_VENUE_CODE = {
    '東京':'TK','阪神':'HN','京都':'KY','中山':'NK',
    '中京':'CK','新潟':'NG','小倉':'KK','札幌':'SP','函館':'HK','福島':'FK',
}
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
    return _re.sub(r'[^A-Za-z0-9]','',''.join(parts)) or None

_rname_raw = str(_ri.get('レース名', '')).strip()
_date_p  = f"{str(_year).zfill(4)}{str(_month).zfill(2)}{str(_day).zfill(2)}" if _year else ''

# ── メモ馬マップ構築（現在レース日付が確定してから） ─────────────
# 条件: 元レース日付 < 現在レース日付（同日・未来は除外）
# 同一馬が複数エントリある場合は最新の過去レースを1件に統合
def _memo_date_key(entry):
    """元レース.日付（YYYY/MM/DD）をYYYYMMDD数値に変換"""
    d = entry.get('元レース', {}).get('日付', '')
    return d.replace('/', '') if d else ''

_memo_map = {}
for _me in _memo_list:
    _mname = _me.get('馬名', '')
    if not _mname:
        continue
    _mdk = _memo_date_key(_me)
    # 現在レース日付より前のメモのみ（同日・未来は除外）
    if _date_p and _mdk >= _date_p:
        continue
    # 同一馬で複数エントリある場合は日付が新しい方を採用
    if _mname not in _memo_map or _mdk > _memo_date_key(_memo_map[_mname]):
        _memo_map[_mname] = _me

_venue_p = f"{_VENUE_CODE.get(race_place, race_place)}{race_r}R" if race_place else ''
_cls_n   = _uc.normalize('NFKC', race_class)
_cls_p   = _CLASS_CODE.get(_cls_n, _CLASS_CODE.get(race_class, _re.sub(r'[^A-Za-z0-9]','',_cls_n)))
_stem_parts = [p for p in [_date_p, _venue_p, _cls_p] if p]
if _rname_raw and _rname_raw not in ('nan','None','','レース名不明'):
    _romaji = _rname_to_romaji(_rname_raw)
    if _romaji: _stem_parts.append(_romaji)
_safe_stem   = '_'.join(_stem_parts) or 'pred'
_out_default = f'{_safe_stem}_pred.html'
if args.out is None:
    import pathlib as _pl2
    if args.outdir:
        args.out = str(_pl2.Path(args.outdir) / _out_default)
    else:
        args.out = _out_default


# ── ヘルパー ──────────────────────────────────────────────────
def leg_color(leg):
    return {
        '逃げ': '#e74c3c', '先行': '#f39c12',
        '差し': '#3498db', '追込': '#9b59b6', '不明': '#95a5a6',
    }.get(leg, '#95a5a6')

def class_label(s):
    if s >= 60: return ('S', '#e74c3c')
    if s >= 50: return ('A', '#f39c12')
    if s >= 40: return ('B', '#3498db')
    if s >= 30: return ('C', '#16a085')
    return ('D', '#7f8c8d')

def fmt(v, digits=1, suffix=''):
    if v is None: return '-'
    try:    return f'{float(v):.{digits}f}{suffix}'
    except: return '-'

def fmt_int(v):
    if v is None: return '-'
    try:    return str(int(v))
    except: return '-'

def bipolar_bar(val, max_abs):
    w   = min(100, abs(val) / max_abs * 100) if max_abs else 0
    cls = 'plus' if val >= 0 else 'minus'
    return f'<div class="fill {cls}" style="width:{w:.0f}%"></div>'

def penalty_bar(val, max_abs):
    w = min(100, abs(val) / max_abs * 100) if max_abs else 0
    return f'<div class="fill minus" style="width:{w:.0f}%"></div>'

def bonus_bar(val, max_abs):
    w   = min(100, abs(val) / max_abs * 100) if max_abs else 0
    cls = 'plus' if val >= 0 else 'minus'
    return f'<div class="fill {cls}" style="width:{w:.0f}%"></div>'

# ── 枠番カラー ────────────────────────────────────────────────
WAKU_BG = {
    1: '#FFFFFF', 2: '#666666', 3: '#FF4444', 4: '#4488FF',
    5: '#DDDD00', 6: '#22BB22', 7: '#FF8822', 8: '#e91e8c',
}
WAKU_FG = {1:'#111', 2:'#fff', 3:'#fff', 4:'#fff', 5:'#111', 6:'#fff', 7:'#fff', 8:'#fff'}

def waku_html_fn(waku, bango):
    if waku and isinstance(waku, int):
        _bg = WAKU_BG.get(waku, '#999')
        _fg = WAKU_FG.get(waku, '#fff')
        wh = (f'<span class="waku-badge" '
              f'style="background:{_bg};color:{_fg};">{waku}枠</span>')
        bh = (f'<span class="bango-badge" '
              f'style="background:{_bg};color:{_fg};">{fmt_int(bango)}番</span>'
              if bango else '')
    else:
        wh = '<span class="waku-badge" style="background:#666;color:#fff;">未定</span>'
        bh = ''
    return wh, bh

# ── 過去走テーブル (B-2) ──────────────────────────────────────
def build_past_races_table(past_races: list, horse_id: str) -> str:
    if not past_races:
        return '<div class="no-data">過去走データなし</div>'

    rows = ''
    for r in past_races:
        pos   = r.get('着順')
        total = r.get('頭数')
        pos_str = f"{pos}/{total}" if pos is not None and total is not None else '-'

        # 時計差の色（内部値は avg-corr: 正=速い / 表示は速い→"-", 遅い→"+"に反転）
        td = r.get('タイム差')
        if td is not None:
            td_cls = 'td-pos' if td >= 0 else 'td-neg'
            td_str = f'<span class="{td_cls}">{-td:+.2f}s</span>'
        else:
            td_str = '-'

        # コース類似度バッジ
        sim = r.get('コース類似度', 0)
        sim_cls = ('sim-hi' if sim >= 0.7
                   else 'sim-mid' if sim >= 0.5
                   else 'sim-lo')
        sim_str = f'<span class="{sim_cls}">{sim:.2f}</span>'

        # 馬場補正
        g_adj = r.get('馬場補正秒', 0)
        g_str = f'{g_adj:+.2f}s' if g_adj != 0 else '(良)'

        # PCI
        pci = r.get('PCI')
        if pci is not None:
            if pci < 50:   pci_str = f'<span class="pci-hi">{pci:.1f}</span>'
            elif pci > 55: pci_str = f'<span class="pci-lo">{pci:.1f}</span>'
            else:          pci_str = f'{pci:.1f}'
        else:
            pci_str = '-'

        rows += (
            f'<tr>'
            f'<td>{r.get("日付", "-")}</td>'
            f'<td>{r.get("場所", "-")}</td>'
            f'<td><span class="course-tag">{r.get("コース", "-")}</span></td>'
            f'<td>{r.get("クラス", "-")}</td>'
            f'<td class="center"><b>{pos_str}</b></td>'
            f'<td class="center">{r.get("走破タイム", "-")}</td>'
            f'<td class="center">{r.get("馬場", "-")} <small style="color:#888">{g_str}</small></td>'
            f'<td class="center">{td_str}</td>'
            f'<td class="center">{sim_str}</td>'
            f'<td class="center">{pci_str}</td>'
            f'<td class="center">{fmt(r.get("上がり3F"), 1)}</td>'
            f'<td class="center">{fmt_int(r.get("4角通過順"))}</td>'
            f'<td>{r.get("騎手", "-")}</td>'
            f'<td class="center">{fmt(r.get("斤量"), 1)}</td>'
            f'</tr>'
        )

    return f'''
<div class="drilldown-wrap" id="drill-{horse_id}" style="display:none;">
  <div class="drilldown-header">
    <span>📋 過去走詳細 ({len(past_races)}走)</span>
    <span class="drill-legend">
      <span class="td-pos">■</span>平均より速い
      <span class="td-neg">■</span>平均より遅い
      &nbsp;
      <span class="sim-hi">■</span>類似コース
      <span class="sim-mid">■</span>やや類似
      <span class="sim-lo">■</span>異質コース
      &nbsp;
      <span class="pci-hi">■</span>ハイペース
      <span class="pci-lo">■</span>スローペース
    </span>
  </div>
  <div style="overflow-x:auto">
  <table class="past-table">
    <thead>
      <tr>
        <th>日付</th><th>場所</th><th>コース</th><th>クラス</th>
        <th>着順</th><th>走破タイム</th><th>馬場</th>
        <th>平均差</th><th>コース適性</th><th>PCI</th>
        <th>上がり3F</th><th>4角</th><th>騎手</th><th>斤量</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  </div>
</div>'''

def _trust_badge(h):
    n_runs  = h.get('出走数', 0) or 0
    n_times = h.get('タイム偏差利用走数', 0) or 0
    if n_times >= 5:
        return '<span class="trust-badge trust-hi">🔒 データ充実</span>'
    elif n_times >= 3:
        return '<span class="trust-badge trust-mid">📊 参考可</span>'
    elif n_times >= 1:
        return '<span class="trust-badge trust-lo">⚠ データ少</span>'
    else:
        return '<span class="trust-badge trust-none">❓ データなし</span>'

# ── 偏差値（同一レース内相対スコア）事前計算 ─────────────
_scores_all = [h['総合スコア'] for h in horses]
_score_mu  = sum(_scores_all) / len(_scores_all) if _scores_all else 50.0
_score_var = sum((s - _score_mu)**2 for s in _scores_all) / len(_scores_all) if _scores_all else 1.0
_score_sig = _score_var ** 0.5
if _score_sig == 0: _score_sig = 1.0
def _dev(s):
    return round((s - _score_mu) / _score_sig * 10 + 50)
_dev_map = {h['馬名']: _dev(h['総合スコア']) for h in horses}

# ── 各馬カード ────────────────────────────────────────────────
horse_cards = ''
for idx, h in enumerate(horses):
    rank   = h['順位予想']
    score  = h['総合スコア']
    dev_score = _dev_map.get(h['馬名'], 50)
    label, color = class_label(score)
    leg    = h['脚質']
    odds   = h.get('単勝オッズ')
    pop    = h.get('人気')
    n      = h['出走数']
    name   = h['馬名']
    waku   = h.get('枠番')
    bango  = h.get('馬番')
    kinryo = h.get('今走斤量')

    waku_html, bango_html = waku_html_fn(waku, bango)

    p1 = (h['最高出力pts'] / 35) * 100
    p2 = (h['クラスpts']   / 25) * 100
    p3 = (h['時計pts']     / 25) * 100

    pace_pts       = h['展開pts']
    kinryo_pts     = h.get('斤量pts', 0)
    kyori_pts      = h.get('距離pts', 0)
    course_apt_pts = h.get('コース適性pts', 0)
    rinsen_pts     = h.get('臨戦pts', 0)
    ninki_pts      = h.get('人気補正pts', 0)
    jockey_pts     = h.get('騎手pts', 0)
    taiju_pts      = h.get('馬体重pts', 0)
    keizoku_pts    = h.get('継続pts', 0)
    chakusa_pts    = h.get('着差pts', 0)
    wakuban_pts    = h.get('枠順pts', 0)
    baba_apt_pts   = h.get('馬場適性pts', 0)

    # 補正バッジ
    adj_badges = ''
    for val, label_str, base_color in [
        (kinryo_pts,     '斤量',    '#2ca02c'),  # 緑
        (kyori_pts,      '距離',    '#e377c2'),  # ピンク
        (course_apt_pts, 'コース',  '#17becf'),  # シアン
        (rinsen_pts,     '休養',    '#8c564b'),  # ブラウン
        (ninki_pts,      '人気補正','#bcbd22'),  # オリーブ
        (jockey_pts,     '騎手',    '#aec7e8'),  # パウダーブルー
        (taiju_pts,      '馬体重',  '#7f7f7f'),  # グレー
        (keizoku_pts,    '継続騎乗','#98df8a'),  # ライトグリーン
        (chakusa_pts,    '着差',    '#dbdb8d'),  # ライトイエロー
        (wakuban_pts,    '枠順',    '#9edae5'),  # ライトシアン
        (baba_apt_pts,   '馬場適性', '#16a085'),  # エメラルド
    ]:
        if val != 0:
            c = base_color if val > 0 else '#c0392b'
            adj_badges += (f'<span class="adj-badge" style="background:{c}">'
                           f'{label_str} {val:+.1f}</span>')

    # 調教データ表示
    sakuro = h.get('坂路Lap1')
    wood   = h.get('ウッドLap1')
    train_str = ''
    if sakuro: train_str += f'坂路:{sakuro:.2f}s '
    if wood:   train_str += f'ウッド:{wood:.2f}s'

    horse_id    = f'h{idx}'
    past_rows   = h.get('past_races', [])
    drill_html  = build_past_races_table(past_rows, horse_id)
    no_past     = h.get('過去走なし', False)
    ref_badge   = ('<span class="adj-badge" style="background:#7f8c8d;font-size:10px;">参考スコア</span>'
                   if no_past else '')

    # メモ馬バッジ
    _memo_entry = _memo_map.get(name)
    if _memo_entry:
        _mo = _memo_entry.get('元レース', {})
        _mo_date  = _mo.get('日付', '')          # 元レース日付（登録日ではない）
        _mo_place = _mo.get('場所', '')
        _mo_r     = _mo.get('R', '')
        _mo_rname = _mo.get('レース名', '') or _mo.get('クラス', '')
        _mo_label = f'{_mo_date} {_mo_place}{_mo_r}R'
        if _mo_rname and str(_mo_rname) not in ('nan', 'None', ''):
            _mo_label += f' {_mo_rname}'
        _memo_note = _memo_entry.get('メモ', '')
        _memo_title = f'title="{_memo_note}"' if _memo_note else ''
        _memo_badge = (
            f'<span {_memo_title} style="display:inline-flex;align-items:center;gap:4px;'
            f'padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;'
            f'background:linear-gradient(135deg,#8e44ad,#6c3483);color:#fff;'
            f'box-shadow:0 0 6px rgba(142,68,173,0.5);white-space:nowrap;">'
            f'📌 メモ馬'
            f'<span style="font-size:9px;font-weight:400;opacity:0.85;margin-left:2px">'
            f'({_mo_label})</span></span>'
        )
    else:
        _memo_badge = ''

    # 注目穴馬バッジ
    _sr_rank = h.get('SmartRC推定人気順')
    _sr_int  = int(_sr_rank) if _sr_rank is not None else None
    _apt_sum = (h.get('コース適性pts', 0) + h.get('馬場適性pts', 0)
               + h.get('距離pts', 0) + h.get('展開pts', 0) + h.get('枠順pts', 0))
    _is_ana  = (_sr_int is not None
                and _sr_int > len(horses) // 2
                and rank <= 3
                and _apt_sum > 0)
    _ana_badge = (
        '<span title="SmartRC推定人気が下位・モデルスコア3位以内・適性系プラス"'
        ' style="display:inline-flex;align-items:center;gap:3px;'
        'padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;'
        'background:linear-gradient(135deg,#c0392b,#e74c3c);color:#fff;'
        'box-shadow:0 0 6px rgba(231,76,60,0.5);white-space:nowrap;">'
        '🎯 注目穴馬'
        f'<span style="font-size:9px;font-weight:400;opacity:0.85;margin-left:2px">'
        f'(SmartRC{_sr_int}番人気/適性{_apt_sum:+.1f}pt)</span></span>'
    ) if _is_ana else ''

    horse_cards += f'''
<div class="horse-card rank-{min(rank,4)}" data-rank="{rank}" data-leg="{leg}">
  <div class="rank-badge" style="background:{color}">
    <span class="rank-num">{rank}</span>
  </div>
  <div class="horse-main">
    <div class="horse-header">
      {waku_html}{bango_html}
      <h3>{name}</h3>
      <span class="leg-badge" style="background:{leg_color(leg)}">{leg}</span>
      {ref_badge}{_trust_badge(h)}{adj_badges}
      {_memo_badge}
      {_ana_badge}
      <span class="meta-info">{h["性別"]}{h["年齢"]} / {h["騎手"]} / {n}走</span>
      <button class="drill-btn" onclick="toggleDrill('{horse_id}', this)">📋 過去走</button>
    </div>
    <div class="score-row">
      <div class="total-score">
        <span class="big-num">{score:.1f}</span>
        <span class="small-label">総合スコア</span>
        <div style="margin-top:6px;display:flex;flex-direction:column;align-items:center;gap:1px"><span style="font-size:9px;color:#aaa;letter-spacing:1px">評価ランク</span><span style="font-size:20px;font-weight:900;letter-spacing:2px;padding:1px 14px;border-radius:5px;background:{color};color:#fff;line-height:1.3">{label}</span></div>
        <span class="small-label" style="margin-top:2px;font-size:10px;color:#f1c40f;font-weight:700">偏差値 {dev_score}</span>
        <span class="small-label" style="margin-top:4px;font-size:10px;color:#7f8c8d">
          単勝 {fmt(odds,1)}倍<br>({fmt_int(pop)}人気)
        </span>
      </div>
      <div class="score-bars">
        <div class="bar-row">
          <label>最高出力</label>
          <div class="bar"><div class="fill" style="width:{p1:.0f}%;background:#e74c3c"></div></div>
          <span class="val">{h["最高出力pts"]:.1f}/35</span>
        </div>
        <div class="bar-row">
          <label>クラス補正</label>
          <div class="bar"><div class="fill" style="width:{p2:.0f}%;background:#f39c12"></div></div>
          <span class="val">{h["クラスpts"]:.1f}/25</span>
        </div>
        <div class="bar-row">
          <label>タイム偏差</label>
          <div class="bar"><div class="fill" style="width:{p3:.0f}%;background:#3498db"></div></div>
          <span class="val">{h["時計pts"]:.1f}/25</span>
        </div>
        <div class="bar-row">
          <label>展開適性</label>
          <div class="bar bipolar">{bipolar_bar(pace_pts, 15)}</div>
          <span class="val">{pace_pts:+d}/±15</span>
        </div>
        <div class="bar-row adj-row">
          <label>斤量補正</label>
          <div class="bar bipolar">{bonus_bar(kinryo_pts, 3)}</div>
          <span class="val">{kinryo_pts:+.1f}/±3</span>
        </div>
        <div class="bar-row adj-row">
          <label>距離補正</label>
          <div class="bar bipolar">{penalty_bar(kyori_pts, 4)}</div>
          <span class="val">{kyori_pts:+.0f}/−4</span>
        </div>
        <div class="bar-row adj-row">
          <label>コース適性</label>
          <div class="bar bipolar">{bipolar_bar(course_apt_pts, 5)}</div>
          <span class="val">{course_apt_pts:+.1f}/±5</span>
        </div>
        <div class="bar-row adj-row">
          <label>臨戦補正</label>
          <div class="bar bipolar">{penalty_bar(rinsen_pts, 7)}</div>
          <span class="val">{rinsen_pts:+.0f}/−7</span>
        </div>
        <div class="bar-row adj-row">
          <label>人気補正</label>
          <div class="bar bipolar">{bipolar_bar(ninki_pts, 3)}</div>
          <span class="val">{ninki_pts:+.1f}/+3</span>
        </div>
        <div class="bar-row adj-row">
          <label>騎手実績</label>
          <div class="bar bipolar">{bipolar_bar(jockey_pts, 2)}</div>
          <span class="val">{jockey_pts:+.1f}/±2</span>
        </div>
        <div class="bar-row adj-row">
          <label>枠順補正</label>
          <div class="bar bipolar">{bipolar_bar(wakuban_pts, 2)}</div>
          <span class="val">{wakuban_pts:+.1f}/±2</span>
        </div>
        <div class="bar-row adj-row">
          <label>馬場適性</label>
          <div class="bar bipolar">{bipolar_bar(baba_apt_pts, 3)}</div>
          <span class="val">{baba_apt_pts:+.1f}/±3</span>
        </div>
      </div>
    </div>
    <div class="extra-info">
      <span>補正最良: <b>{fmt(h["補正タイム最良"], 0)}</b></span>
      <span>上がり平均: <b>{fmt(h["平均上がり3F"], 1)}</b></span>
      <span>平均通過: <b>{fmt(h["平均4角通過順"], 1)}</b></span>
      <span>コース類似度: <b>{fmt(h.get("平均コース類似度"), 2)}</b></span>
      <span>父: {h["父馬名"]}</span>
      <span>母父: {h["母の父馬名"]}</span>
      <span>時計データ: {h["タイム偏差利用走数"]}/{n}走</span>
      {f'<span style="color:#aaa">🏋️ {train_str}</span>' if train_str else ''}
    </div>
    {drill_html}
  </div>
</div>'''

# ── 脚質分布 ──────────────────────────────────────────────────
leg_counts = meta['leg_count']
total_legs = sum(leg_counts.values())
leg_html   = ''
for leg in ['逃げ', '先行', '差し', '追込', '不明']:
    n = leg_counts.get(leg, 0)
    if n > 0:
        pct = n / total_legs * 100
        leg_html += (f'<div class="leg-item">'
                     f'<div class="leg-color" style="background:{leg_color(leg)}"></div>'
                     f'<b>{leg}</b>'
                     f'<span class="leg-count">{n}頭</span>'
                     f'<div class="leg-bar">'
                     f'<div class="leg-fill" style="width:{pct:.0f}%;background:{leg_color(leg)}"></div>'
                     f'</div></div>')

# ── 上位3頭ポジウム ──────────────────────────────────────────
top3   = horses[:3]
honmei = top3[0]
taikou = top3[1]
tanana = top3[2]

def podium_smartrc_pop(h):
    """SmartRC推定人気順を「SmartRC◯番人気」形式で返す。データなしは空文字。"""
    v = h.get('SmartRC推定人気順')
    if v is None:
        return '-人気'
    try:
        return f'想定{int(v)}番人気'
    except (TypeError, ValueError):
        return '-人気'

def podium_waku_str(h):
    w = h.get('枠番')
    b = h.get('馬番')
    if w: return f'{w}枠 {fmt_int(b)}番 / '
    return ''

# ── 全馬テーブル ────────────────────────────────────────────
all_marks = ''
for h in horses:
    r       = h['順位予想']
    _dev_t  = _dev_map.get(h['馬名'], 50)
    waku_b  = h.get('枠番')
    bango_b = h.get('馬番')

    # ① 枠番バッジ（枠色付き）
    if waku_b:
        _wbg = WAKU_BG.get(int(waku_b), '#888')
        _wfg = WAKU_FG.get(int(waku_b), '#fff')
        num_str = (
            f'<span style="display:inline-block;background:{_wbg};color:{_wfg};'
            f'font-weight:700;font-size:11px;padding:1px 5px;border-radius:3px;margin-right:2px;">'
            f'{waku_b}枠</span>'
            f'<span style="display:inline-block;background:{_wbg};color:{_wfg};'
            f'font-weight:700;font-size:11px;padding:1px 5px;border-radius:3px;">'
            f'{fmt_int(bango_b)}番</span>'
        )
    else:
        num_str = '<span style="color:#555">未定</span>'

    # ② バッジ: 補正スコア系を削除し、メモ馬・注目穴馬バッジのみ表示
    badges = ''
    if h['馬名'] in _memo_map:
        badges += '<span style="font-size:9px;background:#8e44ad;color:#fff;padding:1px 5px;border-radius:3px;margin-left:4px;vertical-align:middle;">📌</span>'
    _sr_int_am = None
    try:
        _sr_int_am = int(h.get('SmartRC推定人気順') or 99)
    except (TypeError, ValueError):
        pass
    _apt_sum_am = (h.get('コース適性pts', 0) + h.get('馬場適性pts', 0)
                 + h.get('距離pts', 0) + h.get('展開pts', 0) + h.get('枠順pts', 0))
    _is_ana_am = (_sr_int_am is not None
                  and _sr_int_am > len(horses) // 2
                  and h.get('順位予想', 99) <= 3
                  and _apt_sum_am >= 0)
    if _is_ana_am:
        badges += '<span style="font-size:9px;background:#c0392b;color:#fff;padding:1px 5px;border-radius:3px;margin-left:4px;vertical-align:middle;">🎯</span>'

    # SmartRC推定人気列
    src_rank  = h.get('SmartRC推定人気順')
    src_ninki_cell = (f'<td style="text-align:center;white-space:nowrap"><b style="color:#f39c12">{src_rank}位</b></td>'
                      if src_rank is not None else '<td style="text-align:center;color:#555">-</td>')

    # SmartRC前走評価列 (A/B/C/D/E)
    _sr_hyoka = h.get('SmartRC評価')  # A/B/C/D/E or None
    _SR_COLOR = {'A': '#27ae60', 'B': '#2ecc71', 'C': '#7f8c8d', 'D': '#e67e22', 'E': '#e74c3c'}
    _SR_LABEL = {'A': 'A 不利', 'B': 'B 不利', 'C': 'C 中立', 'D': 'D 有利', 'E': 'E 有利'}
    if _sr_hyoka and _sr_hyoka in _SR_COLOR:
        _sc = _SR_COLOR[_sr_hyoka]
        _sl = _SR_LABEL[_sr_hyoka]
        sr_eval_cell = (f'<td style="text-align:center;white-space:nowrap">'
                        f'<span style="background:{_sc};color:#fff;font-size:11px;font-weight:700;'
                        f'padding:2px 7px;border-radius:4px;">{_sl}</span></td>')
    else:
        sr_eval_cell = '<td style="text-align:center;color:#555">-</td>'

    # 斤量列
    kinryo_val = h.get('今走斤量')
    kinryo_cell = (f'<td style="text-align:center;white-space:nowrap">{kinryo_val}kg</td>'
                   if kinryo_val else '<td style="text-align:center;color:#555">-</td>')

    # 年齢・性別列
    age_val = h.get('年齢')
    sex_val = h.get('性別', '')
    age_cell = (f'<td style="text-align:center;white-space:nowrap">{age_val}歳 {sex_val}</td>'
                if age_val else '<td style="text-align:center;color:#555">-</td>')

    all_marks += (
        f'<tr>'
        f'<td>{r}</td>'
        f'<td style="white-space:nowrap">{num_str}</td>'
        f'<td><b>{h["馬名"]}</b>{badges}</td>'
        f'<td>{h["脚質"]}</td>'
        f'<td style="white-space:nowrap"><b>{h["総合スコア"]:.1f}</b><br><span style="font-size:10px;color:#f1c40f;font-weight:700">偏差{_dev_t}</span></td>'
        f'<td>{fmt(h.get("単勝オッズ"), 1)}倍 ({fmt_int(h.get("人気"))}人気)</td>'
        f'{src_ninki_cell}'
        f'{sr_eval_cell}'
        f'{kinryo_cell}'
        f'{age_cell}'
        f'<td>{h["騎手"]}</td>'
        f'</tr>'
    )

# ── 出馬表反映バナー ──────────────────────────────────────────
has_shutuba = any(h.get('枠番') is not None for h in horses)
if has_shutuba:
    shutuba_banner = '''<div class="shutuba-banner">
      ✅ 出馬表データ反映済み（枠番・馬番・騎手・斤量・オッズが最新です）
    </div>'''
else:
    shutuba_banner = '''<div class="shutuba-banner warning">
      ⚠️ 出馬表未反映（騎手・オッズ・枠番は過去データの最終走値です）
    </div>'''

# ── 馬場状態バナー ─────────────────────────────────────────────────
_baba_color_map = {'良': '#27ae60', '稍重': '#e67e22', '重': '#c0392b', '不良': '#8e44ad'}
_est_shiba = _baba_info.get('推定馬場_芝')
_est_dart  = _baba_info.get('推定馬場_ダート')
_baba_venue = _baba_info.get('場所', '')
if _est_shiba:
    _shiba_color = _baba_color_map.get(_est_shiba, '#ecf0f1')
    _dart_color  = _baba_color_map.get(_est_dart,  '#ecf0f1')
    _cushion_str = (f'　クッション値: {_baba_info["クッション値"]}' if _baba_info.get('クッション値') else '')
    _rain_str    = (f'　降水量: {_baba_info["降水量_mm"]}mm' if _baba_info.get('降水量_mm') is not None else '')
    _konkyo_str  = _baba_info.get('推定根拠', '')
    baba_banner = f'''<div class="shutuba-banner" style="background:linear-gradient(135deg,#1a3a6b 0%,#2c5282 100%);color:#fff;border-left:4px solid #f1c40f;margin-bottom:8px">
      🌤 <b>推定馬場状態</b>（{_baba_venue}）：
      芝 <b style="color:{_shiba_color};font-size:15px">{_est_shiba}</b>
      ／ダート <b style="color:{_dart_color};font-size:15px">{_est_dart}</b>
      {_cushion_str}{_rain_str}
      <span style="font-size:10px;color:#bdc3c7;margin-left:12px">（{_konkyo_str}）</span>
    </div>'''
else:
    baba_banner = ''

# ── 期待値データ (JSON for JS) ─────────────────────────────────
# 過去走なしの馬はsoftmax計算に含めると歪むため除外
ev_data_json = json.dumps([
    {
        '馬名':            h['馬名'],
        '馬番':            h.get('馬番'),
        '枠番':            h.get('枠番'),
        'スコア':          h['総合スコア'],
        '順位予想':         h['順位予想'],
        'オッズ':          h.get('単勝オッズ'),
        '複勝下限':         h.get('複勝下限'),
        '複勝上限':         h.get('複勝上限'),
        '人気':            h.get('人気'),
        '脚質':            h['脚質'],
        'SmartRC推定人気順':  h.get('SmartRC推定人気順'),   # 数字
        '乖離度':          (int(h.get('SmartRC推定人気順') or 99) - h.get('順位予想', 99)) if h.get('SmartRC推定人気順') else None,
        'is_memo':         h['馬名'] in _memo_map,
        'is_ana':          (
            h.get('SmartRC推定人気順') is not None
            and int(h.get('SmartRC推定人気順')) > len(horses) // 2
            and h['順位予想'] <= 3
            and (h.get('コース適性pts', 0) + h.get('馬場適性pts', 0)
                 + h.get('距離pts', 0) + h.get('展開pts', 0) + h.get('枠順pts', 0)) > 0
        ),
    }
    for h in horses
    if not h.get('過去走なし', False)
], ensure_ascii=False)


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
_fav_thr = _n_horses // 2   # 中央値より下位なら低評価
# 99はデータなし（過去走なし等）のデフォルト値なので判定除外
_fav1_is_low = (_fav1_score_rank != 99) and (_fav1_score_rank > _fav_thr)

# ── 自信あり判定（偏差値≥68のみ ― 2026-06-17修正: OR リード≥15 を廃止し基準厳格化）─────────────
_sorted_valid = sorted(
    [h for h in horses if not h.get('過去走なし', False)],
    key=lambda h: h.get('順位予想', 99)
)
_pred1_name  = _sorted_valid[0]['馬名'] if _sorted_valid else ''
_pred1_score = _sorted_valid[0].get('総合スコア', 0) if _sorted_valid else 0
_pred2_score = _sorted_valid[1].get('総合スコア', 0) if len(_sorted_valid) > 1 else 0
_score_lead  = _pred1_score - _pred2_score
_pred1_dev   = _dev_map.get(_pred1_name, 50)
_pred1_smartrc_rank = next(
    (int(h.get('SmartRC推定人気順') or 99)
     for h in horses if h['馬名'] == _pred1_name), 99)
_pred1_is_fav = _pred1_smartrc_rank == 1  # SmartRC推定1番人気=妙味なし
_jishin_flag = (_pred1_dev >= 68) and not _pred1_is_fav

# ── 推奨度判定 ───────────────────────────────────────────────
if _max_kairido >= 4:
    _rec_badge  = '🟢 妙味有'
    _rec_color  = '#27ae60'
    _rec_bg     = '#1a3a28'
    _rec_reason = f'スコア上位馬がSmartRC推定より{_max_kairido}順位上 ― 大きな市場乖離あり'
elif _max_kairido >= 2:
    if _fav1_is_low:
        _rec_badge  = '🟢 妙味有'
        _rec_color  = '#27ae60'
        _rec_bg     = '#1a3a28'
        _rec_reason = (f'SmartRC推定から{_max_kairido}順位上の乖離あり'
                       f'＋1番人気スコア低評価（{_fav1_score_rank}位/{_n_horses}頭中）')
    else:
        _rec_badge  = '🟡 要検討'
        _rec_color  = '#f39c12'
        _rec_bg     = '#3a2e10'
        _rec_reason = f'SmartRC推定から{_max_kairido}順位上の乖離あり（中穴の可能性）'
else:
    _rec_badge  = '🔴 妙味薄'
    _rec_color  = '#e74c3c'
    _rec_bg     = '#3a1a1a'
    _rec_reason = 'スコア上位3頭とSmartRC推定が概ね一致（妙味薄）'

# ── 本命馬自信ありバッジ（偏差値≥68のみ ― 妙味判定とは独立） ────
_jishin_html = ''
if _jishin_flag:
    _dev_str = f'偏差値{_pred1_dev}'
    _lead_str = f'リード{_score_lead:.1f}pt' if _score_lead >= 15 else ''
    _sub = ' / '.join(filter(None, [_dev_str, _lead_str]))
    _jishin_html = (
        f'<span style="display:inline-flex;align-items:center;gap:6px;'
        f'padding:5px 14px;border-radius:6px;background:#2c3e50;'
        f'border:1px solid #f39c12;font-size:12px;">'
        f'⭐ 本命馬自信あり: '
        f'<b style="color:#f1c40f">{_pred1_name}</b>'
        f'<span style="color:#f39c12;font-weight:700">({_sub})</span>'
        f'</span>'
    )

# ── 注目馬バッジ ────────────────────────────────────────────
_best_html = ''
if _best_val and _best_val['乖離'] >= 2:
    _odds_str = (f'{_best_val["オッズ"]:.1f}倍'
                 if _best_val.get('オッズ') else '-')
    _best_html = (
        f'<span style="display:inline-flex;align-items:center;gap:6px;'
        f'padding:5px 14px;border-radius:6px;background:#2c3e50;'
        f'border:1px solid #3498db;font-size:12px;">'
        f'💎 注目馬: '
        f'<b style="color:#f1c40f">{_best_val["馬名"]}</b>'
        f'<span style="color:#aaa;">（予想{_best_val["予想順位"]}位 / 想定{_best_val["SmartRC推定"]}番人気'
        f' / 乖離+{_best_val["乖離"]} / 単勝{_odds_str}）</span>'
        f'</span>'
    )

# ── 危険な人気馬バッジ（想定人気上位×予想低評価 ― 2026-06-18 復元）────
# 06-16のUIリファクタで欠落していたバッジを復元。
# 検証(123R): 想定人気≤3 かつ 予想7位以下 で複勝率 base51.6%→40.5%(-11pt, 方向性◎)。
# 補助条件(前走着順悪化 -5pt/p0.14)はデータ拡充後に追加検討。
_danger_list = []
for _h in horses:
    if _h.get('過去走なし'):
        continue
    try:
        _srank = int(_h.get('SmartRC推定人気順') or 99)
        _prank = int(_h.get('順位予想') or 99)
    except (TypeError, ValueError):
        continue
    if _srank <= 3 and _prank >= 7:
        _danger_list.append((_srank, _prank, _h['馬名']))
_danger_list.sort()
_danger_html = ''
if _danger_list:
    _ditems = ' / '.join(
        f'<b style="color:#f1c40f">{_nm}</b>'
        f'<span style="color:#aaa;">（想定{_sr}番人気 / 予想{_pr}位）</span>'
        for _sr, _pr, _nm in _danger_list)
    _danger_html = (
        f'<span style="display:inline-flex;align-items:center;gap:6px;'
        f'padding:5px 14px;border-radius:6px;background:#2c3e50;'
        f'border:1px solid #e74c3c;font-size:12px;">'
        f'⚠️ 危険な人気馬: {_ditems}</span>'
    )

# ── バッジエリア（注目馬 / 本命馬自信あり / 危険な人気馬 ― どれもなければ非表示） ────
_badge_area_html = ''
if _jishin_html or _best_html or _danger_html:
    _badge_area_html = (
        f'<div style="display:flex;align-items:center;flex-wrap:wrap;gap:10px;'
        f'padding:10px 16px;margin-bottom:8px;border-radius:8px;'
        f'background:#1e2d3d;border:1px solid #2e4055;">'
        f'{_jishin_html}'
        f'{_best_html}'
        f'{_danger_html}'
        f'</div>'
    )

# ── 補正積み上げチャートデータ ──────────────────────────────────
_comp_fields = [
    # ── tab20 カテゴリカルパレット（色重複なし）
    ('最高出力pts',   '最高出力', '#d62728'),  # 赤
    ('クラスpts',     'クラス',   '#ff7f0e'),  # オレンジ
    ('時計pts',       'タイム',   '#1f77b4'),  # 青
    ('展開pts',       '展開',     '#9467bd'),  # 紫
    ('斤量pts',       '斤量',     '#2ca02c'),  # 緑
    ('距離pts',       '距離',     '#e377c2'),  # ピンク/マゼンタ
    ('コース適性pts', 'コース',   '#17becf'),  # シアン
    ('臨戦pts',       '臨戦',     '#8c564b'),  # ブラウン
    ('人気補正pts',   '人気補正', '#bcbd22'),  # オリーブ
    ('騎手pts',       '騎手',     '#aec7e8'),  # パウダーブルー
    ('馬体重pts',     '馬体重',   '#7f7f7f'),  # グレー
    ('継続pts',       '継続',     '#98df8a'),  # ライトグリーン
    ('着差pts',       '着差',     '#dbdb8d'),  # ライトイエロー
    ('枠順pts',       '枠順',     '#9edae5'),  # ライトシアン
    ('昇級pts',       '昇級',     '#c5b0d5'),  # ラベンダー
    ('クラス適応pts',  'クラス適応', '#1abc9c'),  # ターコイズ
    ('SmartRC評価pts',  'SmartRC評価', '#f39c12'),  # アンバー
    ('馬場適性pts',       '馬場適性',   '#16a085'),  # エメラルド
]
_chart_horses = sorted(horses, key=lambda h: h['順位予想'])
_chart_labels  = [f"{h['順位予想']}位 {h['馬名']}" for h in _chart_horses]
_chart_datasets = [
    {'label': lbl, 'data': [h.get(fld, 0) for h in _chart_horses],
     'backgroundColor': col, 'stack': 'adj'}
    for fld, lbl, col in _comp_fields
]
score_chart_json = json.dumps(
    {'labels': _chart_labels, 'datasets': _chart_datasets}, ensure_ascii=False)


# ── 補正項目別ランキングデータ ────────────────────────────────────
_item_rankings = []
for _fld, _lbl, _col in _comp_fields:
    _ranked = sorted(
        [
            {
                'umaban': h.get('馬番', '?'),
                'name':   h['馬名'],
                'val':    round(float(h.get(_fld, 0) or 0), 2),
            }
            for h in horses
        ],
        key=lambda x: x['val'],
        reverse=True,
    )
    _item_rankings.append({'label': _lbl, 'color': _col, 'ranked': _ranked})
item_rankings_json = json.dumps(_item_rankings, ensure_ascii=False)


# ── 展開マトリクスデータ ──────────────────────────────────────────
_today_pace = meta.get('today_pace', 'mid')   # 'high' / 'mid' / 'low'
_pace_favor = {
    'high': {'逃げ': -1, '先行': -1, '差し': 1, '追込': 1},
    'mid':  {'逃げ':  0, '先行':  0, '差し': 0, '追込': 0},
    'low':  {'逃げ':  1, '先行':  1, '差し':-1, '追込':-1},
}
_styles = ['逃げ', '先行', '差し', '追込']
_paces  = [('high','ハイペース'), ('mid','ミドルペース'), ('low','スローペース')]

def _matrix_cell(horses_list, pace_key, style):
    favor = _pace_favor[pace_key].get(style, 0)
    color = '#2ecc71' if favor > 0 else '#e74c3c' if favor < 0 else '#7f8c8d'
    icon  = '◎ 有利' if favor > 0 else '△ 不利' if favor < 0 else '± 普通'
    hs = [(h['馬名'], int(h.get('馬番') or 0), int(h.get('枠番') or 0)) for h in horses_list if h['脚質'] == style]
    _chips = []
    for _n, _u, _wk in hs:
        _bg = WAKU_BG.get(_wk, '#888')
        _fg = WAKU_FG.get(_wk, '#fff')
        _chips.append(
            f'<span style="display:inline-flex;align-items:center;gap:3px;'
            f'background:rgba(255,255,255,0.1);border-radius:4px;padding:2px 6px;margin:2px;font-size:11px">'
            f'<span style="background:{_bg};color:{_fg};border-radius:50%;'
            f'width:16px;height:16px;display:inline-flex;align-items:center;'
            f'justify-content:center;font-size:9px;font-weight:700;flex-shrink:0">{_u or "?"}</span>'
            f'{_n}</span>'
        )
    name_html = ''.join(_chips) if _chips else '<span style="color:#555;font-size:11px">該当なし</span>'
    highlight = 'border:2px solid #f1c40f;' if pace_key == _today_pace else ''
    return (
        f'<td style="padding:8px;vertical-align:top;border:1px solid #2c3e50;{highlight}">'
        f'<div style="color:{color};font-weight:700;font-size:12px;margin-bottom:4px">{icon}</div>'
        f'{name_html}</td>'
    )

_matrix_rows = ''
for style in _styles:
    style_color = {'逃げ':'#e74c3c','先行':'#f39c12','差し':'#3498db','追込':'#9b59b6'}.get(style,'#888')
    _matrix_rows += (
        f'<tr><td style="padding:8px;font-weight:700;color:{style_color};'
        f'border:1px solid #2c3e50;white-space:nowrap">{style}</td>'
    )
    for pk, _ in _paces:
        _matrix_rows += _matrix_cell(horses, pk, style)
    _matrix_rows += '</tr>'

_pace_headers = ''.join(
    f'<th style="padding:8px;background:#243447;color:{"#f1c40f" if pk == _today_pace else "#7f8c8d"};'
    f'border:1px solid #2c3e50">{"★ " if pk == _today_pace else ""}{pn}</th>'
    for pk, pn in _paces
)
_matrix_html = f'''<div class="section" id="section-matrix">
  <h2>🗂 展開マトリクス（脚質 × ペース）</h2>
  <div style="font-size:12px;color:#bdc3c7;margin-bottom:10px">
    当レースの想定ペース: <b style="color:#f1c40f">{"★ " + dict(_paces)[_today_pace]}</b> —
    ★印の列が今回の展開で有利な脚質グループです。
  </div>
  <div style="overflow-x:auto">
  <table style="border-collapse:collapse;width:100%;font-size:12px">
    <thead><tr>
      <th style="padding:8px;background:#243447;border:1px solid #2c3e50;color:#7f8c8d">脚質</th>
      {_pace_headers}
    </tr></thead>
    <tbody>{_matrix_rows}</tbody>
  </table>
  </div>
  <div style="font-size:11px;color:#7f8c8d;margin-top:8px">
    ◎ 有利 = このペース展開で脚質的に優位 / △ 不利 = ペース的に逆風 / ± 普通 = 中立
  </div>
</div>'''


# ── 展開予想パネル（隊列イメージ）────────────────────────────────
_formation_horses_data = []
for _fh in horses:
    _waku  = _fh.get('枠番')
    _uma   = _fh.get('馬番')
    _kyaku = _fh.get('脚質', '差し')
    _ten_r = _fh.get('SmartRCテン速度順位')   # None or int
    _aga_r = _fh.get('SmartRC上がり速度順位') # None or int
    _formation_horses_data.append({
        'name':  _fh['馬名'],
        'uma':   int(_uma)  if _uma  is not None else None,
        'waku':  int(_waku) if _waku is not None else None,
        'kyaku': _kyaku,
        'ten_r': int(_ten_r) if _ten_r is not None else None,
        'aga_r': int(_aga_r) if _aga_r is not None else None,
    })
_formation_json  = json.dumps(_formation_horses_data, ensure_ascii=False)
_formation_pace  = _today_pace      # 'high' / 'mid' / 'low'
_formation_total = len(horses)
_track_direction = _ri.get('回り', '左')   # '左'=反時計 / '右'=時計回り

# SmartRC速度競合情報（展開パネルヘッダー表示用）
_ten_ranks_disp  = [(h.get('ten_r'), h.get('name'), h.get('uma'))
                    for h in _formation_horses_data if h.get('ten_r') is not None]
_aga_ranks_disp  = [(h.get('aga_r'), h.get('name'), h.get('uma'))
                    for h in _formation_horses_data if h.get('aga_r') is not None]
_ten_top3  = sorted(_ten_ranks_disp, key=lambda x: x[0])[:3]
_aga_top3  = sorted(_aga_ranks_disp, key=lambda x: x[0])[:3]
_ten_competition = sum(1 for r, _, _ in _ten_ranks_disp if r <= 3)

def _speed_badge(rank, name):
    colors = {1:'#e74c3c',2:'#e67e22',3:'#f1c40f'}
    c = colors.get(rank, '#7f8c8d')
    return (f'<span style="background:{c};color:#fff;border-radius:3px;'
            f'padding:1px 5px;font-size:10px;font-weight:700;margin:1px">'
            f'{rank}位 {name}</span>')

_ten_html = ''.join(_speed_badge(r, n) for r, n, _ in _ten_top3) if _ten_top3 else '<span style="color:#7f8c8d;font-size:11px">データなし</span>'
_aga_html = ''.join(_speed_badge(r, n) for r, n, _ in _aga_top3) if _aga_top3 else '<span style="color:#7f8c8d;font-size:11px">データなし</span>'
_competition_label = (f'<span style="color:#e74c3c;font-weight:700">速度競合({_ten_competition}頭)あり</span>'
                      if _ten_competition >= 2 else
                      '<span style="color:#bdc3c7">速度競合なし</span>')

_formation_html = f'''<div class="section" id="section-formation">
  <h2>🐎 展開予想 — 序盤/中盤/終盤の隊列イメージ</h2>
  <div style="font-size:12px;color:#bdc3c7;margin-bottom:8px">
    脚質・SmartRCテン/上がり速度順位・枠番・想定ペースをもとに位置取りを推定します。
    チップ色は<b>枠番色</b>。
    <span style="display:inline-flex;gap:4px;align-items:center;flex-wrap:wrap;margin-left:6px;vertical-align:middle">
      <span style="background:#eeeeee;color:#222;border-radius:3px;padding:1px 6px;font-size:9px;font-weight:700">1枠</span>
      <span style="background:#2d2d2d;color:#fff;border-radius:3px;padding:1px 6px;font-size:9px;font-weight:700">2枠</span>
      <span style="background:#c0392b;color:#fff;border-radius:3px;padding:1px 6px;font-size:9px;font-weight:700">3枠</span>
      <span style="background:#1a5276;color:#fff;border-radius:3px;padding:1px 6px;font-size:9px;font-weight:700">4枠</span>
      <span style="background:#d4ac0d;color:#222;border-radius:3px;padding:1px 6px;font-size:9px;font-weight:700">5枠</span>
      <span style="background:#1e8449;color:#fff;border-radius:3px;padding:1px 6px;font-size:9px;font-weight:700">6枠</span>
      <span style="background:#ca6f1e;color:#fff;border-radius:3px;padding:1px 6px;font-size:9px;font-weight:700">7枠</span>
      <span style="background:#e91e8c;color:#fff;border-radius:3px;padding:1px 6px;font-size:9px;font-weight:700">8枠</span>
    </span>
    <span style="color:#7f8c8d;font-size:11px;margin-left:6px">（SmartRC速度データ未取得時は脚質のみで推定）</span>
  </div>
  <div style="font-size:11px;color:#bdc3c7;margin-bottom:6px;line-height:1.8">
    <span style="color:#3498db;font-weight:700">⚡テン速度 TOP3：</span>{_ten_html}
    &nbsp;|&nbsp;
    <span style="color:#e74c3c;font-weight:700">🏁上がり速度 TOP3：</span>{_aga_html}
    &nbsp;|&nbsp; {_competition_label}
  </div>
  <div id="formation-panels" style="display:flex;gap:16px;overflow-x:auto;padding-bottom:8px;align-items:stretch"></div>
</div>

<script>
(function(){{
  const fHorses = {_formation_json};
  const pace      = '{_formation_pace}';
  const N         = {_formation_total};
  const direction  = '{_track_direction}';  // '左'=反時計 / '右'=時計回り

  // 脚質→基本前後スコア (0=逃げ先頭 ～ 3=追込最後方)
  const KYAKU_BASE = {{'逃げ':0.0,'先行':1.0,'差し':2.0,'追込':3.0}};

  // 枠番色 (index=枠番 1-8)
  const WAKU_BG   = ['','#eeeeee','#2d2d2d','#c0392b','#1a5276','#d4ac0d','#1e8449','#ca6f1e','#e91e8c'];
  const WAKU_FG   = ['','#222222','#ffffff','#ffffff','#ffffff','#222222','#ffffff','#ffffff','#ffffff'];

  // ゾーン境界・ラベル・色
  const ZONE_CUTS   = [0.875, 1.875, 2.5];
  const ZONE_LABELS = ['先頭','先行','差し','追込'];
  const ZONE_COLORS = ['#e74c3c','#f39c12','#3498db','#9b59b6'];
  const ZONE_RGBA   = ['231,76,60','243,156,18','52,152,219','155,89,182'];

  function clamp(v,lo,hi){{return Math.max(lo,Math.min(hi,v));}}

  // ── 位置スコア計算 ───────────────────────────────────────────
  // ペース×脚質×フェーズごとの調整テーブル (base への加算値)
  // 中盤: ペースによる圧縮・伸長
  // 中盤: ペースで隊列がじわじわ変化
  const MID_ADJ = {{
    // ハイ: 逃げが番手に詰め寄られ、差し/追込は前に出てこない（まだ脚を温存）
    'high': {{'逃げ': 0.3,'先行': 0.1,'差し':-0.1,'追込':-0.2}},
    'mid':  {{'逃げ': 0.0,'先行': 0.0,'差し': 0.0,'追込': 0.0}},
    // スロー: 逃げ/番手が更に前に行き、後方は置かれる
    'low':  {{'逃げ':-0.1,'先行':-0.2,'差し': 0.0,'追込': 0.0}},
  }};
  // 終盤: 脚質の本領発揮 + ペース補正
  // 実績ベース: ハイペースでは番手(先行)が最有利、逃げは消耗、差し/追込は届くが過大評価しない
  const FIN_ADJ = {{
    'high': {{'逃げ': 1.5,'先行': 0.2,'差し':-0.4,'追込':-0.6}},
    'mid':  {{'逃げ': 0.3,'先行': 0.0,'差し':-0.4,'追込':-0.7}},
    // スロー: 前が残る。差し/追込は全く伸びない
    'low':  {{'逃げ': 0.0,'先行':-0.1,'差し':-0.3,'追込':-0.5}},
  }};

  function frontScore(horse, phase){{
    const kyaku = horse.kyaku || '差し';
    const base  = KYAKU_BASE[kyaku] !== undefined ? KYAKU_BASE[kyaku] : 2.0;
    const tenR  = horse.ten_r;   // null or 1..N
    const agaR  = horse.aga_r;   // null or 1..N

    // テン速度補正: rank1(最速)→前、rankN(最遅)→後
    let tenAdj = 0;
    if (tenR != null && N > 1) {{
      tenAdj = ((tenR - 1) / (N - 1) - 0.35) * 1.2;
    }}
    // 上がり速度補正: rank1(最速)→前、rankN(最遅)→後
    let agaAdj = 0;
    if (agaR != null && N > 1) {{
      agaAdj = ((agaR - 1) / (N - 1) - 0.35) * 1.8;
    }}

    const p = MID_ADJ[pace] ? pace : 'mid';

    if (phase === 'start') {{
      // 序盤: 脚質基本 + テン速度補正
      return clamp(base + tenAdj, 0, 3);
    }}
    if (phase === 'mid') {{
      // 中盤: ペースで隊列変化 + テン速度少量
      const adj = (MID_ADJ[p][kyaku] !== undefined) ? MID_ADJ[p][kyaku] : 0;
      return clamp(base + adj + tenAdj * 0.3, 0, 3);
    }}
    // 終盤: ペース+脚質テーブル + 上がり速度補正
    const adj = (FIN_ADJ[p][kyaku] !== undefined) ? FIN_ADJ[p][kyaku] : 0;
    return clamp(base + adj + agaAdj, 0, 3);
  }}

  function getZone(fs){{
    if (fs < ZONE_CUTS[0]) return 0;
    if (fs < ZONE_CUTS[1]) return 1;
    if (fs < ZONE_CUTS[2]) return 2;
    return 3;
  }}

  // 内外スコア (枠番1→0, 枠番8→1)
  function innerScore(horse){{
    const w = horse.waku || horse.uma || 4;
    // 右回りは内外表示を反転（枠番1が右側＝内側）
    return direction === '右' ? (8 - w) / 7 : (w - 1) / 7;
  }}

  const phases = [
    {{key:'start', label:'序盤',  desc:'テン速度・脚質で位置取り決定'}},
    {{key:'mid',   label:'中盤',  desc:'ペース×脚質で隊列が変化'}},
    {{key:'finish',label:'終盤',  desc:'上がり速度・脚質で大きく変動'}},
  ];

  const container = document.getElementById('formation-panels');
  if (!container) return;

  // カスタムツールチップ
  const _tip = document.createElement('div');
  _tip.style.cssText = [
    'position:fixed;display:none;z-index:9999;pointer-events:none;',
    'background:#0f1923;border:1px solid #f1c40f;border-radius:8px;',
    'padding:8px 12px;font-size:12px;color:#e0e0e0;',
    'box-shadow:0 4px 16px rgba(0,0,0,0.6);line-height:1.7;white-space:nowrap;'
  ].join('');
  document.body.appendChild(_tip);
  const _showTip = (e, html) => {{
    _tip.innerHTML = html;
    _tip.style.display = 'block';
    _tip.style.left = (e.clientX + 14) + 'px';
    _tip.style.top  = (e.clientY - 8)  + 'px';
  }};
  const _moveTip = (e) => {{
    _tip.style.left = (e.clientX + 14) + 'px';
    _tip.style.top  = (e.clientY - 8)  + 'px';
  }};
  const _hideTip = () => {{ _tip.style.display = 'none'; }};


  phases.forEach(ph => {{
    // ゾーン別に馬を分類 (inner順)
    const zones = [[],[],[],[]];
    fHorses.forEach(h => {{
      const fs = frontScore(h, ph.key);
      const z  = getZone(fs);
      zones[z].push({{...h, inner: innerScore(h), fs}});
    }});
    // 右回りは逆ソート（内側が右）
    const innerDir = direction === '右' ? -1 : 1;
    zones.forEach(z => z.sort((a,b) => innerDir * (a.inner - b.inner)));

    // パネル本体
    const wrap = document.createElement('div');
    wrap.style.cssText = 'flex:1;min-width:280px;max-width:420px';

    const titleEl = document.createElement('div');
    titleEl.style.cssText = 'text-align:center;font-weight:700;font-size:14px;color:#f1c40f;margin-bottom:3px';
    titleEl.textContent = ph.label;
    wrap.appendChild(titleEl);

    const subEl = document.createElement('div');
    subEl.style.cssText = 'text-align:center;font-size:10px;color:#7f8c8d;margin-bottom:6px';
    subEl.textContent = ph.desc;
    wrap.appendChild(subEl);

    const board = document.createElement('div');
    board.style.cssText = 'background:#1a252f;border:1px solid #2c3e50;border-radius:8px;padding:8px;';

    const goalLbl = document.createElement('div');
    goalLbl.style.cssText = 'text-align:center;font-size:10px;color:#556;margin-bottom:4px';
    goalLbl.textContent = '↑ ゴール / 前方';
    board.appendChild(goalLbl);

    const axisRow = document.createElement('div');
    axisRow.style.cssText = 'display:flex;justify-content:space-between;font-size:9px;color:#445;margin-bottom:4px;padding:0 2px';
    axisRow.innerHTML = direction === '右'
      ? '<span>外 →</span><span>← 内</span>'
      : '<span>内 →</span><span>← 外</span>';
    board.appendChild(axisRow);

    zones.forEach((zHorses, zi) => {{
      const row = document.createElement('div');
      row.style.cssText = [
        'display:flex;align-items:center;gap:4px;flex-wrap:wrap;',
        'min-height:54px;padding:4px 4px;margin-bottom:3px;',
        'border-radius:5px;overflow:visible;',
        `background:rgba(${{ZONE_RGBA[zi]}},0.08);`,
        `border-left:3px solid ${{ZONE_COLORS[zi]}};`,
      ].join('');

      const zoneLbl = document.createElement('span');
      zoneLbl.style.cssText = `min-width:28px;font-size:9px;font-weight:700;color:${{ZONE_COLORS[zi]}};white-space:nowrap`;
      zoneLbl.textContent = ZONE_LABELS[zi];
      row.appendChild(zoneLbl);

      const chips = document.createElement('div');
      chips.style.cssText = 'display:flex;flex-wrap:wrap;gap:4px;flex:1;justify-content:center;align-content:center;';

      if (zHorses.length === 0) {{
        const empty = document.createElement('span');
        empty.style.cssText = 'font-size:10px;color:#445;font-style:italic';
        empty.textContent = '—';
        chips.appendChild(empty);
      }} else {{
        zHorses.forEach(h => {{
          const waku = h.waku || 1;
          const bg   = WAKU_BG[waku] || '#888';
          const fg   = WAKU_FG[waku] || '#fff';
          const chip = document.createElement('div');
          const _tipLines = [
            `<b style='color:#f1c40f'>${{h.name}}</b>`,
            `${{h.kyaku}} &nbsp;|&nbsp; ${{h.waku}}枠 ${{h.uma}}番`,
          ];
          _tipLines.push(`テン速度順位: <b style='color:#3498db'>${{h.ten_r != null ? h.ten_r + '位' : '---'}}</b>`);
          _tipLines.push(`上がり速度順位: <b style='color:#e74c3c'>${{h.aga_r != null ? h.aga_r + '位' : '---'}}</b>`);
          const _tipHtml = _tipLines.join('<br>');
          chip.addEventListener('mouseenter', e => _showTip(e, _tipHtml));
          chip.addEventListener('mousemove',  e => _moveTip(e));
          chip.addEventListener('mouseleave', () => _hideTip());
          chip.style.cssText = [
            `background:${{bg}};color:${{fg}};`,
            'border-radius:50%;width:26px;height:26px;',
            'display:flex;align-items:center;justify-content:center;',
            'font-size:11px;font-weight:700;cursor:pointer;flex-shrink:0;',
            'box-shadow:0 0 0 1px rgba(255,255,255,0.25);',
          ].join('');
          chip.textContent = h.uma != null ? h.uma : '?';
          chips.appendChild(chip);
        }});
      }}
      row.appendChild(chips);
      const _rsp = document.createElement('span');
      _rsp.style.cssText = 'min-width:28px;flex-shrink:0';
      row.appendChild(_rsp);
      board.appendChild(row);
    }});

    const backLbl = document.createElement('div');
    backLbl.style.cssText = 'text-align:center;font-size:10px;color:#556;margin-top:4px';
    backLbl.textContent = '後方 / スタート側 ↓';
    board.appendChild(backLbl);

    wrap.appendChild(board);
    container.appendChild(wrap);
  }});
}})();
</script>'''


# ── HTML ─────────────────────────────────────────────────────
html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<title>競馬予想 — {_display_title or f'{race_place}{race_r}R {race_class}'} {race_date_str}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: "Noto Sans JP", "Hiragino Kaku Gothic ProN", "Yu Gothic UI",
                 "Yu Gothic", Meiryo, -apple-system, BlinkMacSystemFont,
                 "Segoe UI", sans-serif;
    font-size: 14px;
    line-height: 1.5;
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    color: #e0e0e0;
    padding: 24px;
    min-height: 100vh;
  }}
  .container {{ max-width: 1360px; margin: 0 auto; }}

  header {{
    background: rgba(255,255,255,0.06);
    backdrop-filter: blur(10px);
    border-radius: 16px;
    padding: 28px 32px;
    margin-bottom: 16px;
    border: 1px solid rgba(255,255,255,0.1);
  }}
  h1 {{ font-size: 28px; color: #f1c40f; margin-bottom: 8px; letter-spacing: 1px; }}
  .subtitle {{ font-size: 14px; color: #95a5a6; }}
  .summary-bar {{
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 16px; margin-top: 20px;
  }}
  .summary-item {{
    background: rgba(255,255,255,0.05);
    padding: 16px; border-radius: 10px; text-align: center;
  }}
  .summary-value {{
    font-size: 26px; font-weight: bold; color: #f39c12;
    word-break: break-all; line-height: 1.2;
  }}
  .summary-value.small {{ font-size: 16px; }}
  .summary-value.xsmall {{ font-size: 13px; }}
  .summary-label {{ font-size: 12px; color: #bdc3c7; margin-top: 4px; }}

  .shutuba-banner {{
    background: rgba(39,174,96,0.15);
    border: 1px solid rgba(39,174,96,0.4);
    border-radius: 10px; padding: 12px 20px;
    margin-bottom: 16px; font-size: 14px; color: #a9dfbf;
  }}
  .shutuba-banner.warning {{
    background: rgba(241,196,15,0.1);
    border-color: rgba(241,196,15,0.4); color: #f9e79f;
  }}

  .section {{
    background: rgba(255,255,255,0.06);
    border-radius: 16px; padding: 28px;
    margin-bottom: 24px;
    border: 1px solid rgba(255,255,255,0.1);
  }}
  .section h2 {{
    color: #f1c40f; font-size: 20px;
    margin-bottom: 20px;
    border-bottom: 2px solid rgba(241,196,15,0.3);
    padding-bottom: 8px;
  }}

  .podium {{
    display: grid; grid-template-columns: 1fr 1fr 1fr;
    gap: 20px; margin-bottom: 24px;
  }}
  .podium-card {{
    background: linear-gradient(160deg, rgba(255,255,255,0.08), rgba(255,255,255,0.02));
    border: 2px solid rgba(241,196,15,0.4);
    border-radius: 14px; padding: 20px; text-align: center;
    transition: transform 0.2s;
  }}
  .podium-card:hover {{ transform: translateY(-4px); }}
  .podium-card.first  {{ border-color: #f1c40f; box-shadow: 0 8px 24px rgba(241,196,15,0.3); }}
  .podium-card.second {{ border-color: #bdc3c7; }}
  .podium-card.third  {{ border-color: #cd7f32; }}
  .podium-mark  {{ font-size: 48px; line-height: 1; margin-bottom: 8px; }}
  .podium-name  {{ font-size: 22px; font-weight: bold; color: #fff; margin-bottom: 6px; }}
  .podium-info  {{ font-size: 13px; color: #bdc3c7; margin-bottom: 10px; }}
  .podium-score {{ font-size: 30px; font-weight: bold; color: #f39c12; }}

  .leg-grid {{ display: grid; gap: 10px; }}
  .leg-item {{
    display: grid; grid-template-columns: 16px 60px 50px 1fr;
    align-items: center; gap: 12px; font-size: 14px;
  }}
  .leg-color {{ width: 16px; height: 16px; border-radius: 4px; }}
  .leg-count {{ color: #95a5a6; }}
  .leg-bar {{ height: 8px; background: rgba(255,255,255,0.08); border-radius: 4px; overflow: hidden; }}
  .leg-fill {{ height: 100%; transition: width 0.4s; }}

  .pace-box {{
    background: rgba(231,76,60,0.15);
    border-left: 4px solid #e74c3c;
    padding: 16px 20px; border-radius: 8px; margin-bottom: 20px;
  }}
  .pace-title {{ font-size: 18px; color: #e74c3c; font-weight: bold; margin-bottom: 6px; }}

  /* ── EV シミュレーター ── */
  .ev-tab {{ background:#2c3e50; border:1px solid #4a5f72; color:#bdc3c7;
             padding:6px 18px; border-radius:6px 6px 0 0; cursor:pointer; font-size:13px; font-weight:600; }}
  .ev-tab.active {{ background:#f1c40f; color:#1a1a2e; border-color:#f1c40f; }}
  .ev-tab:hover:not(.active) {{ background:#3d5166; }}
  #evHead th {{ cursor:pointer; user-select:none; white-space:nowrap; }}
  #evHead th:hover {{ background:#3d5166; }}
  .ev-table-wrap {{ overflow-x: auto; }}
  .ev-table {{ width: 100%; border-collapse: collapse; font-size: 12px; white-space: nowrap; }}
  .ev-table th, .ev-table td {{
    padding: 5px 8px; text-align: center;
    border-bottom: 1px solid rgba(255,255,255,0.08);
  }}
  .ev-table th {{ background: rgba(255,255,255,0.05); color: #f1c40f; }}
  .ev-table tr:hover {{ background: rgba(255,255,255,0.04); }}
  .ev-positive {{ color: #2ecc71; font-weight: bold; }}
  .ev-negative {{ color: #e74c3c; }}
  .ev-neutral  {{ color: #95a5a6; }}
  .ev-bar {{ height: 6px; border-radius: 3px; margin: 2px auto; max-width: 80px; }}
  .prob-note {{ font-size: 11px; color: #7f8c8d; margin-top: 12px; }}
  .temp-slider {{ display:flex; align-items:center; gap:12px; margin-bottom:14px; font-size:13px; }}
  .temp-slider input {{ width:120px; accent-color:#f1c40f; }}

  /* ── 馬カード ── */
  .horses-grid {{ display: grid; gap: 16px; }}
  .horse-card {{
    background: rgba(255,255,255,0.04);
    border-radius: 12px; padding: 20px;
    display: grid; grid-template-columns: 80px 1fr;
    gap: 20px;
    border-left: 4px solid rgba(255,255,255,0.1);
    transition: background 0.2s;
  }}
  .horse-card:hover {{ background: rgba(255,255,255,0.07); }}
  .horse-card.rank-1 {{ border-left-color: #f1c40f; background: rgba(241,196,15,0.08); }}
  .horse-card.rank-2 {{ border-left-color: #bdc3c7; background: rgba(189,195,199,0.06); }}
  .horse-card.rank-3 {{ border-left-color: #cd7f32; background: rgba(205,127,50,0.06); }}

  .rank-badge {{
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    border-radius: 10px; padding: 12px 8px;
    color: #fff; text-align: center;
  }}
  .rank-num   {{ font-size: 28px; font-weight: bold; line-height: 1; }}
  .rank-label {{ font-size: 11px; opacity: 0.8; margin-top: 2px; }}

  .horse-header {{
    display: flex; align-items: center;
    gap: 8px; margin-bottom: 12px; flex-wrap: wrap;
  }}
  .horse-header h3 {{ font-size: 20px; color: #fff; }}

  .waku-badge {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 38px; height: 26px;
    border-radius: 5px; font-size: 12px; font-weight: bold;
    border: 1px solid rgba(255,255,255,0.3); flex-shrink: 0;
  }}
  .bango-badge {{
    display: inline-flex; align-items: center; justify-content: center;
    width: 38px; height: 26px;
    border-radius: 5px; font-size: 12px; font-weight: bold;
    border: 1px solid rgba(255,255,255,0.3); flex-shrink: 0;
  }}
  .leg-badge {{
    padding: 3px 10px; border-radius: 12px;
    font-size: 12px; color: #fff; font-weight: bold;
  }}
  .adj-badge {{
    padding: 2px 8px; border-radius: 10px;
    font-size: 11px; color: #fff; font-weight: bold; opacity: 0.9;
  }}
  .meta-info {{ font-size: 12px; color: #95a5a6; margin-left: auto; }}

  .drill-btn {{
    background: rgba(241,196,15,0.15);
    border: 1px solid rgba(241,196,15,0.4);
    color: #f1c40f; border-radius: 8px;
    padding: 4px 12px; font-size: 12px; cursor: pointer;
    transition: background 0.2s; flex-shrink: 0;
  }}
  .drill-btn:hover {{ background: rgba(241,196,15,0.25); }}
  .drill-btn.active {{ background: rgba(241,196,15,0.35); }}

  .score-row {{
    display: grid; grid-template-columns: 110px 1fr;
    gap: 16px; margin-bottom: 12px;
  }}
  .total-score {{
    background: rgba(0,0,0,0.3);
    border-radius: 10px; padding: 12px; text-align: center;
    display: flex; flex-direction: column; justify-content: center;
  }}
  .big-num    {{ font-size: 32px; font-weight: bold; color: #f1c40f; line-height: 1; }}
  .small-label {{ font-size: 11px; color: #7f8c8d; margin-top: 4px; }}

  .score-bars {{ display: grid; gap: 4px; }}
  .bar-row {{
    display: grid; grid-template-columns: 76px 1fr 68px;
    align-items: center; gap: 8px; font-size: 12px;
  }}
  .bar-row label {{ color: #bdc3c7; }}
  .adj-row {{ opacity: 0.85; }}
  .adj-row label {{ font-size: 11px; color: #95a5a6; }}

  .bar {{
    height: 8px; background: rgba(255,255,255,0.08);
    border-radius: 4px; overflow: hidden; position: relative;
  }}
  .bar.bipolar {{
    background: linear-gradient(to right,
      rgba(231,76,60,0.15) 50%, rgba(46,204,113,0.15) 50%);
  }}
  .bar.bipolar .fill {{ position: absolute; height: 100%; }}
  .bar.bipolar .fill.plus  {{ left: 50%; background: #2ecc71; }}
  .bar.bipolar .fill.minus {{ right: 50%; background: #e74c3c; }}
  .fill {{ height: 100%; transition: width 0.5s; }}
  .val  {{ color: #95a5a6; font-size: 11px; text-align: right; }}

  .extra-info {{
    display: flex; flex-wrap: wrap; gap: 14px;
    font-size: 12px; color: #95a5a6;
    padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.06);
  }}
  .extra-info b {{ color: #ecf0f1; }}

  /* ── 過去走ドリルダウン ── */
  .drilldown-wrap {{
    margin-top: 16px;
    background: rgba(0,0,0,0.25);
    border-radius: 10px; padding: 16px;
    border: 1px solid rgba(255,255,255,0.08);
  }}
  .drilldown-header {{
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 10px; font-size: 14px; font-weight: bold; color: #f1c40f;
    flex-wrap: wrap; gap: 8px;
  }}
  .drill-legend {{ font-size: 11px; font-weight: normal; color: #95a5a6; }}
  .drill-legend span {{ margin: 0 2px; }}

  .past-table {{ width: 100%; border-collapse: collapse; font-size: 12px; white-space: nowrap; }}
  .past-table th, .past-table td {{
    padding: 6px 8px; border-bottom: 1px solid rgba(255,255,255,0.06);
  }}
  .past-table th {{ background: rgba(255,255,255,0.04); color: #bdc3c7; font-weight: 600; }}
  .past-table tr:hover {{ background: rgba(255,255,255,0.04); }}
  .past-table td.center {{ text-align: center; }}

  .course-tag {{
    background: rgba(52,152,219,0.2);
    border-radius: 4px; padding: 1px 5px; font-size: 11px;
  }}
  .td-pos  {{ color: #2ecc71; font-weight: bold; }}
  .td-neg  {{ color: #e74c3c; font-weight: bold; }}
  .sim-hi  {{ color: #2ecc71; font-weight: bold; }}
  .sim-mid {{ color: #f39c12; }}
  .sim-lo  {{ color: #e74c3c; }}
  .pci-hi  {{ color: #e74c3c; }}
  .pci-lo  {{ color: #3498db; }}
  .no-data {{ color: #95a5a6; font-style: italic; font-size: 13px; padding: 8px; }}

  /* ── 印テーブル ── */
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid rgba(255,255,255,0.08); }}
  th {{ background: rgba(255,255,255,0.05); color: #f1c40f; font-weight: 600; }}
  .mini-badge {{
    display: inline-block; padding: 1px 6px; border-radius: 8px;
    font-size: 10px; font-weight: bold; color: #fff; margin-left: 4px;
  }}
  .mini-badge.red    {{ background: #c0392b; }}
  .mini-badge.green  {{ background: #27ae60; }}
  .mini-badge.purple {{ background: #8e44ad; }}
  .mini-badge.blue   {{ background: #2980b9; }}
  .mini-badge.orange {{ background: #e67e22; }}

  .buy-list {{ display: grid; gap: 10px; }}
  .buy-item {{
    background: rgba(255,255,255,0.04);
    padding: 14px 18px; border-radius: 10px;
    border-left: 3px solid #f39c12;
  }}


  .adj-legend {{
    display: flex; gap: 14px; flex-wrap: wrap;
    margin-top: 12px; font-size: 12px;
  }}
  .adj-legend-item {{ display: flex; align-items: center; gap: 6px; color: #bdc3c7; }}
  .adj-dot {{ width: 10px; height: 10px; border-radius: 50%; }}

  .trust-badge {{ display:inline-block;padding:2px 6px;border-radius:8px;font-size:10px;font-weight:600;margin-left:4px;vertical-align:middle; }}
  .trust-hi   {{ background:#1a5276;color:#85c1e9; }}
  .trust-mid  {{ background:#1e8449;color:#a9dfbf; }}
  .trust-lo   {{ background:#7d6608;color:#f9e79f; }}
  .trust-none {{ background:#4a235a;color:#d7bde2; }}
  .chart-wrap-xl {{ position:relative;height:460px;margin-bottom:8px; }}
  footer {{
    text-align: center; padding: 20px; color: #7f8c8d; font-size: 12px; }}

  @media (max-width: 768px) {{
    body {{ padding: 12px; }}
    .summary-bar {{ grid-template-columns: repeat(2, 1fr); }}
    .podium {{ grid-template-columns: 1fr; }}
    .horse-card {{ grid-template-columns: 60px 1fr; gap: 12px; padding: 14px; }}
    .score-row {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="container">

  <header>
    <h1>🐎 競馬予想 — {_display_title or f'{race_place}{race_r}R {race_class}'}</h1>
    <div class="subtitle">{race_date_str} ・ {race_place}{race_r}R {race_track}{race_dist}m ・ {race_class} ・ {race_heads}頭立て ・ 16要素スコアリングモデル</div>
    <div class="summary-bar">
      <div class="summary-item">
        <div class="summary-value">{len(horses)}</div>
        <div class="summary-label">出走頭数</div>
      </div>
      <div class="summary-item">
        {(lambda t: f'<div class="summary-value{" xsmall" if len(t)>10 else " small" if len(t)>7 else ""}">{t}</div>')(meta["pace"].replace("想定",""))}
        <div class="summary-label">ペース予想</div>
      </div>
      <div class="summary-item">
        {(lambda t: f'<div class="summary-value{" small" if len(t)>5 else ""}">{t}</div>')(horses[0]["馬名"])}
        <div class="summary-label">最高スコア馬</div>
      </div>
      <div class="summary-item">
        <div class="summary-value">{horses[0]["総合スコア"]:.1f}<span style="font-size:10px;color:#f1c40f;font-weight:700;margin-left:4px">(偏差{_dev_map.get(horses[0]["馬名"],50)})</span></div>
        <div class="summary-label">最高スコア</div>
      </div>
    </div>
  </header>

  {shutuba_banner}
  {baba_banner}

  <div class="section">
    <h2>🏆 上位3頭 予想</h2>
    <div class="podium">
      <div class="podium-card first">
        <div class="podium-mark">🥇</div>
        <div class="podium-name">{honmei["馬名"]}</div>
        <div class="podium-info">{podium_waku_str(honmei)}{honmei["脚質"]} ・ {honmei["騎手"]} ・ {podium_smartrc_pop(honmei)}</div>
        <div class="podium-score">{honmei["総合スコア"]:.1f}<div class="podium-dev" style="font-size:10px;color:#f1c40f;font-weight:700;margin-top:2px">偏差値 {_dev_map.get(honmei["馬名"],50)}</div></div>
      </div>
      <div class="podium-card second">
        <div class="podium-mark">🥈</div>
        <div class="podium-name">{taikou["馬名"]}</div>
        <div class="podium-info">{podium_waku_str(taikou)}{taikou["脚質"]} ・ {taikou["騎手"]} ・ {podium_smartrc_pop(taikou)}</div>
        <div class="podium-score">{taikou["総合スコア"]:.1f}<div class="podium-dev" style="font-size:10px;color:#f1c40f;font-weight:700;margin-top:2px">偏差値 {_dev_map.get(taikou["馬名"],50)}</div></div>
      </div>
      <div class="podium-card third">
        <div class="podium-mark">🥉</div>
        <div class="podium-name">{tanana["馬名"]}</div>
        <div class="podium-info">{podium_waku_str(tanana)}{tanana["脚質"]} ・ {tanana["騎手"]} ・ {podium_smartrc_pop(tanana)}</div>
        <div class="podium-score">{tanana["総合スコア"]:.1f}<div class="podium-dev" style="font-size:10px;color:#f1c40f;font-weight:700;margin-top:2px">偏差値 {_dev_map.get(tanana["馬名"],50)}</div></div>
      </div>
    </div>
  </div>


  <!-- 期待値シミュレーター -->
  <div class="section">
    <h2>💰 期待値シミュレーター</h2>
    <!-- 1行目: 市場乖離バナー（妙味判定のみ） -->
    <div style="display:flex;align-items:center;flex-wrap:wrap;gap:8px;
                padding:10px 16px;margin-bottom:8px;border-radius:8px;
                background:{_rec_bg};border:1px solid {_rec_color};">
      <span style="font-size:15px;font-weight:900;color:{_rec_color};
                   padding:3px 14px;border-radius:5px;border:2px solid {_rec_color};">
        {_rec_badge}
      </span>
      <span style="color:#ccc;font-size:12px;">{_rec_reason}</span>
    </div>
    <!-- 2行目: 注目馬 / 本命馬自信あり バッジエリア（該当なければ非表示） -->
    {_badge_area_html}
    <!-- 3行目: モデル信頼度スライダー -->
    <div class="temp-slider" style="margin-bottom:14px;">
      <label style="font-weight:600">モデル信頼度</label>
      <span style="color:#7f8c8d;font-size:11px">本命重視</span>
      <input type="range" id="tempSlider" min="5" max="50" step="1" value="20">
      <span style="color:#7f8c8d;font-size:11px">混戦想定</span>
      <span style="margin-left:8px;font-weight:600" id="tempVal">20</span>
      <span style="color:#7f8c8d;font-size:11px;margin-left:2px">（T値 — 小:上位集中 / 大:全馬分散）</span>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:12px">
      <button class="ev-tab active" id="tabTanshо" onclick="switchTab('tansho')">単勝 EV</button>
      <button class="ev-tab" id="tabFukusho" onclick="switchTab('fukusho')">複勝 EV</button>
    </div>
    <div class="ev-table-wrap">
      <table class="ev-table" id="evTable">
        <thead>
          <tr id="evHead">
            <th data-col="waku" onclick="sortEV(this)">枠-番 ▲</th>
            <th data-col="name" onclick="sortEV(this)">馬名</th>
            <th data-col="leg" onclick="sortEV(this)">脚質</th>
            <th data-col="score" onclick="sortEV(this)">スコア</th>
            <th data-col="rank" onclick="sortEV(this)">予想順位</th>
            <th data-col="src_ninki" onclick="sortEV(this)" title="SmartRC推定人気順">推定人気</th>
            <th data-col="kairido" onclick="sortEV(this)" title="SmartRC推定人気順 − スコア順位（プラスほど穴馬）">乖離度</th>
            <th data-col="prob" id="thProb" onclick="sortEV(this)">勝率推定</th>
            <th data-col="breakeven" id="thBreakEven" onclick="sortEV(this)">採算オッズ</th>
            <th data-col="odds" id="thOdds" onclick="sortEV(this)">現在オッズ（入力可）</th>
            <th data-col="ev" onclick="sortEV(this)">期待値 (EV)</th>
            <th data-col="judge" onclick="sortEV(this)">判定</th>
          </tr>
        </thead>
        <tbody id="evBody"></tbody>
      </table>
    </div>
    <div class="prob-note" id="evNote">
      ※ 勝率はスコアのsoftmax変換による推定値。単勝EV = 勝率推定 × 現在オッズ − 1。<br>
      <b>採算オッズ</b> = EV がちょうど 0 になるオッズ（損益分岐点）。実オッズ ≥ 採算オッズなら EV プラスの可能性。<br>
      現在オッズ欄に締切前の実オッズを入力すると EV が即時更新されます。
    </div>
  </div>

  <div class="section">
    <h2>📊 全出走馬一覧</h2>
    <div style="overflow-x:auto">
    <table style="min-width:560px">
      <thead>
        <tr>
          <th style="white-space:nowrap">順位</th><th style="white-space:nowrap">枠-番</th><th style="white-space:nowrap">馬名</th>
          <th style="white-space:nowrap">脚質</th><th style="white-space:nowrap">スコア</th><th style="white-space:nowrap">市場評価</th>
          <th style="white-space:nowrap" title="SmartRC推定人気順">推定人気</th>
          <th style="white-space:nowrap" title="前走の馬場・展開有利不利評価 A/B=不利→巻き返し候補 D/E=有利→過信注意">前走評価</th>
          <th style="white-space:nowrap">斤量</th>
          <th style="white-space:nowrap">年齢・性別</th>
          <th style="white-space:nowrap">騎手</th>
        </tr>
      </thead>
      <tbody>{all_marks}</tbody>
    </table>
    </div>
  </div>

  <div class="section">
    <h2>🏃 展開予想 / 脚質構成</h2>
    <div class="pace-box">
      <div class="pace-title">{meta["pace"]}</div>
      <div>逃げ・先行馬が <b>{leg_counts.get("逃げ",0) + leg_counts.get("先行",0)}頭</b> 揃い、展開面での有利・不利が生じます。</div>
    </div>
    <div class="leg-grid">{leg_html}</div>
  </div>

{_formation_html}

{_matrix_html}

  <div class="section">
    <h2>📊 補正項目の積み上げ比較（全馬）</h2>
    <div class="chart-wrap-xl"><canvas id="scoreStackChart"></canvas></div>
    <div class="prob-note">各馬の補正項目を積み上げで比較。ゼロ以上が加点、以下が減点要因。予想順位順で左から表示。</div>
  </div>

  <div class="section">
    <h2>🏆 補正項目別ランキング</h2>
    <div class="prob-note">各補正項目のスコアが高い順に全馬を並べて表示。同点の場合は馬番順。</div>
    <div id="itemRankingGrid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin-top:14px"></div>
  </div>

  <div class="section">
    <h2>💡 スコア補正の見方（16要素）</h2>
    <div class="adj-legend">
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#e74c3c"></div>
        <span><b>最高出力</b>（35pt）: 全過去走の補正タイム最良値を偏差値化</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#ff7f0e"></div>
        <span><b>クラス補正</b>（25pt・出走数補正あり）: クラス重み×着順スコアの加重平均</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#1f77b4"></div>
        <span><b>タイム偏差</b>（25pt）: コース平均との差 [A-1 馬場状態補正込み]</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#9467bd"></div>
        <span><b>展開適性</b>（±2pt）: 枠番・頭数・コース特性（コーナー区分）による内枠先行有利度 × 過去走平均4角通過順実績 → 位置取り確率スコア</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#2ca02c"></div>
        <span><b>斤量補正</b>（±3pt）: 今走斤量 vs 過去平均</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#e377c2"></div>
        <span><b>距離補正</b>（-2〜+2pt）: 前走から400m以上の距離延長のみ-2pt + 同コース種別×距離帯TGX≥95なら+2pt</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#17becf"></div>
        <span><b>コース適性</b>（±10pt）: 過去コースの特性類似度（コーナー区分/回り/直線/坂）</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#8c564b"></div>
        <span><b>臨戦補正</b>（-4〜+1pt）: 出走間隔7段階（連闘−1/中1週−1/標準0/中5〜8週+1/3〜4ヶ月−1/4〜6ヶ月−2/6ヶ月超−4）</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#bcbd22"></div>
        <span><b>人気補正</b>（0〜+3pt）: 1〜3番人気馬がモデルスコア中央値を下回る場合に上方補正（1番人気+3、2番人気+2、3番人気+1.5）</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#aec7e8"></div>
        <span><b>騎手実績</b>（±2pt）: 過去データ全体から算出 (Bayesian収縮)</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#7f7f7f"></div>
        <span><b>馬体重増減</b>（0/−1pt）: ±12〜19kgで−0.5、±20kg以上で−1pt</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#98df8a"></div>
        <span><b>継続騎乗</b>（0/+1pt）: 前走と同騎手で継続騎乗なら加点</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#dbdb8d"></div>
        <span><b>前走着差</b>（−2〜+1pt）: 1着/0.5秒以内+1 / 0.6〜1.0秒±0 / 1.1〜2.0秒−1 / 2.1秒超−2</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#9edae5"></div>
        <span><b>枠順補正</b>（±2pt）: 芝スタートダートは外枠加点 / 通常コースは逃先内枠加点・逃げ大外減点</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#c5b0d5"></div>
        <span><b>昇級戦補正</b>（0〜−3pt）: 1クラス昇級−1、2クラス昇級−2、3クラス以上昇級−3</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#1abc9c"></div>
        <span><b>クラス適応補正</b>（−2〜+1.5pt）: 今走クラス以上での直近5走（1年以内）の1位との着差加重平均で適応度を評価。着差≤0.2秒→+1.5pt（好走継続）、≤0.5秒→+0.8pt、≤1.0秒→0pt、≤1.8秒→-1.0pt、>1.8秒→-2.0pt（壁）。最低2走以上のデータが必要。未勝利クラスは加点上限+0.5pt。</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#f39c12"></div>
        <span><b>SmartRC評価補正</b>（−4.5〜+4.5pt）: 過去5走の馬場・展開有利不利評価（h1〜h5_fr_baba）を加重平均（前走×1.0/前々走×0.6/以降逓減）。A=+4.5/B=+2.5pt 上方修正、D=−2.5/E=−4.5pt 下方修正、C=0pt</span>
      </div>
      <div class="adj-legend-item">
        <div class="adj-dot" style="background:#16a085"></div>
        <span><b>馬場適性</b>（−2〜+3pt）: 過去走の同馬場条件（良/稍重/重/不良）における勝率・複勝率・平均着順率を算出。同馬場2走未満の場合は隣接馬場の成績を0.5倍で補完</span>
      </div>
    </div>
  </div>

  <div class="section">
    <h2>🐴 全18頭 詳細スコア（📋で過去走ドリルダウン）</h2>
    <div class="horses-grid">{horse_cards}</div>
  </div>

  <footer>
    生成: {race_date_str} ・ データ: TARGET JV frontier + course-db.com ・ スコアモデル v3（16要素）
  </footer>
</div>

<script>
// ── B-2 ドリルダウントグル ──────────────────────────────────
function toggleDrill(id, btn) {{
  const el = document.getElementById('drill-' + id);
  if (!el) return;
  const isVisible = el.style.display !== 'none';
  el.style.display = isVisible ? 'none' : 'block';
  btn.classList.toggle('active', !isVisible);
  btn.textContent = isVisible ? '📋 過去走' : '📋 閉じる';
}}

// ── 期待値シミュレーター ─────────────────────────────────
const EV_DATA = {ev_data_json};
// WAKU_BG をメインJSスコープで定義（renderRows内のwakuバッジで参照）
const WAKU_BG = {{1:'#ffffff',2:'#555555',3:'#ee3333',4:'#4488ff',5:'#dddd00',6:'#22bb22',7:'#ff8822',8:'#ffaacc'}};
const WAKU_FG = {{1:'#111',2:'#eee',3:'#fff',4:'#fff',5:'#111',6:'#fff',7:'#111',8:'#111'}};
let currentTab = 'tansho';
let sortCol    = 'score';
let sortAsc    = false;   // default: スコア降順
let _userOdds  = {{}};     // 馬番 → ユーザー手入力オッズ（採算オッズで初期化 → 手入力で上書き）

// Harville式 上位k着以内確率
function placeProb(probs, idx, k) {{
  const pi = probs[idx];
  const n  = probs.length;
  if (k <= 1) return pi;
  // 2着以内
  let p2 = 0;
  for (let j = 0; j < n; j++) {{
    if (j === idx) continue;
    p2 += probs[j] * pi / Math.max(1e-9, 1 - probs[j]);
  }}
  if (k <= 2) return Math.min(1, pi + p2);
  // 3着以内 (複勝)
  let p3 = 0;
  for (let j = 0; j < n; j++) {{
    if (j === idx) continue;
    for (let m = 0; m < n; m++) {{
      if (m === idx || m === j) continue;
      const d = 1 - probs[j] - probs[m];
      if (d <= 0) continue;
      p3 += probs[j] * (probs[m] / Math.max(1e-9, 1 - probs[j])) * (pi / d);
    }}
  }}
  return Math.min(1, pi + p2 + p3);
}}

function switchTab(tab) {{
  currentTab = tab;
  document.getElementById('tabTanshо').classList.toggle('active', tab === 'tansho');
  document.getElementById('tabFukusho').classList.toggle('active', tab === 'fukusho');
  const isFuku = (tab === 'fukusho');
  document.getElementById('thProb').textContent = isFuku ? '複勝率推定 ▲' : '勝率推定';
  document.getElementById('thOdds').textContent    = isFuku ? '複勝オッズ幅' : '現在オッズ（入力可）';
  document.getElementById('thBreakEven').style.display = isFuku ? 'none' : '';
  document.getElementById('evNote').innerHTML = isFuku
    ? '※ 複勝率はHarville式による上位3着以内確率の推定値（頭数が少ない場合は2着以内）。<br>複勝EV = 複勝率推定 × 複勝オッズ下限 − 1。プラス(緑)は期待値プラスの可能性を示します。'
    : '※ 勝率はスコアのsoftmax変換による推定値。単勝EV = 勝率推定 × 現在オッズ − 1。<br>採算オッズ（損益分岐オッズ）以上の実オッズなら EV プラスの可能性。オッズ欄を入力すると EV が即時更新されます。';
  computeEV(Number(document.getElementById('tempSlider').value));
}}

let _lastRows = [];
function sortEV(th) {{
  const col = th.dataset.col;
  if (sortCol === col) {{ sortAsc = !sortAsc; }}
  else {{ sortCol = col; sortAsc = false; }}
  renderRows(_lastRows);
}}

function colVal(h, col) {{
  switch(col) {{
    case 'waku':  return (h['枠番'] || 99) * 100 + (h['馬番'] || 99);
    case 'name':  return h['馬名'];
    case 'leg':   return h['脚質'];
    case 'score': return h['スコア'];
    case 'rank':    return h['順位予想'];
    case 'kairido': return h['乖離度'] != null ? h['乖離度'] : -99;
    case 'prob':  return h._prob || 0;
    case 'breakeven': return h._prob > 0 ? 1/h._prob : 999;
    case 'odds':  return currentTab === 'fukusho' ? (h['複勝下限'] || 999)
                       : ((_userOdds[h['馬番']] != null ? _userOdds[h['馬番']] : h['オッズ']) || 999);
    case 'ev':    return h._ev !== undefined ? h._ev : -99;
    case 'judge': return h._ev !== undefined ? h._ev : -99;
    default:      return 0;
  }}
}}

function renderRows(rows) {{
  _lastRows = rows;
  // ヘッダのマーカー更新
  document.querySelectorAll('#evHead th').forEach(th => {{
    const base = th.textContent.replace(/ [▲▼]$/, '');
    th.textContent = th.dataset.col === sortCol
      ? base + (sortAsc ? ' ▲' : ' ▼')
      : base;
  }});
  const sorted = [...rows].sort((a, b) => {{
    const va = colVal(a, sortCol), vb = colVal(b, sortCol);
    if (typeof va === 'string') return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
    return sortAsc ? va - vb : vb - va;
  }});

  const isFuku = (currentTab === 'fukusho');
  document.getElementById('evBody').innerHTML = sorted.map(h => {{
    const waku_fg = ['','#222','#fff','#fff','#fff','#222','#fff','#fff','#222'];
    const waku_num = h['枠番'] || 0;
    const waku_bg_c = WAKU_BG[waku_num] || '#888';
    const waku_fg_c = waku_fg[waku_num] || '#fff';
    const waku_b  = h['枠番']
      ? `<span style="display:inline-block;background:${{waku_bg_c}};color:${{waku_fg_c}};font-weight:700;font-size:11px;padding:1px 5px;border-radius:3px;margin-right:2px;">${{h['枠番']}}枠</span><span style="display:inline-block;background:${{waku_bg_c}};color:${{waku_fg_c}};font-weight:700;font-size:11px;padding:1px 5px;border-radius:3px;">${{h['馬番'] || '?'}}番</span>`
      : '<span style="color:#555">未定</span>';
    const probPct = ((h._prob || 0) * 100).toFixed(1) + '%';
    const ev      = h._ev;
    let evStr = '-', evCls = 'ev-neutral', judgement = '-';
    if (ev !== undefined && ev !== null) {{
      evStr = ev.toFixed(3);
      // EV値のみで判定（大穴・通常共通基準）
      if (ev > 0.05)       {{ evCls = 'ev-positive'; judgement = h._isDark ? '⚠ 大穴注意' : '◎ 買い'; }}
      else if (ev >= -0.1) {{ evCls = 'ev-neutral';  judgement = '△ 様子見'; }}
      else                 {{ evCls = 'ev-negative';  judgement = '✕ 見送り'; }}
    }}
    const barWidth = Math.min(100, (h._prob || 0) * 100 * (isFuku ? 2 : 5));
    const barColor = evCls === 'ev-positive' ? '#2ecc71' :
                     evCls === 'ev-negative' ? '#e74c3c' : '#95a5a6';
    // 採算オッズ（案A）: 1/勝率推定 = EV=0となる損益分岐点
    const beOdds   = (!isFuku && h._prob > 0) ? 1/h._prob : null;
    // curOdds: 手入力値 or computeEVで初期化済みの採算オッズ
    const curOdds  = !isFuku ? (_userOdds[h['馬番']] != null ? _userOdds[h['馬番']] : beOdds) : null;
    const beColor  = beOdds ? '#f1c40f' : '#7f8c8d';  // 採算オッズは黄色固定
    const beCell   = !isFuku
      ? (beOdds ? `<span style="font-weight:700;color:${{beColor}}">${{beOdds.toFixed(1)}}倍</span>` : '-')
      : `<span style="color:#555">-</span>`;
    // 現在オッズ: 単勝タブは手入力 input、複勝タブは範囲表示
    const oddsCell = isFuku
      ? (h['複勝下限'] ? h['複勝下限'].toFixed(1) + '〜' + (h['複勝上限'] || '?').toFixed(1) + '倍' : '-')
      : `<input type="number" min="0" max="999" step="0.1"
           value="${{curOdds != null ? curOdds.toFixed(1) : (h._prob > 0 ? (1/h._prob).toFixed(1) : '0.0')}}"
           placeholder="${{h._prob > 0 ? (1/h._prob).toFixed(1) : '0.0'}}"
           style="width:68px;background:#1a2634;color:#ecf0f1;border:1px solid #2c3e50;
                  border-radius:4px;padding:2px 5px;font-size:12px;text-align:right"
           oninput="const v=parseFloat(this.value); _userOdds[${{h['馬番']}}]=(v>0?v:null);
                    computeEV(Number(document.getElementById('tempSlider').value))">`;
    // SmartRC推定人気表示: 数字のみ
    const srcRank  = h['SmartRC推定人気順'] != null ? h['SmartRC推定人気順'] : null;
    const srcNinkiCell = srcRank != null
      ? `<span style="font-weight:700;color:#f39c12">${{srcRank}}位</span>`
      : '<span style="color:#555">-</span>';
    return `<tr>
      <td>${{waku_b}}</td>
      <td style="white-space:nowrap"><b style="font-size:13px">${{h['馬名']}}</b>${{h._isDark ? '<span style="font-size:9px;background:#8e44ad;color:#fff;padding:1px 4px;border-radius:3px;margin-left:4px;vertical-align:middle;">大穴</span>' : ''}}${{h['is_memo'] ? '<span style="font-size:9px;background:#8e44ad;color:#fff;padding:1px 5px;border-radius:3px;margin-left:4px;vertical-align:middle;">📌</span>' : ''}}${{h['is_ana']  ? '<span style="font-size:9px;background:#c0392b;color:#fff;padding:1px 5px;border-radius:3px;margin-left:4px;vertical-align:middle;">🎯</span>' : ''}}</td>
      <td>${{h['脚質']}}</td>
      <td>${{h['スコア'].toFixed(1)}}</td>
      <td>${{h['順位予想']}}</td>
      <td style="text-align:center;white-space:nowrap">${{srcNinkiCell}}</td>
      <td style="text-align:center;white-space:nowrap">${{
        (() => {{
          const k = h['乖離度'];
          if (k == null) return '<span style="color:#555">-</span>';
          const col = k >= 4 ? '#27ae60' : k >= 2 ? '#f39c12' : k >= 0 ? '#95a5a6' : '#e74c3c';
          const pf  = k > 0 ? '+' : '';
          const lbl = k >= 4 ? '大穴↑' : k >= 2 ? '中穴↑' : k >= 0 ? '一致' : '妙味薄↓';
          return `<span style="font-weight:700;color:${{col}}">${{pf}}${{k}}</span>`
               + `<span style="font-size:9px;color:${{col}};margin-left:2px">${{lbl}}</span>`;
        }})()
      }}</td>
      <td>
        <div>${{probPct}}</div>
        <div class="ev-bar" style="background:${{barColor}};width:${{barWidth}}%"></div>
      </td>
      <td style="text-align:center;display:${{isFuku ? 'none' : ''}}">${{beCell}}</td>
      <td>${{oddsCell}}</td>
      <td class="${{evCls}}">${{evStr}}</td>
      <td class="${{evCls}}">${{judgement}}</td>
    </tr>`;
  }}).join('');
}}

function computeEV(temp) {{
  const scores = EV_DATA.map(h => h['スコア']);
  const maxS   = Math.max(...scores);
  const exps   = scores.map(s => Math.exp((s - maxS) / temp));
  const sumExp = exps.reduce((a, b) => a + b, 0);
  const rawProbs = exps.map(e => e / sumExp);

  // ── 大穴補正: 市場オッズ基準でsoftmax確率を圧縮して再正規化 ──
  // 単勝オッズoの馬の市場確率は約1/o。モデルがその MAX_RATIO 倍を超えないよう制限。
  const MAX_RATIO = 3.0;  // 市場の最大3倍まで許容
  const DARK_THRESHOLD = 50;  // 50倍超を「大穴」扱い
  const dampedProbs = rawProbs.map((p, i) => {{
    const o = EV_DATA[i]['オッズ'];
    if (!o || o <= 0) return p;
    const marketProb = 1.0 / o;
    return Math.min(p, marketProb * MAX_RATIO);
  }});
  const sumDamped = dampedProbs.reduce((a, b) => a + b, 0);
  const winProbs  = dampedProbs.map(p => p / sumDamped);  // 再正規化

  const isFuku = (currentTab === 'fukusho');
  const rows = EV_DATA.map((h, i) => {{
    const prob   = isFuku ? placeProb(winProbs, i, 3) : winProbs[i];
    const _rawOdds = isFuku ? h['複勝下限'] : h['オッズ'];
    // 単勝タブで未入力の場合は採算オッズ(1/prob)で初期化してEVをフラット(≈0)から出発
    if (!isFuku && _userOdds[h['馬番']] == null && prob > 0) {{
      _userOdds[h['馬番']] = Math.round((1 / prob) * 10) / 10;
    }}
    const odds     = (!isFuku && _userOdds[h['馬番']] != null) ? _userOdds[h['馬番']] : _rawOdds;
    const ev       = (odds !== null && odds !== undefined) ? prob * odds - 1.0 : undefined;
    const isDark = !!(h['オッズ'] && h['オッズ'] > DARK_THRESHOLD);
    return {{ ...h, _prob: prob, _ev: ev, _isDark: isDark }};
  }});
  renderRows(rows);
}}

const slider = document.getElementById('tempSlider')
const tempLabel = document.getElementById('tempVal');
slider.addEventListener('input', () => {{
  tempLabel.textContent = slider.value;
  computeEV(Number(slider.value));
}});
computeEV(20);

// ── 積み上げチャート ─────────────────────────────
const STACK_DATA = {score_chart_json};
const stackCtx = document.getElementById('scoreStackChart');
if (stackCtx) {{
  new Chart(stackCtx.getContext('2d'), {{
    type: 'bar',
    data: STACK_DATA,
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      plugins: {{
        legend: {{
          position: 'right',
          labels: {{ color: '#bdc3c7', font: {{ size: 10 }}, boxWidth: 12 }}
        }},
        tooltip: {{ mode: 'index', intersect: false }}
      }},
      scales: {{
        x: {{
          stacked: true,
          ticks: {{ color: '#bdc3c7', font: {{ size: 10 }}, maxRotation: 50 }},
          grid: {{ color: '#2c3e50' }}
        }},
        y: {{
          stacked: true,
          ticks: {{ color: '#bdc3c7' }},
          grid: {{ color: '#2c3e50' }},
          title: {{ display: true, text: '補正pts', color: '#7f8c8d' }}
        }}
      }}
    }}
  }});
}}

// ── 補正項目別ランキング ──────────────────────────────────────────
(function() {{
  const ITEM_RANKINGS = {item_rankings_json};
  const grid = document.getElementById('itemRankingGrid');
  if (!grid) return;
  const RANK_ICONS = ['🥇','🥈','🥉'];
  ITEM_RANKINGS.forEach(item => {{
    const card = document.createElement('div');
    card.style.cssText =
      'background:#1a2634;border-radius:8px;padding:10px 12px;' +
      'border-left:4px solid ' + item.color + ';overflow:hidden';
    let inner = '<div style="font-weight:700;font-size:13px;color:' + item.color +
                ';margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid #2c3e50">' +
                item.label + '</div>';
    item.ranked.forEach((r, i) => {{
      const val    = r.val;
      const valStr = val > 0 ? '+' + val.toFixed(1) : val.toFixed(1);
      const valCol = val > 1 ? '#2ecc71' : val < -0.5 ? '#e74c3c' : '#7f8c8d';
      const rank   = i < 3 ? RANK_ICONS[i] : (i + 1) + '位';
      inner += '<div style="display:flex;justify-content:space-between;align-items:center;padding:2px 0;font-size:12px">' +
               '<span>' + rank + ' ' + r.name + '</span>' +
               '<span style="font-weight:700;color:' + valCol + '">' + valStr + '</span>' +
               '</div>';
    }});
    card.innerHTML = inner;
    grid.appendChild(card);
  }});
}})();
</script>
</body>
</html>
'''

# ── 買い目提案パネル（期待値シミュレーター直後）v5: フォーメーション＋合成採算オッズ ──
_BET_PANEL = """  <!-- 買い目提案パネル -->
  <div class="section">
    <h2>🎯 買い目提案 — フォーメーション</h2>
    <div id="betAnchorInfo" style="margin-bottom:4px;color:#ccc;font-size:13px"></div>
    <div id="betPartnerInfo" style="margin-bottom:8px;color:#9fb3c8;font-size:12px"></div>
    <div style="display:flex;gap:8px;margin-bottom:10px;align-items:center;flex-wrap:wrap">
      <button class="ev-tab active" id="betTabForm" onclick="setBetMode('form')">フォーメーション</button>
      <button class="ev-tab" id="betTabDetail" onclick="setBetMode('detail')">内訳</button>
      <span id="betModeNote" style="color:#7f8c8d;font-size:11px"></span>
    </div>
    <div class="ev-table-wrap">
      <table class="ev-table">
        <thead><tr id="betHead">
          <th>券種</th><th>買い目</th><th>点数</th><th>的中率</th><th>合成採算オッズ</th>
          <th>実オッズ(入力)</th><th>期待値</th><th>判定</th>
        </tr></thead>
        <tbody id="betBody"></tbody>
      </table>
    </div>
    <div class="prob-note">
      ※ 上の「モデル信頼度」スライダーと連動。勝率・複勝率は期待値シミュレーターと同一基準。<br>
      軸＝妙味馬優先（無ければ本命）。<b>相手はスコア偏差値・勝率・連対率・想定人気から自動選定</b>（堅いレースは絞り、混戦は広げる）。<br>
      <b>合成採算オッズ＝1÷フォーメーション全体の的中率</b>（各買い目の採算オッズに反比例配分した均等払い戻しの合成オッズ）。<br>
      投票画面に表示される<b>フォーメーションの合成オッズ</b>を「実オッズ」に入力 → 期待値=合成オッズ×的中率−1。実オッズ≥合成採算オッズなら<b>期待値プラス（◎）</b>。「内訳」で各組の個別採算も確認可。
    </div>
  </div>
"""

_BET_JS = r'''
// ===== 買い目提案 v5（フォーメーション＋合成採算オッズ）=====
var _betOdds = {};
var _betMode = 'form';
function setBetMode(m){ _betMode=m;
  var a=document.getElementById('betTabForm'), b=document.getElementById('betTabDetail');
  if(a) a.classList.toggle('active', m==='form'); if(b) b.classList.toggle('active', m==='detail');
  renderBets();
}
function _betWinProbs(temp){
  var scores = EV_DATA.map(function(h){return h['スコア'];});
  var maxS = Math.max.apply(null, scores);
  var exps = scores.map(function(s){return Math.exp((s-maxS)/temp);});
  var sum = exps.reduce(function(a,b){return a+b;},0);
  var probs = exps.map(function(e){return e/sum;});
  var MR=3.0;
  probs = probs.map(function(p,i){ var o=EV_DATA[i]['オッズ']; if(!o||o<=0) return p; return Math.min(p,(1/o)*MR); });
  var s2 = probs.reduce(function(a,b){return a+b;},0);
  return probs.map(function(p){return p/s2;});
}
function _permK(arr,k){ var r=[]; function go(cur,rest){ if(cur.length===k){r.push(cur.slice());return;} for(var i=0;i<rest.length;i++){ go(cur.concat([rest[i]]), rest.slice(0,i).concat(rest.slice(i+1))); } } go([],arr); return r; }
function _combK(arr,k){ var r=[]; function go(s,cur){ if(cur.length===k){r.push(cur.slice());return;} for(var i=s;i<arr.length;i++){ cur.push(arr[i]); go(i+1,cur); cur.pop(); } } go(0,[]); return r; }
function _betOddsInput(el){ var k=el.getAttribute('data-betkey'); var v=parseFloat(el.value); _betOdds[k]=(v>0?v:null); renderBets(); }
var _UMA_WAKU={};
EV_DATA.forEach(function(h){ if(h['馬番']!=null) _UMA_WAKU[h['馬番']]=h['枠番']||0; });
function _umaChip(u){
  var w=_UMA_WAKU[u]||0;
  var bg=(typeof WAKU_BG!=='undefined'&&WAKU_BG[w])?WAKU_BG[w]:'#888';
  var fg=(typeof WAKU_FG!=='undefined'&&WAKU_FG[w])?WAKU_FG[w]:'#fff';
  return '<span style="display:inline-flex;align-items:center;justify-content:center;width:21px;height:21px;border-radius:50%;background:'+bg+';color:'+fg+';font-weight:700;font-size:11px;box-shadow:0 0 0 1px rgba(255,255,255,0.25)">'+u+'</span>';
}
function _seqHtml(umaArr, sep){
  var s=(sep==='→')?'<span style="margin:0 3px;color:#889">→</span>':(sep==='−'||sep==='-')?'<span style="margin:0 3px;color:#889">-</span>':'';
  return '<span style="display:inline-flex;align-items:center;white-space:nowrap">'+umaArr.map(_umaChip).join(s)+'</span>';
}
function _formHtml(a, parts, sep){
  if(!parts||parts.length===0) return _umaChip(a);
  return '<span style="display:inline-flex;align-items:center;white-space:nowrap">'+_umaChip(a)+'<span style="margin:0 5px;color:#9ab;font-weight:700">'+sep+'</span>'+parts.map(_umaChip).join(' ')+'</span>';
}
function _evCell(P, key){
  var be = P>0 ? (1/P) : 0;
  var od=_betOdds[key];
  var evStr='-', cls='', judge='';
  if(od!=null && od>0 && P>0){ var e=od*P-1; evStr=e.toFixed(2); if(e>0.05){cls='ev-positive';judge='◎ 妙味';} else if(e>=-0.1){cls='ev-neutral';judge='△';} else {cls='ev-negative';judge='✕';} }
  var inp='<input type="number" inputmode="decimal" min="0" step="0.1" data-betkey="'+key+'" value="'+(od!=null?od:'')+'" style="width:66px;background:#1a2634;color:#ecf0f1;border:1px solid #2c3e50;border-radius:4px;padding:2px 5px;font-size:12px;text-align:right" onchange="_betOddsInput(this)">';
  return {be:(be>0?be.toFixed(1)+'倍':'-'), inp:inp, ev:evStr, cls:cls, judge:judge};
}
function renderBets(){
  var sl=document.getElementById('tempSlider'); if(!sl) return;
  var body=document.getElementById('betBody'); if(!body) return;
  var T=Number(sl.value);
  var wp=_betWinProbs(T);
  var allSc=EV_DATA.map(function(h){return h['スコア'];});
  var mean=allSc.reduce(function(a,b){return a+b;},0)/(allSc.length||1);
  var sd=Math.sqrt(allSc.reduce(function(a,b){return a+(b-mean)*(b-mean);},0)/(allSc.length||1))||1;
  var arr=EV_DATA.map(function(h,i){return {name:h['馬名'],uma:h['馬番'],idx:i,p:wp[i],rank:h['順位予想'],src:h['SmartRC推定人気順'],dev:50+10*(h['スコア']-mean)/sd};}).filter(function(x){return x.p>0&&x.uma!=null;});
  arr.sort(function(a,b){return b.p-a.p;}); arr=arr.slice(0,8);
  if(arr.length<2){ body.innerHTML='<tr><td colspan="8" style="color:#888">データ不足</td></tr>'; return; }
  var names=arr.map(function(x){return x.name;});
  var pv={}, um={}, dv={}, sc={}, gi={};
  arr.forEach(function(x){ pv[x.name]=x.p; um[x.name]=x.uma; dv[x.name]=x.dev; sc[x.name]=x.src; gi[x.name]=x.idx; });
  var o3={}; _permK(names,3).forEach(function(seq){ var rem=1,pr=1; for(var i=0;i<seq.length;i++){ if(rem<=1e-9){pr=0;break;} pr*=pv[seq[i]]/rem; rem-=pv[seq[i]]; } o3[seq.join('|')]=pr; });
  function place2(n){ var p=pv[n], t=p; names.forEach(function(j){ if(j!==n) t+=pv[j]*p/(1-pv[j]); }); return t; }
  var aobj=arr.find(function(x){ return x.rank<=3 && x.src!=null && Number(x.src)>=5; }); var isVal=!!aobj; if(!aobj) aobj=arr[0];
  var A=aobj.name;
  var place3A = (typeof placeProb!=='undefined') ? placeProb(wp, gi[A], 3) : 0;
  var cand=names.filter(function(n){return n!==A;});
  cand.sort(function(a,b){return pv[b]-pv[a];});
  var partners=[]; var cum=pv[A];
  for(var ci=0; ci<cand.length; ci++){
    var n=cand[ci]; var src=(sc[n]!=null)?Number(sc[n]):99;
    var live=(dv[n]>=48)||(src<=4)||(place2(n)>=0.30);
    var noHope=(dv[n]<42)&&(src>6)&&(place2(n)<0.18);
    if(noHope) continue;
    if(partners.length>=2 && cum>=0.82 && !(src<=2)) break;
    if(live || partners.length<2){ partners.push(n); cum+=pv[n]; }
    if(partners.length>=6) break;
  }
  if(partners.length<1){ partners=cand.slice(0,2); }
  var pUm=partners.map(function(n){return um[n];});
  var info=document.getElementById('betAnchorInfo');
  if(info) info.innerHTML='軸: '+_umaChip(um[A])+' <b style="color:#f1c40f">'+A+'</b>（偏差値'+dv[A].toFixed(0)+' / 勝率'+(pv[A]*100).toFixed(0)+'%） '+(isVal?'<span style="color:#3498db">妙味馬</span>':'<span style="color:#aaa">本命</span>');
  var pinfo=document.getElementById('betPartnerInfo');
  if(pinfo) pinfo.innerHTML='相手 '+partners.length+'頭（偏差値/勝率/連対率/想定人気で自動選定）: '+pUm.map(_umaChip).join(' ');
  var head=document.getElementById('betHead');
  // ── フォーメーション表示 ──
  if(_betMode==='form'){
    if(head) head.innerHTML='<th>券種</th><th>買い目</th><th>点数</th><th>的中率</th><th>合成採算オッズ</th><th>実オッズ(入力)</th><th>期待値</th><th>判定</th>';
    var P_uren=0, P_utan=0, P_wide=0;
    partners.forEach(function(o){ P_uren += pv[A]*pv[o]/(1-pv[A]) + pv[o]*pv[A]/(1-pv[o]); P_utan += pv[A]*pv[o]/(1-pv[A]); var wd=0; for(var k in o3){var ss=k.split('|'); if(ss.indexOf(A)>=0&&ss.indexOf(o)>=0) wd+=o3[k];} P_wide+=wd; });
    var trios=_combK(partners,2); var P_3p=0; trios.forEach(function(c){ _permK([A,c[0],c[1]],3).forEach(function(seq){P_3p+=o3[seq.join('|')]||0;}); });
    var ord=_permK(partners,2); var P_3t=0; ord.forEach(function(c){ P_3t += o3[[A,c[0],c[1]].join('|')]||0; });
    var forms=[
      {bt:'単勝', a:um[A], parts:[], sep:'', M:1, P:pv[A]},
      {bt:'複勝', a:um[A], parts:[], sep:'', M:1, P:place3A},
      {bt:'馬連', a:um[A], parts:pUm, sep:'−', M:partners.length, P:P_uren},
      {bt:'馬単(軸1着流し)', a:um[A], parts:pUm, sep:'→', M:partners.length, P:P_utan},
      {bt:'ワイド', a:um[A], parts:pUm, sep:'−', M:partners.length, P:P_wide},
      {bt:'三連複(軸1頭流し)', a:um[A], parts:pUm, sep:'−', M:trios.length, P:P_3p},
      {bt:'三連単(軸1着流し)', a:um[A], parts:pUm, sep:'→', M:ord.length, P:P_3t}
    ];
    body.innerHTML=forms.map(function(f){
      if(f.M<1) return '<tr><td style="font-weight:700">'+f.bt+'</td><td colspan="7" style="color:#667">相手不足</td></tr>';
      var key=f.bt+'|'+f.a+f.sep+f.parts.join(',');
      var c=_evCell(f.P,key);
      return '<tr><td style="font-weight:700">'+f.bt+'</td><td>'+_formHtml(f.a,f.parts,f.sep)+'</td><td style="text-align:center">'+f.M+'点</td><td>'+(f.P*100).toFixed(1)+'%</td><td style="color:#f1c40f;font-weight:700">'+c.be+'</td><td>'+c.inp+'</td><td class="'+c.cls+'">'+c.ev+'</td><td>'+c.judge+'</td></tr>';
    }).join('');
    var mn=document.getElementById('betModeNote'); if(mn) mn.textContent='券種ごとに軸流しフォーメーション1点（合成採算オッズ表示）';
    return;
  }
  // ── 内訳（個別組）表示 ──
  if(head) head.innerHTML='<th>券種</th><th>買い目</th><th>点数</th><th>的中率</th><th>採算オッズ</th><th>実オッズ(入力)</th><th>期待値</th><th>判定</th>';
  var rows=[];
  rows.push(['単勝',[um[A]],'',pv[A]]); rows.push(['複勝',[um[A]],'',place3A]);
  var pp=partners.map(function(o){ var at=pv[A]*pv[o]/(1-pv[A]); var ta=pv[o]*pv[A]/(1-pv[o]); var wd=0; for(var k in o3){var ss=k.split('|'); if(ss.indexOf(A)>=0&&ss.indexOf(o)>=0) wd+=o3[k];} return {o:o,umaren:at+ta,umatan:at,wide:wd}; });
  pp.slice().sort(function(a,b){return b.umaren-a.umaren;}).forEach(function(x){ rows.push(['馬連',[um[A],um[x.o]].sort(function(p,q){return p-q;}),'−',x.umaren]); });
  pp.slice().sort(function(a,b){return b.umatan-a.umatan;}).forEach(function(x){ rows.push(['馬単',[um[A],um[x.o]],'→',x.umatan]); });
  pp.slice().sort(function(a,b){return b.wide-a.wide;}).forEach(function(x){ rows.push(['ワイド',[um[A],um[x.o]].sort(function(p,q){return p-q;}),'−',x.wide]); });
  var tri2=_combK(partners,2).map(function(c){ var t=0; _permK([A,c[0],c[1]],3).forEach(function(seq){t+=o3[seq.join('|')]||0;}); return {c:[um[A],um[c[0]],um[c[1]]].sort(function(p,q){return p-q;}),p:t}; });
  tri2.sort(function(x,y){return y.p-x.p;}); tri2.forEach(function(x){ rows.push(['三連複',x.c,'−',x.p]); });
  var t12=_permK(partners,2).map(function(c){ return {c:[um[A],um[c[0]],um[c[1]]],p:o3[[A,c[0],c[1]].join('|')]||0}; });
  t12.sort(function(x,y){return y.p-x.p;}); t12.forEach(function(x){ rows.push(['三連単',x.c,'→',x.p]); });
  body.innerHTML=rows.map(function(r){
    var key=r[0]+'|'+r[1].join(r[2]); var c=_evCell(r[3],key);
    return '<tr><td style="font-weight:700">'+r[0]+'</td><td>'+_seqHtml(r[1],r[2])+'</td><td style="text-align:center">1点</td><td>'+(r[3]*100).toFixed(1)+'%</td><td style="color:#f1c40f;font-weight:700">'+c.be+'</td><td>'+c.inp+'</td><td class="'+c.cls+'">'+c.ev+'</td><td>'+c.judge+'</td></tr>';
  }).join('');
  var mn2=document.getElementById('betModeNote'); if(mn2) mn2.textContent='自動選定した相手での全買い目（個別採算オッズ）';
}
(function(){ var sl=document.getElementById('tempSlider'); if(sl) sl.addEventListener('input', renderBets); renderBets(); })();
'''

html = html.replace('  <div class="section">\n    <h2>📊 全出走馬一覧</h2>', _BET_PANEL + '  <div class="section">\n    <h2>📊 全出走馬一覧</h2>', 1)
html = html.replace('computeEV(20);', 'computeEV(20);\n' + _BET_JS, 1)

import argparse as _ap, os as _os2
if __name__ == '__main__':
    _parser = _ap.ArgumentParser()
    _parser.add_argument('--json',   required=True)
    _parser.add_argument('--outdir', default=None)
    _parser.add_argument('--baba-json', default=None, dest='baba_json')
    _args = _parser.parse_args()
    _outdir2 = _args.outdir or _os2.path.dirname(_os2.path.abspath(_args.json))
    _stem = _os2.path.splitext(_os2.path.basename(_args.json))[0]
    _race_id = _stem.replace('horses_data_', '')
    _out_html = _os2.path.join(_outdir2, f'pred_{_race_id}.html')
    with open(_out_html, 'w', encoding='utf-8') as _fh:
        _fh.write(html)
    print(f'  -> {_out_html}')
