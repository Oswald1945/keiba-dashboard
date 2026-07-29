# -*- coding: utf-8 -*-
"""注目レースの印。**利用者ごと**に持つ。

保存先は app/data/featured_races.json（新規ファイル）。既存ファイルには触れない。
書き込みは一時ファイル→置換の原子的方式で、上書き前に退避する。

公開サーバーでは招待した数名が同じ画面を使うため、印を全員で共有すると
他人の注目レースが自分の一覧に出てしまう。ログイン中の利用者ごとに分けて持つ。
このPCにはログインの概念が無いので、'local' という決め打ちの利用者名を使う。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

from .. import config

DATA_DIR = config.APP_DIR / 'data'
FILE = DATA_DIR / 'featured_races.json'
JST = timezone(timedelta(hours=9))
SCHEMA_VERSION = 2

# ログインの概念が無い環境（このPC）で使う利用者名
LOCAL_USER = 'local'

_lock = threading.Lock()


def _empty() -> dict:
    return {'version': SCHEMA_VERSION, 'users': {}}


def _migrate(data: dict) -> dict:
    """旧形式（全員で1つ）を利用者別に移す。

    旧: {'version': 1, 'races': {race_id: {...}}}
    新: {'version': 2, 'users': {'local': {race_id: {...}}}}

    旧形式には利用者の情報が無いので、このPCで付けた印として 'local' に入れる。
    """
    races = data.get('races') or {}
    return {'version': SCHEMA_VERSION,
            'users': {LOCAL_USER: races} if races else {}}


def _load() -> dict:
    if not FILE.exists():
        return _empty()
    try:
        data = json.loads(FILE.read_text(encoding='utf-8'))
    except Exception:
        _backup('broken')
        return _empty()
    if not isinstance(data, dict):
        _backup('unexpected')
        return _empty()
    if 'users' not in data:
        if 'races' in data:
            _backup('v1')
            return _migrate(data)
        _backup('unexpected')
        return _empty()
    return data


def _backup(reason: str) -> None:
    if not FILE.exists():
        return
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(JST).strftime('%Y%m%d_%H%M%S')
    dest = config.BACKUP_DIR / f'featured_races_{stamp}_{reason}.json'
    if not dest.exists():
        dest.write_bytes(FILE.read_bytes())


def _save(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _backup('update')
    tmp = FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(FILE)
    # 一覧に★が出るので、作り直させる
    from . import catalog
    catalog.invalidate_list_cache()


def _races_of(data: dict, user: str) -> dict:
    return data.get('users', {}).get(user or LOCAL_USER) or {}


def list_ids(user: str = LOCAL_USER) -> list:
    """その利用者が注目に印を付けたレースID。"""
    return sorted(_races_of(_load(), user))


def is_featured(race_id: str, user: str = LOCAL_USER) -> bool:
    return race_id in _races_of(_load(), user)


def set_featured(race_id: str, on: bool, user: str = LOCAL_USER) -> dict:
    """印を付ける / 外す。付けた日時も残す（後から並べ替えたいときのため）。

    他の利用者の印には触れない。
    """
    from . import paths
    if paths.parse_race_id(race_id) is None:
        raise ValueError(f'race_id の形式が不正です: {race_id}')
    user = user or LOCAL_USER
    with _lock:
        data = _load()
        races = data.setdefault('users', {}).setdefault(user, {})
        if on:
            races[race_id] = {'marked_at': datetime.now(JST).isoformat(timespec='seconds')}
        else:
            races.pop(race_id, None)
        _save(data)
    return {'race_id': race_id, 'featured': on, 'total': len(races)}
