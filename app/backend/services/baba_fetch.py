# -*- coding: utf-8 -*-
"""JRA馬場情報の自動取得。

これまで自動取得が失敗していた理由:
  https://www.jra.go.jp/keiba/baba/ のページHTMLには、クッション値や含水率の
  **数値が入っていない**（JavaScriptが後から差し込む）。素直にページを取っても
  ラベルだけが取れて値は空になる。

そこで、ページ自身が読みに行っているデータ配信URLを直接取る:
  _data_cushion.html … 会場名・測定時刻・クッション値（直近3回）
  _data_moist.html   … 会場名・測定時刻・芝/ダート含水率・馬場状態の帯・当日雨量
  _data_week.html    … 会場名・週間天候（10日分。末尾が当日）
  index.html/2/3     … 使用コース・開催（第N回○○競馬第M日）

いずれもログイン不要。3会場ぶんが1ファイルにまとめて入っており、
`title="新潟"` のように**会場名が付いている**ので、週ごとに開催場が変わっても
並び順に依存せず特定できる。

重要な注意:
  含水率に付いてくる馬場状態（hard/wet/soft/heavy）は、JRAが含水率から
  機械的に当てはめた**目安**であって、レースごとの発表馬場ではない。
  予想作成時（前日夜・当日朝）は発表前なのでこれが最良の推定値だが、
  そのまま採点に流し込まず、必ず画面で確認してもらう。
  発表馬場はレース当日に race.db (RT_RA_RACE) から取れる（racedb.announced_going）。
"""
from __future__ import annotations

import re
from datetime import date as _date

BASE = 'https://www.jra.go.jp/keiba/baba/'
DATA_CUSHION = BASE + '_data_cushion.html'
DATA_MOIST = BASE + '_data_moist.html'
DATA_WEEK = BASE + '_data_week.html'
INDEX_PAGES = [BASE + 'index.html', BASE + 'index2.html', BASE + 'index3.html']

TIMEOUT = 15
UA = 'keiba-dashboard/0.1 (local personal use)'

# 含水率に付く馬場状態の帯（JRAのHTMLのクラス/属性値）
CONDITION_TO_BABA = {'hard': '良', 'wet': '稍重', 'soft': '重', 'heavy': '不良'}

# title属性は「新潟」、race.db や baba_manual.json は「新潟」で揃っているのでそのまま使う
_BLOCK_RE = re.compile(r'<div\s+id="rc([A-Z])"\s+title="([^"]+)"\s*>(.*?)</div><!--', re.S)
_UNIT_RE = re.compile(r'<div class="unit">(.*?)(?=<div class="unit">|\Z)', re.S)
_TIME_RE = re.compile(r'<div class="time">([^<]+)</div>')
_CUSHION_RE = re.compile(r'<div class="cushion">([\d.]+)</div>')
_SPAN_RE = re.compile(r'<span class="(mg|m4c)"[^>]*data-condition="(\w+)"[^>]*>([\d.]+)</span>')
_RAIN_RE = re.compile(r'当日雨量は([\d.]+)ミリメートル')
_LI_RE = re.compile(r'<li>([^<]*)</li>')


class BabaFetchError(RuntimeError):
    pass


def _get(url: str) -> str:
    import requests
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={'User-Agent': UA})
    except Exception as e:
        raise BabaFetchError(f'{url} に接続できません: {e}') from e
    if r.status_code != 200:
        raise BabaFetchError(f'{url} が {r.status_code} を返しました')
    return decode(r.content)


def decode(raw: bytes) -> str:
    """JRAのページは Shift_JIS(cp932)。念のため utf-8 も試す。"""
    for enc in ('cp932', 'utf-8', 'euc_jp'):
        try:
            t = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if '馬場' in t or 'cushion' in t or 'moist' in t or 'week_data' in t:
            return t
    return raw.decode('cp932', errors='replace')


def _blocks(html: str) -> dict:
    """会場名 -> ブロックHTML。"""
    out = {}
    for _slot, venue, inner in _BLOCK_RE.findall(html):
        out[venue.strip()] = inner
    return out


# ── 各データの解析（テストしやすいよう文字列を受け取る） ──────────
def parse_cushion(html: str) -> dict:
    """会場名 -> {'value': 9.6, 'time': '7月26日（日曜）7時00分', 'history': [...]}"""
    out = {}
    for venue, inner in _blocks(html).items():
        units = []
        for u in _UNIT_RE.findall(inner):
            t = _TIME_RE.search(u)
            v = _CUSHION_RE.search(u)
            if v:
                units.append({'time': (t.group(1).strip() if t else None),
                              'value': float(v.group(1))})
        if units:
            out[venue] = {'value': units[0]['value'], 'time': units[0]['time'],
                          'history': units}
    return out


