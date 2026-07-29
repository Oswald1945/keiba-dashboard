# -*- coding: utf-8 -*-
"""メモ馬（memo_horses.json）の読み書き。

既存資産との約束:
  - 項目構成は一切変えない（馬名 / 登録日 / 追加者 / 元レース / メモ）。
    build_dashboard_v3.py と run_new.py の自動登録がそのまま動くこと。
  - 一意キーは run_new.py の重複判定と同じ「馬名|元レース日付|R」。
  - 書式も同じ（ensure_ascii=False, indent=2）。差分を無駄に増やさない。

いちばん気をつけること:
  run_new.py は回顧を作るたびに memo_horses.json を **丸ごと書き換える**。
  アプリが画面に出した内容をそのまま全件保存すると、その間に自動登録された
  メモが消える。そこで
    1. 保存は必ず「読み直して1件だけ差し替え」で行う
    2. 画面を開いたときのファイルと中身が変わっていたら保存を拒否する（409）
  の2段構えにしてある。黙って上書きしない。

削除はしない。アーカイブは app/data/memo_archived.json へ移すだけ
（memo_horses.json から外れるので、既存ダッシュボードからも自然に消える）。
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .. import config

DATA_DIR = config.APP_DIR / 'data'
ARCHIVE_FILE = DATA_DIR / 'memo_archived.json'
JST = timezone(timedelta(hours=9))

# 削除したメモ馬を完全に消すまでの日数（それまでは「削除予定」として戻せる）
PURGE_AFTER_DAYS = 7

_lock = threading.Lock()

# 自動登録の変換もれで、会場名が「sp」「fs」のようなローマ字のまま入っているものがある。
# 表示時に会場名へ直す（元のJSONは書き換えない）。
_ROMAJI_TO_VENUE = {
    'sp': '札幌', 'sm': '札幌',
    'hk': '函館', 'hd': '函館',
    'fk': '福島', 'fs': '福島',
    'ng': '新潟', 'ni': '新潟',
    'tk': '東京', 'to': '東京', 't': '東京',
    'nk': '中山', 'cb': '中山', 'na': '中山', 'ns': '中山',
    'ck': '中京', 'cc': '中京',
    'ky': '京都', 'kt': '京都',
    'hn': '阪神', 'hs': '阪神',
    'kk': '小倉', 'ko': '小倉', 'ok': '小倉',
}


def normalize_venue(place) -> str:
    """「sp」→「札幌」。すでに会場名ならそのまま返す。"""
    v = str(place or '').strip()
    if not v:
        return v
    return _ROMAJI_TO_VENUE.get(v.lower(), v)


def _with_venue(entry: dict) -> dict:
    """表示用に会場名を直したコピーを返す。"""
    src = dict(entry.get('元レース') or {})
    if src.get('場所'):
        src['場所'] = normalize_venue(src['場所'])
    return {**entry, '元レース': src}


class MemoConflict(Exception):
    """画面を開いた後に memo_horses.json が別の処理で変わっていた。"""


class MemoNotFound(Exception):
    pass


class MemoDuplicate(Exception):
    """同じキーの登録が既にある。"""


# ── 基本 ─────────────────────────────────────────────────────────
def entry_key(entry: dict) -> str:
    """run_new.py の重複判定と同じキー。"""
    src = entry.get('元レース') or {}
    return f"{entry.get('馬名', '')}|{src.get('日付', '')}|{src.get('R', '')}"


def _dumps(entries: list) -> str:
    return json.dumps(entries, ensure_ascii=False, indent=2)


def _read_file(path) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        raise RuntimeError(f'{path.name} を読めません（壊れている可能性）: {e}') from e
    if not isinstance(data, list):
        raise RuntimeError(f'{path.name} の形式が想定外です（配列ではありません）')
    return data


def file_hash() -> str:
    """memo_horses.json の中身のハッシュ。競合検出に使う。"""
    if not config.MEMO_JSON.exists():
        return ''
    return hashlib.sha256(config.MEMO_JSON.read_bytes()).hexdigest()


def _backup(reason: str) -> None:
    if not config.MEMO_JSON.exists():
        return
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(JST).strftime('%Y%m%d_%H%M%S')
    dest = config.BACKUP_DIR / f'memo_horses_{stamp}_{reason}.json'
    if not dest.exists():
        dest.write_bytes(config.MEMO_JSON.read_bytes())


def _write_memo(entries: list, reason: str) -> None:
    _backup(reason)
    tmp = config.MEMO_JSON.with_suffix('.tmp')
    tmp.write_text(_dumps(entries), encoding='utf-8')
    tmp.replace(config.MEMO_JSON)
    # 一覧にメモ馬の印が出るので、作り直させる
    from . import catalog
    catalog.invalidate_list_cache()


def _write_archive(entries: list) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ARCHIVE_FILE.with_suffix('.tmp')
    tmp.write_text(_dumps(entries), encoding='utf-8')
    tmp.replace(ARCHIVE_FILE)


def _check_hash(expected: str | None) -> None:
    if expected is None:
        return
    current = file_hash()
    if expected != current:
        raise MemoConflict(
            'メモ馬の一覧が別の処理（回顧生成など）で更新されています。'
            '画面を読み直してから、もう一度保存してください。'
        )


# ── 読み取り ─────────────────────────────────────────────────────
def _norm_date(s: str) -> str:
    return (s or '').replace('/', '')


def list_all() -> dict:
    """馬名ごとにまとめた一覧を返す。

    同じ馬が別レースで複数回登録されることがある（実データで41頭）ので、
    馬名でまとめ、元レースの新しい順に並べる。
    """
    entries = _read_file(config.MEMO_JSON)
    groups: dict = {}
    for e in entries:
        name = e.get('馬名', '')
        if not name:
            continue
        # キーは元の値で作る（保存データと一致させる）。表示だけ会場名に直す。
        groups.setdefault(name, []).append({**_with_venue(e), 'key': entry_key(e)})

    horses = []
    for name, items in groups.items():
        items.sort(key=lambda x: _norm_date((x.get('元レース') or {}).get('日付', '')), reverse=True)
        latest = items[0]
        horses.append({
            'name': name,
            'entries': items,
            'entry_count': len(items),
            'latest_race_date': (latest.get('元レース') or {}).get('日付', ''),
            'has_memo': any((i.get('メモ') or '').strip() for i in items),
            'registered_at': max((i.get('登録日') or '') for i in items),
        })
    horses.sort(key=lambda h: (_norm_date(h['latest_race_date']), h['name']), reverse=True)
    return {
        'file_hash': file_hash(),
        'total_entries': len(entries),
        'total_horses': len(horses),
        'horses': horses,
    }


def find_by_name(name: str) -> list:
    """同じ馬名の既存登録を返す（手動追加のときの重複確認用）。"""
    name = (name or '').strip()
    if not name:
        return []
    return [{**_with_venue(e), 'key': entry_key(e)}
            for e in _read_file(config.MEMO_JSON)
            if e.get('馬名', '') == name]


def list_deleted() -> dict:
    """削除予定の一覧。期限（7日）を過ぎたものはこの時に完全削除する。"""
    entries = _purge_expired()
    today = date.today()
    out = []
    for e in entries:
        d = e.get('削除日') or ''
        remain = None
        try:
            remain = PURGE_AFTER_DAYS - (today - date.fromisoformat(d)).days
        except ValueError:
            pass
        out.append({**_with_venue(e), 'key': entry_key(e), 'days_left': remain})
    return {'total': len(out), 'purge_after_days': PURGE_AFTER_DAYS, 'entries': out}


# 旧名（呼び出し互換のため残す）
list_archived = list_deleted


def _purge_expired() -> list:
    """削除から7日を過ぎたものを完全に消す。消す前に退避を残す。"""
    entries = _read_file(ARCHIVE_FILE)
    if not entries:
        return entries
    today = date.today()
    keep, gone = [], []
    for e in entries:
        d = e.get('削除日') or e.get('アーカイブ日') or ''
        try:
            expired = (today - date.fromisoformat(d)).days >= PURGE_AFTER_DAYS
        except ValueError:
            expired = False       # 日付が読めないものは消さない
        (gone if expired else keep).append(e)
    if gone:
        config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(JST).strftime('%Y%m%d_%H%M%S')
        dest = config.BACKUP_DIR / f'memo_purged_{stamp}.json'
        dest.write_text(json.dumps(gone, ensure_ascii=False, indent=2), encoding='utf-8')
        with _lock:
            _write_archive(keep)
    return keep


# ── 書き込み ─────────────────────────────────────────────────────
def _clean_source(src: Any) -> dict:
    """元レース。日付は必須（空だと全レースにメモバッジが付いてしまうため）。"""
    src = src or {}
    d = str(src.get('日付', '') or '').strip()
    if not d:
        raise ValueError('元レースの日付は必須です（空だと全レースにメモが表示されます）')
    r = src.get('R', '')
    try:
        r = int(r)
    except (TypeError, ValueError):
        r = str(r or '').strip()
    return {
        '日付': d,
        '場所': str(src.get('場所', '') or '').strip(),
        'R': r,
        'レース名': str(src.get('レース名', '') or '').strip(),
        'クラス': str(src.get('クラス', '') or '').strip(),
    }


def add(horse_name: str, source: dict, memo: str = '', author: str = '',
        expected_hash: str | None = None, overwrite: bool = False) -> dict:
    """1件追加する。

    overwrite=False で同じキーが既にあれば MemoDuplicate。
    画面側は既存内容を見せて「上書き」か「馬名を直して新規登録」を選ばせる。
    """
    horse_name = (horse_name or '').strip()
    if not horse_name:
        raise ValueError('馬名は必須です')
    src = _clean_source(source)

    with _lock:
        _check_hash(expected_hash)
        entries = _read_file(config.MEMO_JSON)     # 保存直前に読み直す
        new_entry = {
            '馬名': horse_name,
            '登録日': date.today().isoformat(),
            '追加者': str(author or '').strip(),
            '元レース': src,
            'メモ': str(memo or ''),
        }
        key = entry_key(new_entry)
        idx = next((i for i, e in enumerate(entries) if entry_key(e) == key), None)
        if idx is not None:
            if not overwrite:
                raise MemoDuplicate(key)
            # 上書きでも登録日は元のものを残す（いつ気づいた馬かの記録なので）
            new_entry['登録日'] = entries[idx].get('登録日') or new_entry['登録日']
            entries[idx] = new_entry
        else:
            entries.append(new_entry)
        _write_memo(entries, 'add')
    return {'key': key, 'file_hash': file_hash(), 'entry': new_entry}


def update(key: str, memo: str | None = None, author: str | None = None,
           source: dict | None = None, expected_hash: str | None = None) -> dict:
    """既存1件のメモ・追加者・元レースを更新する（全件上書きはしない）。"""
    with _lock:
        _check_hash(expected_hash)
        entries = _read_file(config.MEMO_JSON)
        idx = next((i for i, e in enumerate(entries) if entry_key(e) == key), None)
        if idx is None:
            raise MemoNotFound(key)
        entry = dict(entries[idx])
        if memo is not None:
            entry['メモ'] = str(memo)
        if author is not None:
            entry['追加者'] = str(author).strip()
        if source is not None:
            entry['元レース'] = _clean_source(source)
        # 項目の並びを既存と揃える
        entries[idx] = {
            '馬名': entry.get('馬名', ''),
            '登録日': entry.get('登録日', ''),
            '追加者': entry.get('追加者', ''),
            '元レース': entry.get('元レース', {}),
            'メモ': entry.get('メモ', ''),
        }
        new_key = entry_key(entries[idx])
        _write_memo(entries, 'update')
    return {'key': new_key, 'file_hash': file_hash(), 'entry': entries[idx]}


def delete(key: str, expected_hash: str | None = None) -> dict:
    """memo_horses.json から外して「削除予定」に移す。

    すぐには消さない。7日間は戻せる状態で app/data/memo_archived.json に置き、
    期限を過ぎたら完全に消す（消す前に _archive/app_backups/ へ退避する）。
    """
    with _lock:
        _check_hash(expected_hash)
        entries = _read_file(config.MEMO_JSON)
        idx = next((i for i, e in enumerate(entries) if entry_key(e) == key), None)
        if idx is None:
            raise MemoNotFound(key)
        moved = entries.pop(idx)
        archived = _read_file(ARCHIVE_FILE)
        if not any(entry_key(a) == key for a in archived):
            archived.append({**moved, '削除日': date.today().isoformat()})
        _write_archive(archived)
        _write_memo(entries, 'delete')
    return {'key': key, 'file_hash': file_hash(), 'entry': moved}


# 旧名（呼び出し互換のため残す）
archive = delete


def restore(key: str, expected_hash: str | None = None) -> dict:
    """削除予定から memo_horses.json へ戻す。"""
    with _lock:
        _check_hash(expected_hash)
        archived = _read_file(ARCHIVE_FILE)
        idx = next((i for i, a in enumerate(archived) if entry_key(a) == key), None)
        if idx is None:
            raise MemoNotFound(key)
        moved = dict(archived.pop(idx))
        moved.pop('アーカイブ日', None)
        moved.pop('削除日', None)
        entries = _read_file(config.MEMO_JSON)
        if not any(entry_key(e) == key for e in entries):
            entries.append({
                '馬名': moved.get('馬名', ''),
                '登録日': moved.get('登録日', ''),
                '追加者': moved.get('追加者', ''),
                '元レース': moved.get('元レース', {}),
                'メモ': moved.get('メモ', ''),
            })
        _write_archive(archived)
        _write_memo(entries, 'restore')
    return {'key': key, 'file_hash': file_hash()}
