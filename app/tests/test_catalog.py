# -*- coding: utf-8 -*-
"""race_id の解析とレース一覧の基本動作。基準データが無くても動く。"""
from __future__ import annotations

import pytest

from app.backend.services import catalog, paths


@pytest.mark.parametrize('race_id,date,code,no,venue,is_jra', [
    ('20260726_sp9', '20260726', 'sp', 9, '札幌', True),
    ('20260523_kt12', '20260523', 'kt', 12, '京都', True),
    ('20260222_t11', '20260222', 't', 11, '東京', True),
    ('20260411_hs11', '20260411', 'hs', 11, '阪神', True),
    ('20260314_CK12', '20260314', 'CK', 12, '中京', True),
])
def test_parse_race_id_jra(race_id, date, code, no, venue, is_jra):
    key = paths.parse_race_id(race_id)
    assert key is not None
    assert (key.date, key.venue_code, key.race_no) == (date, code, no)
    assert key.venue == venue
    assert key.is_jra is is_jra


@pytest.mark.parametrize('race_id,venue', [
    ('20260601_oi11', '大井'),
    ('20260601_kw5', '川崎'),
    ('20260601_en3', '園田'),
])
def test_parse_race_id_nar(race_id, venue):
    """地方(NAR)の会場も会場名まで解決できること。"""
    key = paths.parse_race_id(race_id)
    assert key is not None
    assert key.venue == venue
    assert key.is_jra is False


@pytest.mark.parametrize('bad', [
    '', 'horses_data', '2026072_sp9', '20260726sp9', '20260726_9',
    '20260726_sp', '20260726_sp999',
])
def test_parse_race_id_rejects_bad(bad):
    assert paths.parse_race_id(bad) is None


def test_list_races_shape():
    rows = catalog.list_races()
    assert rows, 'レースが1件も見つかりません'
    required = {'race_id', 'date', 'venue', 'race_no', 'scored',
                'has_pred', 'has_review', 'is_jra'}
    for r in rows[:50]:
        assert required <= set(r), f'項目が足りません: {r["race_id"]}'
    # 新しい順に並んでいること
    dates = [r['date'] for r in rows]
    assert dates == sorted(dates, reverse=True)


def test_list_races_is_cached_and_stable():
    a = catalog.list_races()
    b = catalog.list_races()
    assert [r['race_id'] for r in a] == [r['race_id'] for r in b]


def test_pred_html_lookup_handles_legacy_naming():
    """旧命名（20260222_TK11R_G1_..._pred.html）も引けること。"""
    rows = [r for r in catalog.list_races() if r['has_pred']]
    assert rows, '予想HTMLのあるレースが見つかりません'
    legacy = [r for r in rows
              if r['pred_file'] and not r['pred_file'].startswith(r['race_id'])]
    if not legacy:
        pytest.skip('旧命名の予想HTMLがこの環境にありません')
    for r in legacy[:5]:
        assert paths.pred_html(r['race_id']) is not None
