# -*- coding: utf-8 -*-
"""
result_loader.py — レース結果ファイルを CSV/Excel/HTML のいずれからでも統一的に読み込む。

TARGET の HTML 結果は「回顧用データ（着順・タイム・通過・PCI・上3F・決め手・前走 等）」と
「全券種の払戻（配当）」の両方を含む。本モジュールは

    load_result(path) -> (res_df, meta_series, payouts)

を返す。res_df / meta_series は従来 CSV(統合形式) と同じ列名スキーマに正規化されるため、
build_review.py など既存フローはそのまま利用できる。payouts は HTML のみ取得（CSV では {}）。

  - res_df 列: 入線順位, 馬番, 枠番, 馬名, 人気, 単勝オッズ, 決め手, タイム, 着差,
               上り3F, 通過1..通過4, 体重, 増減, 種牡馬, 母の父馬名, PCI 他
  - meta 列  : レース名, 場所, 距離, 芝・ダート, 天候, 馬場状態, 頭数, 通過3F, 上り3F,
               レースPCI, 前後3F差, 最速上3F, 通過ラップ表記, 上りラップ表記, R, クラス名, 年,月,日
  - payouts  : {'tansho':[(組番,円),...], 'fukusho':..., 'umaren':..., 'wide':..., 'umatan':...,
               'sanrenpuku':..., 'sanrentan':..., 'wakuren':...}
"""
import os
import re
import unicodedata
import pandas as pd

try:
    from payout_parser import parse_payout as _parse_payout
except Exception:
    _parse_payout = None

_VENUES = ['札幌', '函館', '福島', '新潟', '東京', '中山', '中京', '京都', '阪神', '小倉']


def _nfkc(s):
    return unicodedata.normalize('NFKC', str(s)) if s is not None else ''


def _num(s, cast=float, default=None):
    try:
        return cast(_nfkc(s).strip())
    except (ValueError, TypeError):
        return default


