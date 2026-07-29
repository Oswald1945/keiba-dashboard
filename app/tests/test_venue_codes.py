# -*- coding: utf-8 -*-
"""会場コードの対応表がズレていないかを検査する。

このプロジェクトには会場の略号が3系統ある。
  1. `jv_export.JYO_ROMAJI`      … これから作るファイル名（sp/hk/fk/ng/tk/nk/ck/ky/hs/ok）
  2. 過去に作られたファイル名     … hd/fs/kt/kk など別表記が混在
  3. `build_dashboard_v3._VENUE_CODE` … 旧HTML命名の大文字コード

`run_new._VENUE_CODE_MAP` は 1〜3 のどれを渡されても会場名に戻せる必要がある。
実際、ここが食い違っていて **NK を「新潟」と判定していた**（正しくは中山。
20260321_NK11R フラワーカップ＝中山で確認）。小倉の OK は登録もれだった。
会場を丸ごと取り違える種類の不具合なので、テストで固定する。
"""
from __future__ import annotations

import importlib
import sys

import pytest

from app.backend import config
from app.backend.services import memo_store

JYO_NAME = {
    '01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
    '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉',
}

# 過去に生成されたファイルで実際に使われている略号（2026-07 実測）
LEGACY_CODES = {
    'sp': '札幌', 'hd': '函館', 'fs': '福島', 'ng': '新潟', 'tk': '東京',
    'ck': '中京', 'kt': '京都', 'hs': '阪神', 'kk': '小倉', 't': '東京',
}


def _load(name: str):
    root = str(config.ROOT_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)
    saved = sys.argv
    sys.argv = [f'{name}.py']
    try:
        return importlib.import_module(name)
    finally:
        sys.argv = saved


@pytest.fixture(scope='module')
def maps():
    jv = _load('jv_export')
    rn = _load('run_new')
    return jv, rn


def test_every_generated_code_maps_back_to_the_same_venue(maps):
    """これから作るファイル名の略号が、必ず元の会場名に戻ること。"""
    jv, rn = maps
    wrong = []
    for code, romaji in jv.JYO_ROMAJI.items():
        back = rn._VENUE_CODE_MAP.get(romaji.upper())
        if back != JYO_NAME[code]:
            wrong.append(f'{JYO_NAME[code]}({code}) -> {romaji} -> {back}')
    assert not wrong, '会場が入れ替わる: ' + ' / '.join(wrong)


def test_nakayama_is_not_confused_with_niigata(maps):
    """NK=中山 / NG=新潟。取り違えると全レースの会場が狂う。"""
    _jv, rn = maps
    assert rn._VENUE_CODE_MAP['NK'] == '中山'
    assert rn._VENUE_CODE_MAP['NG'] == '新潟'


def test_legacy_codes_still_resolve(maps):
    """過去に作ったファイルの略号も会場名に戻せること（一覧が壊れないように）。"""
    _jv, rn = maps
    wrong = []
    for code, name in LEGACY_CODES.items():
        back = rn._VENUE_CODE_MAP.get(code.upper())
        if back != name:
            wrong.append(f'{code} -> {back}（期待 {name}）')
    assert not wrong, '過去のファイルを解決できない: ' + ' / '.join(wrong)


def test_memo_auto_registration_uses_the_same_map(maps):
    """メモ馬の自動登録が独自の変換表を持たないこと。

    以前はここに別表があり、sp/fs/hd/kk/ng が変換されず「sp11R」のまま
    保存されていた（74件）。
    """
    _jv, rn = maps
    src = (config.ROOT_DIR / 'run_new.py').read_text(encoding='utf-8')
    assert 'PLACE_MAP = _VENUE_CODE_MAP' in src, \
        'メモ馬の自動登録が独自の会場変換表を持っている'


def test_app_side_normalization_covers_both_schemes():
    """アプリの表示用変換も、新旧どちらの略号も会場名に直せること。"""
    for code, name in LEGACY_CODES.items():
        assert memo_store.normalize_venue(code) == name, f'{code} が {name} にならない'
    for code, name in (('hk', '函館'), ('fk', '福島'), ('ky', '京都'),
                       ('ok', '小倉'), ('nk', '中山')):
        assert memo_store.normalize_venue(code) == name, f'{code} が {name} にならない'


def test_dashboard_html_codes_resolve(maps):
    """旧HTML命名（20260321_NK11R_...）の大文字コードも戻せること。"""
    _jv, rn = maps
    for code, name in (('NK', '中山'), ('KY', '京都'), ('HN', '阪神'),
                       ('HK', '函館'), ('FK', '福島'), ('KK', '小倉'),
                       ('TK', '東京'), ('SP', '札幌'), ('NG', '新潟'), ('CK', '中京')):
        assert rn._VENUE_CODE_MAP.get(code) == name, f'{code} が {name} にならない'
