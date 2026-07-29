# -*- coding: utf-8 -*-
"""メモ馬の読み書き。実ファイル(memo_horses.json)は汚さず一時フォルダで検証する。"""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from app.backend.services import memo_store


def _entry(name, d='2026/07/25', r=11, memo='', place='新潟', race='関屋記念', cls='Ｇ３'):
    return {'馬名': name, '登録日': '2026-07-25', '追加者': '',
            '元レース': {'日付': d, '場所': place, 'R': r, 'レース名': race, 'クラス': cls},
            'メモ': memo}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    memo = tmp_path / 'memo_horses.json'
    monkeypatch.setattr(memo_store.config, 'MEMO_JSON', memo)
    monkeypatch.setattr(memo_store.config, 'BACKUP_DIR', tmp_path / 'backups')
    monkeypatch.setattr(memo_store, 'DATA_DIR', tmp_path / 'data')
    monkeypatch.setattr(memo_store, 'ARCHIVE_FILE', tmp_path / 'data' / 'memo_archived.json')
    return tmp_path


def _write(path, entries):
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8')


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


# ── キーと一覧 ───────────────────────────────────────────────────
def test_entry_key_matches_run_new_dedup_rule():
    """既存 run_new.py の重複判定キーと同じであること。"""
    assert memo_store.entry_key(_entry('ラムジェット')) == 'ラムジェット|2026/07/25|11'


def test_list_groups_by_horse_name(isolated):
    _write(isolated / 'memo_horses.json', [
        _entry('トウカイエルデ', d='2026/05/23', r=8),
        _entry('トウカイエルデ', d='2026/07/25', r=11),
        _entry('ラムジェット', d='2026/06/07', r=9, memo='次走注目'),
    ])
    got = memo_store.list_all()
    assert got['total_entries'] == 3
    assert got['total_horses'] == 2

    horses = {h['name']: h for h in got['horses']}
    tk = horses['トウカイエルデ']
    assert tk['entry_count'] == 2
    # 元レースが新しい順
    assert [e['元レース']['日付'] for e in tk['entries']] == ['2026/07/25', '2026/05/23']
    assert tk['has_memo'] is False
    assert horses['ラムジェット']['has_memo'] is True
    # 一覧は元レースの新しい順
    assert [h['name'] for h in got['horses']] == ['トウカイエルデ', 'ラムジェット']


def test_find_by_name_returns_existing_entries(isolated):
    _write(isolated / 'memo_horses.json', [
        _entry('ラムジェット', d='2026/05/23', r=8),
        _entry('ラムジェット', d='2026/07/25', r=11),
        _entry('別の馬'),
    ])
    got = memo_store.find_by_name('ラムジェット')
    assert len(got) == 2
    assert all(e['馬名'] == 'ラムジェット' for e in got)
    assert memo_store.find_by_name('いない馬') == []


# ── 追加（重複時の分岐） ─────────────────────────────────────────
def test_add_creates_entry_with_existing_field_order(isolated):
    memo_store.add('ラムジェット', {'日付': '2026/07/25', '場所': '新潟', 'R': 11,
                                    'レース名': '関屋記念', 'クラス': 'Ｇ３'}, メモ := 'テスト')
    saved = _read(isolated / 'memo_horses.json')
    assert len(saved) == 1
    assert list(saved[0].keys()) == ['馬名', '登録日', '追加者', '元レース', 'メモ']
    assert saved[0]['メモ'] == メモ


def test_add_rejects_duplicate_unless_overwrite(isolated):
    src = {'日付': '2026/07/25', '場所': '新潟', 'R': 11, 'レース名': '関屋記念', 'クラス': 'Ｇ３'}
    memo_store.add('ラムジェット', src, 'さいしょ')
    with pytest.raises(memo_store.MemoDuplicate):
        memo_store.add('ラムジェット', src, 'あとから')
    # 拒否されたので中身は変わっていない
    assert _read(isolated / 'memo_horses.json')[0]['メモ'] == 'さいしょ'


def test_add_with_overwrite_replaces_and_keeps_registered_date(isolated):
    src = {'日付': '2026/07/25', '場所': '新潟', 'R': 11, 'レース名': '関屋記念', 'クラス': 'Ｇ３'}
    _write(isolated / 'memo_horses.json',
           [{'馬名': 'ラムジェット', '登録日': '2026-05-27', '追加者': '',
             '元レース': src, 'メモ': 'ふるいメモ'}])
    memo_store.add('ラムジェット', src, 'あたらしいメモ', overwrite=True)
    saved = _read(isolated / 'memo_horses.json')
    assert len(saved) == 1, '上書きなのに増えている'
    assert saved[0]['メモ'] == 'あたらしいメモ'
    assert saved[0]['登録日'] == '2026-05-27', '最初に気づいた日は残すこと'