def parse_moist(html: str) -> dict:
    """会場名 -> 芝/ダートの含水率と馬場状態の目安。"""
    out = {}
    for venue, inner in _blocks(html).items():
        units = _UNIT_RE.findall(inner)
        if not units:
            continue
        latest = units[0]
        t = _TIME_RE.search(latest)
        rain = _RAIN_RE.search(latest)

        def surface(tag: str) -> dict:
            m = re.search(rf'<div class="{tag}">(.*?)</div>', latest, re.S)
            if not m:
                return {}
            vals = {}
            for pos, cond, num in _SPAN_RE.findall(m.group(1)):
                vals[pos] = {'value': float(num), 'condition': cond,
                             'baba': CONDITION_TO_BABA.get(cond)}
            return vals

        turf = surface('turf')
        dirt = surface('dirt')
        out[venue] = {
            'time': (t.group(1).strip() if t else None),
            'rain_mm': (float(rain.group(1)) if rain else None),
            '芝': turf,
            'ダート': dirt,
            'unit_count': len(units),
        }
    return out


def parse_week_weather(html: str) -> dict:
    """会場名 -> {'today': '曇時々雨', 'series': [...10日分...]}"""
    out = {}
    for venue, inner in _blocks(html).items():
        items = [x.strip() for x in _LI_RE.findall(inner) if x.strip()]
        if items:
            out[venue] = {'today': items[-1], 'series': items}
    return out


def parse_index(html: str) -> dict:
    """1ページから 会場名・開催・日付・使用コース を取り出す。"""
    title = re.search(r'<title>([^<]*)</title>', html)
    venue = None
    if title:
        m = re.search(r'（(.+?)競馬場）', title.group(1))
        if m:
            venue = m.group(1).strip()
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)
    kaisai = re.search(r'第\d+回\S+?競馬第\d+日', text)
    ymd = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    # 「使用コース」の直後はタグで分断されて "A コース（…）" のように空白が入る。
    # 見出しの「使用コース・芝の様子」と区別するため、A〜D が続くことを必須にする。
    course = re.search(r'使用コース\s*([ABCD])\s*コース\s*([（(][^）)]*[）)])?', text)
    course_used = None
    if course:
        course_used = f'{course.group(1)}コース' + (course.group(2) or '')
    return {
        'venue': venue,
        'kaisai': (kaisai.group(0) if kaisai else None),
        'date': (f'{ymd.group(1)}{int(ymd.group(2)):02d}{int(ymd.group(3)):02d}'
                 if ymd else None),
        'course_used': course_used,
    }


# ── まとめ ────────────────────────────────────────────────────────
def _estimate(surface: dict) -> tuple:
    """ゴール前(mg)の帯を代表値にする。4コーナー(m4c)と違う場合は注記を返す。"""
    mg = surface.get('mg') or {}
    m4c = surface.get('m4c') or {}
    baba = mg.get('baba') or m4c.get('baba')
    note = None
    if mg.get('baba') and m4c.get('baba') and mg['baba'] != m4c['baba']:
        note = f"ゴール前={mg['baba']} / 4コーナー={m4c['baba']}（差あり）"
    return baba, note


def fetch_all(fetcher=None) -> dict:
    """JRAから3会場ぶんまとめて取得して整える。

    fetcher を差し替えられるようにしてあるのは、テストで保存済みHTMLを使うため
    （テストはネットワークに触らない）。
    """
    get = fetcher or _get
    cushion = parse_cushion(get(DATA_CUSHION))
    moist = parse_moist(get(DATA_MOIST))
    week = parse_week_weather(get(DATA_WEEK))

    indexes = {}
    for url in INDEX_PAGES:
        try:
            info = parse_index(get(url))
        except BabaFetchError:
            continue          # 開催が2場の週は index3 が無い
        if info.get('venue'):
            indexes[info['venue']] = info

    venues = []
    for venue in sorted(set(cushion) | set(moist) | set(week) | set(indexes)):
        mo = moist.get(venue) or {}
        idx = indexes.get(venue) or {}
        est_turf, note_turf = _estimate(mo.get('芝') or {})
        est_dirt, note_dirt = _estimate(mo.get('ダート') or {})
        venues.append({
            'venue': venue,
            'date': idx.get('date'),
            'kaisai': idx.get('kaisai'),
            'course_used': idx.get('course_used'),
            'cushion': (cushion.get(venue) or {}).get('value'),
            'cushion_time': (cushion.get(venue) or {}).get('time'),
            'moisture_time': mo.get('time'),
            'rain_mm': mo.get('rain_mm'),
            'moisture_turf': (mo.get('芝') or {}),
            'moisture_dirt': (mo.get('ダート') or {}),
            'weather': (week.get(venue) or {}).get('today'),
            # ここから下は「JRAの含水率からの目安」。発表馬場ではない。
            'estimated_turf': est_turf,
            'estimated_dirt': est_dirt,
            'estimate_note_turf': note_turf,
            'estimate_note_dirt': note_dirt,
        })
    return {
        'fetched_at': _date.today().isoformat(),
        'source': BASE,
        'is_estimate': True,
        'notice': ('含水率から機械的に当てはめた目安です。レースごとの発表馬場では'
                   'ありません。内容を確認してから保存してください。'),
        'venues': venues,
    }
