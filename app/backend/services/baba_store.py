# -*- coding: utf-8 -*-
"""baba_manual.json の読み書き。

形式は既存のまま:
  { "_注意": "...", "YYYYMMDD": { "新潟": {"芝":"良","ダート":"稍重","天候":"曇",
                                          "クッション値":9.6,"含水率_芝":13.9,"含水率_ダート":7.6} } }

守ること:
  - `_注意` や他の日付のデータを消さない（1日分だけ差し替える）。
  - **自動取得した値を勝手に保存しない。** 画面で確認・修正してもらったものだけ保存する。
    馬場は採点に強く効くため（CLAUDE.md / RULES_AND_NOTES.md）。
  - 上書き前に _archive/app_backups/ へ退避。書き込みは一時ファイル→置換。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

from .. import config
from . import baba_fetch, racedb

JST = timezone(timedelta(hours=9))
_lock = threading.Lock()

VALID_BABA = ('良', '稍重', '重', '不良')

# 含水率はJRAが「ゴール前」と「4コーナー」の2地点を出している。両方残す。
# 採点（トラックバイアス）が読むのは 含水率_芝 / 含水率_ダート の方（＝ゴール前を入れる）。
# _4コーナー は記録用で、run_new.py は読まない（未知のキーは無視される）。
FIELDS = ('芝', 'ダート', '天候', 'クッション値',
          '含水率_芝', '含水率_ダート',
          '含水率_芝_4コーナー', '含水率_ダート_4コーナー',
          '降水mm')

# 採点に効くフィールド（画面で見分けられるように公開する）
SCORING_FIELDS = ('芝', 'ダート', 'クッション値', '含水率_芝', '含水率_ダート')


def _load() -> dict:
    if not config.BABA_MANUAL_JSON.exists():
        return {}
    try:
        data = json.loads(config.BABA_MANUAL_JSON.read_text(encoding='utf-8'))
    except Exception as e:
        raise RuntimeError(f'baba_manual.json を読めません（壊れている可能性）: {e}') from e
    if not isinstance(data, dict):
        raise RuntimeError('baba_manual.json の形式が想定外です')
    return data


def _backup() -> None:
    if not config.BABA_MANUAL_JSON.exists():
        return
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(JST).strftime('%Y%m%d_%H%M%S')
    dest = config.BACKUP_DIR / f'baba_manual_{stamp}.json'
    if not dest.exists():
        dest.write_bytes(config.BABA_MANUAL_JSON.read_bytes())


def get(date: str) -> dict:
    """その日付の保存済み内容（会場 -> 値）。"""
    entry = _load().get(date)
    return entry if isinstance(entry, dict) else {}


def dates() -> list:
    return sorted([k for k in _load() if k.isdigit()], reverse=True)


def preview(date: str, fetcher=None) -> dict:
    """JRAから取得した値と、保存済みの値を並べて返す（**保存はしない**）。

    画面はこれを表示して、くろあめさんが確認・修正してから保存する。
    """
    saved = get(date)
    try:
        fetched = baba_fetch.fetch_all(fetcher=fetcher)
        error = None
    except Exception as e:
        fetched = {'venues': []}
        error = str(e)

    by_venue = {v['venue']: v for v in fetched.get('venues', [])}
    rows = []
    for venue in sorted(set(by_venue) | set(saved)):
        f = by_venue.get(venue) or {}
        s = saved.get(venue) or {}
        # 発表馬場（レース当日以降なら race.db から取れる。予想時点では空）
        try:
            announced = racedb.announced_going(date, racedb.JYO_BY_NAME.get(venue, ''))
        except Exception:
            announced = {'芝': None, 'ダート': None, '天候': None, 'source': None}

        turf = f.get('moisture_turf') or {}
        dirt = f.get('moisture_dirt') or {}
        rows.append({
            'venue': venue,
            'kaisai': f.get('kaisai'),
            'fetched_date': f.get('date'),
            'course_used': f.get('course_used'),
            'measured_at': {'cushion': f.get('cushion_time'), 'moisture': f.get('moisture_time')},
            'rain_mm': f.get('rain_mm'),
            # 自動取得（目安）。含水率はゴール前と4コーナーの両方。
            'suggested': {
                '芝': f.get('estimated_turf'),
                'ダート': f.get('estimated_dirt'),
                '天候': f.get('weather'),
                'クッション値': f.get('cushion'),
                '含水率_芝': (turf.get('mg') or {}).get('value'),
                '含水率_ダート': (dirt.get('mg') or {}).get('value'),
                '含水率_芝_4コーナー': (turf.get('m4c') or {}).get('value'),
                '含水率_ダート_4コーナー': (dirt.get('m4c') or {}).get('value'),
            },
            # 参考: ゴール前と4コーナーの両方（どちらを採るかは画面で選べる）
            'moisture_detail': {
                '芝': {'ゴール前': (turf.get('mg') or {}).get('value'),
                       '4コーナー': (turf.get('m4c') or {}).get('value')},
                'ダート': {'ゴール前': (dirt.get('mg') or {}).get('value'),
                           '4コーナー': (dirt.get('m4c') or {}).get('value')},
            },
            'estimate_note': {'芝': f.get('estimate_note_turf'),
                              'ダート': f.get('estimate_note_dirt')},
            # 発表馬場（あればこちらが正）
            'announced': announced,
            # いま保存されている値
            'saved': {k: s.get(k) for k in FIELDS if k in s},
        })
    return {
        'date': date,
        'error': error,
        'source': baba_fetch.BASE,
        'is_estimate': True,
        'notice': ('自動取得した馬場は「含水率からの目安」です。発表馬場ではありません。'
                   '内容を確認・修正してから保存してください。'),
        'scoring_fields': list(SCORING_FIELDS),
        'field_note': ('含水率はゴール前と4コーナーの両方を保存します。'
                       '採点（トラックバイアス）に使われるのはゴール前の値です。'),
        'venues': rows,
    }


def _clean(values: dict) -> dict:
    out = {}
    for k in FIELDS:
        if k not in values:
            continue
        v = values[k]
        if v is None or v == '':
            continue
        if k in ('芝', 'ダート'):
            if v not in VALID_BABA:
                raise ValueError(f'{k} は 良/稍重/重/不良 のいずれかです（受け取った値: {v}）')
            out[k] = v
        elif k == '天候':
            out[k] = str(v)
        else:
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                raise ValueError(f'{k} は数値で入力してください（受け取った値: {v}）')
    return out


def save(date: str, venues: dict) -> dict:
    """1日分を保存する。他の日付・`_注意` はそのまま残す。"""
    if not (date or '').isdigit() or len(date) != 8:
        raise ValueError(f'日付は YYYYMMDD で指定してください: {date}')
    if not isinstance(venues, dict) or not venues:
        raise ValueError('保存する会場がありません')

    cleaned = {}
    for venue, values in venues.items():
        c = _clean(values or {})
        if not c.get('芝') and not c.get('ダート'):
            raise ValueError(f'{venue}: 芝またはダートの馬場状態を入れてください')
        cleaned[venue] = c

    with _lock:
        data = _load()
        data[date] = cleaned
        _backup()
        tmp = config.BABA_MANUAL_JSON.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(config.BABA_MANUAL_JSON)
    return {'date': date, 'saved': cleaned}
