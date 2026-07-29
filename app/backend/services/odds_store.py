# -*- coding: utf-8 -*-
"""手入力オッズの保存。

保存先は app/data/odds_manual.json（新規ファイル）。
既存ファイルには一切触れない。

将来の妙味検証で使えるように、値だけでなく
「いつ入れたか」「どのEVロジック版で見ていたか」も一緒に残す。
レース確定後に、そのとき見えていたオッズと突き合わせられる。

書き込みは一時ファイル→置換の原子的方式。上書き前の内容は
_archive/app_backups/ に日時付きで退避する（物理削除はしない方針）。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from .. import config

DATA_DIR = config.APP_DIR / 'data'
ODDS_FILE = DATA_DIR / 'odds_manual.json'
SCHEMA_VERSION = 1
JST = timezone(timedelta(hours=9))

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(JST).isoformat(timespec='seconds')


def _empty() -> dict:
    return {'version': SCHEMA_VERSION, 'races': {}}


def _load() -> dict:
    if not ODDS_FILE.exists():
        return _empty()
    try:
        data = json.loads(ODDS_FILE.read_text(encoding='utf-8'))
    except Exception:
        # 壊れたファイルを黙って空扱いにしない。退避してから作り直す。
        _backup(reason='broken')
        return _empty()
    if not isinstance(data, dict) or 'races' not in data:
        _backup(reason='unexpected')
        return _empty()
    return data


def _backup(reason: str = 'update') -> None:
    if not ODDS_FILE.exists():
        return
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(JST).strftime('%Y%m%d_%H%M%S')
    dest = config.BACKUP_DIR / f'odds_manual_{stamp}_{reason}.json'
    if not dest.exists():
        dest.write_bytes(ODDS_FILE.read_bytes())


def _save(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _backup()
    tmp = ODDS_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(ODDS_FILE)


def _clean_numbers(src: Any) -> dict:
    """{キー: 数値} だけを残す。0以下・数値でないものは捨てる。"""
    out: dict = {}
    if not isinstance(src, dict):
        return out
    for k, v in src.items():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0:
            out[str(k)] = f
    return out


def get(race_id: str) -> dict:
    """1レース分の保存済みオッズ。無ければ空。"""
    entry = _load()['races'].get(race_id) or {}
    return {
        'race_id': race_id,
        'updated_at': entry.get('updated_at'),
        'ev_core_version': entry.get('ev_core_version'),
        'tansho': entry.get('tansho') or {},
        'bets': entry.get('bets') or {},
    }


def put(race_id: str, tansho: Any, bets: Any, ev_core_version: str | None) -> dict:
    """1レース分を保存して、保存後の内容を返す。"""
    with _lock:
        data = _load()
        data['races'][race_id] = {
            'updated_at': _now(),
            'ev_core_version': ev_core_version,
            'tansho': _clean_numbers(tansho),
            'bets': _clean_numbers(bets),
        }
        _save(data)
    return get(race_id)


def clear(race_id: str) -> dict:
    """1レース分の入力を消す（ファイル自体は消さない）。"""
    with _lock:
        data = _load()
        if race_id in data['races']:
            data['races'].pop(race_id)
            _save(data)
    return get(race_id)


def all_races() -> dict:
    """保存済みの全レース（将来の妙味検証の入口）。"""
    return _load()['races']
