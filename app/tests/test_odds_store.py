# -*- coding: utf-8 -*-
"""手入力オッズの保存まわり。実ファイルは汚さず一時フォルダで検証する。"""
from __future__ import annotations

import json

import pytest

from app.backend.services import odds_store


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """保存先とバックアップ先を一時フォルダに差し替える。"""
    monkeypatch.setattr(odds_store, 'DATA_DIR', tmp_path / 'data')
    monkeypatch.setattr(odds_store, 'ODDS_FILE', tmp_path / 'data' / 'odds_manual.json')
    monkeypatch.setattr(odds_store.config, 'BACKUP_DIR', tmp_path / 'backups')
    return tmp_path


def test_get_returns_empty_when_nothing_saved():
    got = odds_store.get('20260726_sp9')
    assert got == {'race_id': '20260726_sp9', 'updated_at': None,
                   'ev_core_version': None, 'tansho': {}, 'bets': {}}


def test_put_then_get_roundtrip():
    saved = odds_store.put('20260726_sp9', {'5': 12.2, '1': 3.4},
                           {'馬連|5-1,3': 18.4}, 'v1-2026-07-26')
    assert saved['tansho'] == {'5': 12.2, '1': 3.4}
    assert saved['bets'] == {'馬連|5-1,3': 18.4}
    assert saved['ev_core_version'] == 'v1-2026-07-26'
    assert saved['updated_at']
    assert odds_store.get('20260726_sp9') == saved


def test_non_positive_and_broken_values_are_dropped():
    """0以下・数値でないものは保存しない（勝手に0扱いにもしない）。"""
    saved = odds_store.put('20260726_sp9',
                           {'5': 12.2, '6': 0, '7': -1, '8': 'あ', '9': None},
                           {}, 'v1')
    assert saved['tansho'] == {'5': 12.2}


def test_races_are_independent():
    odds_store.put('20260726_sp9', {'5': 12.2}, {}, 'v1')
    odds_store.put('20260726_sp8', {'3': 4.5}, {}, 'v1')
    assert odds_store.get('20260726_sp9')['tansho'] == {'5': 12.2}
    assert odds_store.get('20260726_sp8')['tansho'] == {'3': 4.5}
    assert set(odds_store.all_races()) == {'20260726_sp9', '20260726_sp8'}


def test_clear_removes_only_that_race():
    odds_store.put('20260726_sp9', {'5': 12.2}, {}, 'v1')
    odds_store.put('20260726_sp8', {'3': 4.5}, {}, 'v1')
    odds_store.clear('20260726_sp9')
    assert odds_store.get('20260726_sp9')['tansho'] == {}
    assert odds_store.get('20260726_sp8')['tansho'] == {'3': 4.5}
    assert odds_store.ODDS_FILE.exists(), 'ファイル自体は消さないこと'


def test_overwrite_keeps_a_backup(isolated):
    odds_store.put('20260726_sp9', {'5': 12.2}, {}, 'v1')
    odds_store.put('20260726_sp9', {'5': 9.9}, {}, 'v1')
    backups = list((isolated / 'backups').glob('odds_manual_*.json'))
    assert backups, '上書き前の退避が作られていません'
    old = json.loads(backups[0].read_text(encoding='utf-8'))
    assert old['races']['20260726_sp9']['tansho'] == {'5': 12.2}


def test_broken_file_is_backed_up_not_silently_ignored(isolated):
    odds_store.DATA_DIR.mkdir(parents=True, exist_ok=True)
    odds_store.ODDS_FILE.write_text('{ こわれている', encoding='utf-8')
    assert odds_store.get('20260726_sp9')['tansho'] == {}
    broken = list((isolated / 'backups').glob('*_broken.json'))
    assert broken, '壊れたファイルが退避されていません'


def test_atomic_write_leaves_no_temp_file(isolated):
    odds_store.put('20260726_sp9', {'5': 12.2}, {}, 'v1')
    assert not list((isolated / 'data').glob('*.tmp'))