def test_add_with_different_name_creates_new_entry(isolated):
    """重複時に「馬名を修正して新規登録」を選んだ場合。"""
    src = {'日付': '2026/07/25', '場所': '新潟', 'R': 11, 'レース名': '関屋記念', 'クラス': 'Ｇ３'}
    memo_store.add('ラムジェット', src)
    memo_store.add('ラムジェットII', src)
    assert len(_read(isolated / 'memo_horses.json')) == 2


def test_source_date_is_required(isolated):
    """日付が空だと全レースにメモバッジが付くので受け付けない。"""
    with pytest.raises(ValueError):
        memo_store.add('ラムジェット', {'日付': '', 'R': 11})
    with pytest.raises(ValueError):
        memo_store.add('', {'日付': '2026/07/25', 'R': 11})


# ── 更新 ─────────────────────────────────────────────────────────
def test_update_changes_only_target_entry(isolated):
    _write(isolated / 'memo_horses.json', [_entry('A', r=1), _entry('B', r=2)])
    memo_store.update('A|2026/07/25|1', memo='Aのメモ', author='くろあめ')
    saved = _read(isolated / 'memo_horses.json')
    assert saved[0]['メモ'] == 'Aのメモ' and saved[0]['追加者'] == 'くろあめ'
    assert saved[1]['メモ'] == '' and saved[1]['馬名'] == 'B'


def test_update_missing_key_raises(isolated):
    _write(isolated / 'memo_horses.json', [_entry('A', r=1)])
    with pytest.raises(memo_store.MemoNotFound):
        memo_store.update('いない|2026/07/25|1', memo='x')


# ── 競合検出（いちばん大事） ─────────────────────────────────────
def test_save_is_rejected_when_file_changed_meanwhile(isolated):
    """画面を開いた後に run_new.py が自動登録した状況を再現する。"""
    path = isolated / 'memo_horses.json'
    _write(path, [_entry('A', r=1)])
    opened = memo_store.file_hash()

    # 裏で回顧生成が走ってメモが1件増えた
    _write(path, [_entry('A', r=1), _entry('自動登録された馬', r=5)])

    with pytest.raises(memo_store.MemoConflict):
        memo_store.update('A|2026/07/25|1', memo='x', expected_hash=opened)
    # 自動登録された分が消えていないこと
    assert len(_read(path)) == 2


def test_save_succeeds_with_current_hash(isolated):
    _write(isolated / 'memo_horses.json', [_entry('A', r=1)])
    memo_store.update('A|2026/07/25|1', memo='ok', expected_hash=memo_store.file_hash())
    assert _read(isolated / 'memo_horses.json')[0]['メモ'] == 'ok'


def test_write_rereads_file_and_keeps_entries_added_meanwhile(isolated):
    """ハッシュを渡さない場合でも、全件上書きで他の追加を消さないこと。"""
    path = isolated / 'memo_horses.json'
    _write(path, [_entry('A', r=1)])
    _write(path, [_entry('A', r=1), _entry('あとから追加', r=9)])
    memo_store.update('A|2026/07/25|1', memo='x')
    saved = _read(path)
    assert len(saved) == 2
    assert {e['馬名'] for e in saved} == {'A', 'あとから追加'}


# ── 削除（すぐには消さず、7日後に完全削除） ─────────────────────
def test_delete_moves_entry_to_pending_list(isolated):
    _write(isolated / 'memo_horses.json', [_entry('A', r=1), _entry('B', r=2)])
    memo_store.delete('A|2026/07/25|1')
    assert [e['馬名'] for e in _read(isolated / 'memo_horses.json')] == ['B']
    pending = _read(isolated / 'data' / 'memo_archived.json')
    assert [e['馬名'] for e in pending] == ['A']
    assert pending[0]['削除日'], '削除日を記録すること（7日の起点になる）'


def test_restore_puts_entry_back(isolated):
    _write(isolated / 'memo_horses.json', [_entry('A', r=1)])
    memo_store.delete('A|2026/07/25|1')
    memo_store.restore('A|2026/07/25|1')
    saved = _read(isolated / 'memo_horses.json')
    assert [e['馬名'] for e in saved] == ['A']
    assert '削除日' not in saved[0], '戻したら削除日は残さない'
    assert list(saved[0].keys()) == ['馬名', '登録日', '追加者', '元レース', 'メモ']
    assert _read(isolated / 'data' / 'memo_archived.json') == []


def test_deleted_list_shows_days_left(isolated):
    _write(isolated / 'memo_horses.json', [_entry('A', r=1)])
    memo_store.delete('A|2026/07/25|1')
    got = memo_store.list_deleted()
    assert got['total'] == 1
    assert got['purge_after_days'] == 7
    assert got['entries'][0]['days_left'] == 7