# ──────────────────────────────────────────────────────────────
# HTML パーサ
# ──────────────────────────────────────────────────────────────
def _read_html_tables(html_str):
    """HTMLの<table>群をDataFrameのリストで返す。lxml/bs4 等が無くても動くよう
    pandas(lxml/bs4/html5lib)を優先し、失敗時は標準ライブラリのみでパースする。"""
    import io as _io
    try:
        return pd.read_html(_io.StringIO(html_str))
    except Exception:
        pass
    from html.parser import HTMLParser

    class _T(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tables = []; self.cur = None; self.row = None; self.cell = None; self.buf = None

        def handle_starttag(self, t, a):
            if t == 'table':
                self.cur = []
            elif t == 'tr' and self.cur is not None:
                self.row = []
            elif t in ('td', 'th') and self.row is not None:
                self.cell = []; self.buf = self.cell

        def handle_endtag(self, t):
            if t == 'table' and self.cur is not None:
                self.tables.append(self.cur); self.cur = None
            elif t == 'tr' and self.row is not None:
                self.cur.append(self.row); self.row = None
            elif t in ('td', 'th') and self.cell is not None:
                self.row.append(''.join(self.cell).strip()); self.cell = None; self.buf = None

        def handle_data(self, d):
            if self.buf is not None:
                self.buf.append(d)

    p = _T(); p.feed(html_str)
    dfs = []
    for tb in p.tables:
        if not tb:
            continue
        w = max(len(r) for r in tb)
        rows = [r + [''] * (w - len(r)) for r in tb]
        hdr = rows[0]; body = rows[1:] if len(rows) > 1 else []
        seen = {}; cols = []
        for i, c in enumerate(hdr):
            c = c or f'col{i}'
            if c in seen:
                seen[c] += 1; c = f'{c}.{seen[c]}'
            else:
                seen[c] = 0
            cols.append(c)
        dfs.append(pd.DataFrame(body, columns=cols))
    return dfs


def _load_html(path, encoding='cp932'):
    raw = open(path, 'rb').read()
    try:
        html = raw.decode(encoding)
    except UnicodeDecodeError:
        html = raw.decode('utf-8', errors='replace')

    # --- 1) 結果テーブル ---
    tabs = _read_html_tables(html)
    tbl = max(tabs, key=lambda t: t.shape[0] * t.shape[1])
    tbl.columns = [str(c) for c in tbl.columns]

    # HTML列名 -> CSVスキーマ列名
    cmap = {
        '着': '入線順位', '馬': '馬番', '枠': '枠番', '馬名S': '馬名', '騎手': '騎手',
        'タイム': 'タイム', '着差': '着差', '1着差': '1着差タイム', '平均1F': '平均1Fタイム',
        '時速km/h': '時速(km/h)', 'PCI': 'PCI', '通過順位': '通過順位', '決手': '決め手',
        'Ave-3F': 'Ave-3F', '上3F': '上り3F', '人': '人気', '単勝': '単勝オッズ',
        '複勝オッズ': '複勝オッズ範囲', '単勝票数': '単勝票数', '複勝票数': '複勝票数',
        '単複比': '単複票数比', '体重': '体重', '±': '増減', '父': '種牡馬', '母': '母馬名',
        '母父': '母の父馬名', '間隔': '間隔', '前場': '前走場所', '前レース名': '前走レース名',
        '前距離': '前走距離', '前着': '前走確定着順', '前人': '前走人気', '前決': '前走決め手',
        '前ｸﾗｽ': '前走クラス', '前走騎手': '前走騎手', '前走年月日': '前走日付',
    }
    res = pd.DataFrame()
    for src, dst in cmap.items():
        if src in tbl.columns:
            res[dst] = tbl[src]
    # 性齢 -> 性別/年齢
    if '性齢' in tbl.columns:
        sa = tbl['性齢'].astype(str).map(_nfkc)
        res['性別'] = sa.str.extract(r'([牡牝騙セ])')[0]
        res['年齢'] = pd.to_numeric(sa.str.extract(r'(\d+)')[0], errors='coerce')
    # 斤量（見習いマーク☆★▲△◇等を除去）
    if '斤量' in tbl.columns:
        res['斤量'] = pd.to_numeric(tbl['斤量'].astype(str).map(lambda x: re.sub(r'[^0-9.]', '', _nfkc(x))), errors='coerce')

    # 数値化・整形
    res['入線順位'] = pd.to_numeric(res['入線順位'].map(_nfkc), errors='coerce')
    res = res[res['入線順位'].notna()].copy()
    res['入線順位'] = res['入線順位'].astype(int)
    for c in ['馬番', '枠番', '人気', '体重', '増減', '前走確定着順', '前走人気', '前走距離']:
        if c in res.columns:
            res[c] = pd.to_numeric(res[c].map(lambda x: re.sub(r'[^0-9.+-]', '', _nfkc(x))), errors='coerce')
    for c in ['単勝オッズ', '上り3F', 'PCI', '単複票数比', '単勝票数', '複勝票数']:
        if c in res.columns:
            res[c] = pd.to_numeric(res[c].map(lambda x: re.sub(r'[^0-9.]', '', _nfkc(x))), errors='coerce')
    for c in ['馬名', '騎手', '決め手', 'タイム', '着差', '種牡馬', '母の父馬名']:
        if c in res.columns:
            res[c] = res[c].astype(str).map(lambda x: _nfkc(x).strip())
    # 複勝オッズ範囲 '2.0- 3.0' -> 複勝下限/複勝上限
    if '複勝オッズ範囲' in res.columns:
        rng = res['複勝オッズ範囲'].astype(str).map(_nfkc).str.extract(r'([\d.]+)\D+([\d.]+)')
        res['複勝下限'] = pd.to_numeric(rng[0], errors='coerce')
        res['複勝上限'] = pd.to_numeric(rng[1], errors='coerce')
    # 通過順位 '06-05' -> 通過1..通過4
    if '通過順位' in res.columns:
        pp = res['通過順位'].astype(str).map(_nfkc).str.replace(' ', '')
        sp = pp.str.split('-', expand=True)
        for i in range(4):
            res['通過%d' % (i + 1)] = pd.to_numeric(sp[i], errors='coerce') if (sp.shape[1] > i) else None

    # --- 2) ヘッダ/ラップ等のテキスト行 ---
    txt = re.sub(r'<[^>]+>', ' ', html)
    txt = re.sub(r'[ \t]+', ' ', txt)
    lines = [_nfkc(l).strip() for l in txt.splitlines() if l.strip()]
    head = '\n'.join(lines[:6])

    meta = {}
    m = re.search(r'(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日', head)
    if m:
        meta['年'], meta['月'], meta['日'] = int(m.group(1)), int(m.group(2)), int(m.group(3))
    meta['場所'] = next((v for v in _VENUES if v in head), '')
    mr = re.search(r'【\s*(\d{1,2})\s*R', head) or re.search(r'/\s*(\d{1,2})R', head)
    meta['R'] = int(mr.group(1)) if mr else None
    meta['天候'] = (re.search(r'天候\s*[:：]\s*([^\s　]+)', head) or [None, ''])[1] if '天候' in head else ''
    mw = re.search(r'天候\s*[:：]\s*(\S+)', head); meta['天候'] = mw.group(1) if mw else ''
    mb = re.search(r'馬場状態\s*[:：]\s*(\S+)', head); meta['馬場状態'] = mb.group(1) if mb else ''
    md = re.search(r'(芝|ダート|障)\s*(\d{3,4})\s*m', head)
    meta['芝・ダート'] = md.group(1) if md else ''
    meta['距離'] = int(md.group(2)) if md else None
    mh = re.search(r'(\d{1,2})\s*頭', head); meta['頭数'] = int(mh.group(1)) if mh else int(res.shape[0])
    # クラス名（条件表記行）
    cls_line = next((l for l in lines[:6] if ('クラス' in l or '万下' in l or 'オープン' in l or 'Ｇ' in l or 'Ｌ' in l or 'リステッド' in l)), '')
    mc = re.search(r'([123]勝クラス|新馬|未勝利|オープン|Ｇ\s*[ⅠⅡⅢ123]|G[123]|\(L\)|リステッド|OP)', cls_line)
    meta['クラス名'] = re.sub(r'\s+', '', mc.group(1)) if mc else cls_line.split('(')[0].strip()[:12]
    # レース名（特別・重賞名があれば抽出。条件戦は空でOK→build_review側で 場所R+クラス にフォールバック）
    rn = next((l for l in lines[:6] if re.search(r'(Ｓ|ステークス|賞|杯|記念|カップ|オープン特別|ハンデキャップ)', l) and '頭立' not in l and 'クラス' not in l), '')
    mn = re.search(r'([一-龥ァ-ヶA-Za-zＡ-Ｚ０-９0-9・ー]+(?:Ｓ|ステークス|賞|杯|記念|カップ))', rn)
    meta['レース名'] = mn.group(1) if mn else ''

    # ラップ/ペース行
    lap_l = next((l for l in lines if l.startswith('LAP')), '')
    pas_l = next((l for l in lines if l.startswith('通過') and '上り' in l), '')
    meta['通過ラップ表記'] = lap_l.replace('LAP', '').strip()
    m3 = re.search(r'通過\s*([\d.]+)-([\d.]+)-([\d.]+)', pas_l)
    meta['通過3F'] = _num(m3.group(1)) if m3 else (float(res['Ave-3F'].dropna().iloc[0]) if 'Ave-3F' in res and res['Ave-3F'].notna().any() else None)
    ag = re.search(r'上り\s*([\d.]+)-([\d.]+)-([\d.]+)', pas_l)
    meta['上り3F'] = _num(ag.group(3)) if ag else None
    meta['上りラップ表記'] = (ag.group(0).replace('上り', '').strip() if ag else '')
    # 派生
    if meta.get('通過3F') is not None and meta.get('上り3F') is not None:
        meta['前後3F差'] = round(meta['通過3F'] - meta['上り3F'], 1)
    else:
        meta['前後3F差'] = 0.0
    meta['最速上3F'] = float(res['上り3F'].dropna().min()) if ('上り3F' in res and res['上り3F'].notna().any()) else (meta.get('上り3F') or 0.0)
    if meta.get('上り3F') is None:
        meta['上り3F'] = meta['最速上3F']
    if meta.get('通過3F') is None:
        meta['通過3F'] = meta['上り3F']
    # レースPCI: 前半3F/後半(上り)3F の比から算出（<50=前傾ハイ / >50=後傾スロー）
    try:
        _f3, _l3 = meta.get('通過3F'), meta.get('上り3F')
        if _f3 and _l3 and _l3 > 0:
            meta['レースPCI'] = round(50.0 * float(_f3) / float(_l3), 1)
        else:
            meta['レースPCI'] = float(res.sort_values('入線順位').iloc[0]['PCI'])
    except Exception:
        meta['レースPCI'] = 50.0

    # --- 3) 払戻 ---
    payouts = {}
    if _parse_payout is not None:
        try:
            payouts = _parse_payout(path, encoding=encoding)
        except Exception:
            payouts = {}

    return res.reset_index(drop=True), pd.Series(meta), payouts


# ──────────────────────────────────────────────────────────────
# CSV / Excel（従来形式）
# ──────────────────────────────────────────────────────────────
def _read_df(path, **kwargs):
    """拡張子が .csv/.tsv なら pd.read_csv(encoding=cp932)、それ以外は pd.read_excel。
    ラギッドCSV（行ごとカラム数不揃い）もPythonのcsvモジュールで処理。
    """
    import csv as _csv_mod
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.csv', '.tsv'):
        sep = '	' if ext == '.tsv' else ','
        enc = kwargs.pop('encoding', 'cp932')
        kwargs.pop('sheet_name', None)
        try:
            return pd.read_csv(path, sep=sep, encoding=enc, **kwargs)
        except UnicodeDecodeError:
            try:
                return pd.read_csv(path, sep=sep, encoding='utf-8-sig', **kwargs)
            except pd.errors.ParserError:
                pass
        except pd.errors.ParserError:
            pass
        # フォールバック: ラギッドCSV対応
        header_arg = kwargs.get('header', 0)
        rows = []
        for enc2 in [enc, 'utf-8-sig', 'utf-8']:
            try:
                with open(path, encoding=enc2, newline='', errors='replace') as _f:
                    rows = list(_csv_mod.reader(_f, delimiter=sep))
                break
            except Exception:
                continue
        if not rows:
            return pd.DataFrame()
        max_cols = max(len(r) for r in rows)
        padded = [r + [''] * (max_cols - len(r)) for r in rows]
        if header_arg is None:
            df = pd.DataFrame(padded)
        elif isinstance(header_arg, int) and header_arg < len(padded):
            cols = padded[header_arg]
            df = pd.DataFrame(padded[header_arg + 1:], columns=cols)
        else:
            df = pd.DataFrame(padded)
        df = df.replace('', float('nan'))
        for col in df.columns:
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass
        return df
    else:
        return pd.read_excel(path, **kwargs)


def load_result(path, racedata=None):
    """統一ローダ。返り値: (res_df, meta_series, payouts_dict)"""
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.html', '.htm'):
        return _load_html(path)
    # CSV/Excel
    if racedata:
        res = _read_df(path)
        meta = _read_df(racedata).iloc[0]
    else:
        _raw = _read_df(path, header=None)
        meta = pd.Series(_raw.iloc[1].values, index=_raw.iloc[0].values)
        res = _read_df(path, header=2)
    return res, meta, {}


if __name__ == '__main__':
    import sys
    res, meta, po = load_result(sys.argv[1])
    print('res shape:', res.shape, '| cols:', [c for c in res.columns][:20])
    _mk = ['レース名','場所','R','クラス名','芝・ダート','距離','頭数','天候','馬場状態','通過3F','上り3F','レースPCI','前後3F差','最速上3F','年','月','日']
    print('meta:', {k: meta[k] for k in _mk if k in meta})
    print('payouts:', {k: v for k, v in po.items()})
    _cols = [c for c in ['入線順位','馬番','馬名','人気','単勝オッズ','決め手','タイム','上り3F','通過1','通過2','体重'] if c in res.columns]
    print(res[_cols].head(4).to_string(index=False))
