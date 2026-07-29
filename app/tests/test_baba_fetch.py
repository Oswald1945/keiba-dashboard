# -*- coding: utf-8 -*-
"""JRA馬場情報の解析。保存済みHTMLだけを使い、ネットワークには一切触らない。

fixtures は 2026-07-26（新潟・中京・札幌の3場開催）に実際に配信されていたもの。
"""
from __future__ import annotations

import pytest

from app.backend import config
from app.backend.services import baba_fetch as bf

FIX = config.TESTS_DIR / 'fixtures' / 'jra_baba'

pytestmark = pytest.mark.skipif(
    not (FIX / 'cushion.html').exists(),
    reason='JRA馬場のテスト用HTMLがありません',
)


def _read(name: str) -> str:
    return (FIX / f'{name}.html').read_text(encoding='utf-8')


def _fetcher(url: str) -> str:
    name = {
        bf.DATA_CUSHION: 'cushion',
        bf.DATA_MOIST: 'moist',
        bf.DATA_WEEK: 'week',
        bf.INDEX_PAGES[0]: 'index',
        bf.INDEX_PAGES[1]: 'index2',
        bf.INDEX_PAGES[2]: 'index3',
    }[url]
    return _read(name)


# ── 個別の解析 ───────────────────────────────────────────────────
def test_cushion_is_parsed_per_venue():
    got = bf.parse_cushion(_read('cushion'))
    assert set(got) == {'新潟', '中京', '札幌'}, '会場が title 属性から取れていない'
    assert got['新潟']['value'] == 9.6
    assert '7月26日' in got['新潟']['time'], '測定時刻が取れていない'
    assert len(got['新潟']['history']) >= 2, '過去の測定値も持っておく'


def test_moisture_gives_values_and_going_band():
    got = bf.parse_moist(_read('moist'))
    ng = got['新潟']
    assert ng['芝']['mg']['value'] == 12.9
    assert ng['芝']['m4c']['value'] == 12.4
    assert ng['ダート']['mg']['value'] == 8.9
    # data-condition から馬場状態の目安に変換できていること
    assert ng['芝']['mg']['baba'] == '良'
    assert ng['ダート']['mg']['baba'] == '稍重'
    assert ng['rain_mm'] == 4.0


def test_condition_mapping_covers_all_bands():
    assert bf.CONDITION_TO_BABA == {'hard': '良', 'wet': '稍重', 'soft': '重', 'heavy': '不良'}


def test_weather_takes_today_as_last_item():
    got = bf.parse_week_weather(_read('week'))
    assert got['新潟']['today'] == '曇時々雨'
    assert len(got['新潟']['series']) == 10


def test_index_gives_venue_kaisai_and_course():
    got = bf.parse_index(_read('index'))
    assert got['venue'] == '新潟'
    assert got['kaisai'] == '第2回新潟競馬第2日'
    assert got['date'] == '20260726'
    # 「使用コース」直後はタグで分断されるので、そこも拾えていること
    assert got['course_used'] == 'Aコース（内柵を最内に設置）'


def test_index_does_not_confuse_heading_with_course():
    """見出し『使用コース・芝の様子』を使用コースとして拾わないこと。"""
    got = bf.parse_index(_read('index2'))
    assert got['course_used'] and got['course_used'].startswith(('A', 'B', 'C', 'D'))
    assert '芝の様子' not in got['course_used']


# ── まとめ ───────────────────────────────────────────────────────
def test_fetch_all_merges_by_venue_name():
    got = bf.fetch_all(fetcher=_fetcher)
    assert got['is_estimate'] is True, '発表馬場ではなく目安であることを示すこと'
    venues = {v['venue']: v for v in got['venues']}
    assert set(venues) == {'新潟', '中京', '札幌'}

    ng = venues['新潟']
    assert ng['cushion'] == 9.6
    assert ng['weather'] == '曇時々雨'
    assert ng['course_used'] == 'Aコース（内柵を最内に設置）'
    assert ng['estimated_turf'] == '良'
    assert ng['estimated_dirt'] == '稍重'
    assert ng['kaisai'] == '第2回新潟競馬第2日'

    # 会場ごとに違う値が入っていること（取り違えていない）
    assert venues['中京']['cushion'] == 9.5
    assert venues['札幌']['cushion'] == 7.6
    assert venues['中京']['weather'] == '晴'


def test_decode_handles_shift_jis():
    raw = '馬場情報 クッション値'.encode('cp932')
    assert bf.decode(raw) == '馬場情報 クッション値'