def test_expired_entries_are_purged_with_a_backup(isolated):
    """削除から7日たったものは完全に消す。ただし消す前に控えを残す。"""
    old_day = (date.today() - timedelta(days=7)).isoformat()
    recent = (date.today() - timedelta(days=6)).isoformat()
    (isolated / 'data').mkdir(parents=True, exist_ok=True)
    (isolated / 'data' / 'memo_archived.json').write_text(json.dumps([
        {**_entry('ふるい', r=1), '削除日': old_day},
        {**_entry('まだ新しい', r=2), '削除日': recent},
    ], ensure_ascii=False), encoding='utf-8')

    got = memo_store.list_deleted()
    assert [e['馬名'] for e in got['entries']] == ['まだ新しい']
    assert _read(isolated / 'data' / 'memo_archived.json')[0]['馬名'] == 'まだ新しい'

    backups = list((isolated / 'backups').glob('memo_purged_*.json'))
    assert backups, '完全削除の前に控えを残すこと'
    assert _read(backups[0])[0]['馬名'] == 'ふるい'


def test_entries_without_a_valid_delete_date_are_not_purged(isolated):
    """日付が読めないものを勝手に消さない（都合よく解釈しない）。"""
    (isolated / 'data').mkdir(parents=True, exist_ok=True)
    (isolated / 'data' / 'memo_archived.json').write_text(json.dumps([
        {**_entry('日付なし', r=1)},
        {**_entry('壊れた日付', r=2), '削除日': 'いつか'},
    ], ensure_ascii=False), encoding='utf-8')
    got = memo_store.list_deleted()
    assert len(got['entries']) == 2
    assert all(e['days_left'] is None for e in got['entries'])


# ── 会場コードの表示 ─────────────────────────────────────────────
def test_venue_code_is_shown_as_venue_name(isolated):
    """自動登録の変換もれで「sp」等が入っていても、画面には会場名で出す。"""
    _write(isolated / 'memo_horses.json', [
        {'馬名': 'ルーフ', '登録日': '2026-07-25', '追加者': '',
         '元レース': {'日付': '2026/07/25', '場所': 'sp', 'R': 11, 'レース名': '', 'クラス': ''},
         'メモ': ''},
    ])
    got = memo_store.list_all()
    assert got['horses'][0]['entries'][0]['元レース']['場所'] == '札幌'
    # 元のファイルは書き換えない
    assert _read(isolated / 'memo_horses.json')[0]['元レース']['場所'] == 'sp'


def test_normalize_venue_covers_known_codes():
    for code, name in (('sp', '札幌'), ('hd', '函館'), ('fs', '福島'), ('ng', '新潟'),
                       ('kk', '小倉'), ('kt', '京都'), ('hs', '阪神'), ('tk', '東京')):
        assert memo_store.normalize_venue(code) == name
    assert memo_store.normalize_venue('東京') == '東京', '会場名はそのまま'
    assert memo_store.normalize_venue('') == ''


def test_key_uses_raw_value_so_it_matches_the_file(isolated):
    """表示は会場名に直すが、キーは保存データのまま（更新できなくなるのを防ぐ）。"""
    _write(isolated / 'memo_horses.json', [
        {'馬名': 'ルーフ', '登録日': '2026-07-25', '追加者': '',
         '元レース': {'日付': '2026/07/25', '場所': 'sp', 'R': 11, 'レース名': '', 'クラス': ''},
         'メモ': ''},
    ])
    key = memo_store.list_all()['horses'][0]['entries'][0]['key']
    memo_store.update(key, memo='書けること')
    assert _read(isolated / 'memo_horses.json')[0]['メモ'] == '書けること'


# ── ファイルの扱い ───────────────────────────────────────────────
def test_backup_is_kept_before_overwrite(isolated):
    _write(isolated / 'memo_horses.json', [_entry('A', r=1)])
    memo_store.update('A|2026/07/25|1', memo='x')
    backups = list((isolated / 'backups').glob('memo_horses_*.json'))
    assert backups, '上書き前の退避が作られていません'
    assert _read(backups[0])[0]['メモ'] == ''


def test_broken_file_raises_instead_of_being_treated_as_empty(isolated):
    """壊れたファイルを空扱いにして上書きしない（データ消失を防ぐ）。"""
    (isolated / 'memo_horses.json').write_text('{ こわれている', encoding='utf-8')
    with pytest.raises(RuntimeError):
        memo_store.list_all()
    with pytest.raises(RuntimeError):
        memo_store.add('A', {'日付': '2026/07/25', 'R': 1})


def test_output_format_matches_existing_pipeline(isolated):
    """既存 run_new.py と同じ書式（ensure_ascii=False, indent=2）で書くこと。"""
    memo_store.add('ラムジェット', {'日付': '2026/07/25', '場所': '新潟', 'R': 11,
                                    'レース名': '関屋記念', 'クラス': 'Ｇ３'})
    text = (isolated / 'memo_horses.json').read_text(encoding='utf-8')
    assert 'ラムジェット' in text, '日本語がエスケープされている'
    assert text.startswith('[\n  {\n'), 'インデント2で書かれていない'
