# -*- coding: utf-8 -*-
"""検証（的中精度・妙味）の集計。

いちばん大事なのは **母数の取り方**。複勝配当は3着以内のときだけ記録されているので、
「配当が記録されているレース」を母数にすると回収率143%というありえない数字が出る。
そこを取り違えていないことを固定する。
"""
from __future__ import annotations

import math

import pytest

from app.backend.services import validation as V

needs_data = pytest.mark.skipif(
    not any(s['exists'] for s in V.available_sources()),
    reason='検証用の因子データがありません',
)

FULL = {'date_from': None, 'date_to': None, 'include_maiden': False}


# ── 順位相関（scipy を使わない実装） ─────────────────────────────
def test_spearman_matches_known_values():
    assert V._spearman([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == pytest.approx(1.0)
    assert V._spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == pytest.approx(-1.0)


def test_spearman_handles_ties_and_short_input():
    # 全部同値なら相関は定義できない
    assert math.isnan(V._spearman([1, 1, 1, 1], [1, 2, 3, 4]))
    # 4件未満は計算しない
    assert math.isnan(V._spearman([1, 2, 3], [3, 2, 1]))
    # 同順位があっても計算できる
    r = V._spearman([1, 1, 2, 3], [1, 2, 3, 4])
    assert -1.0 <= r <= 1.0


# ── 複勝配当の引き当て ───────────────────────────────────────────
def test_fukusho_payout_matches_umaban():
    payouts = {'fukusho': [['6', 110], ['10', 210], ['3', 140]]}
    assert V._fukusho_payout(payouts, 10) == 210.0
    assert V._fukusho_payout(payouts, '3') == 140.0
    assert V._fukusho_payout(payouts, 99) is None
    assert V._fukusho_payout({}, 6) is None


# ── 集計 ─────────────────────────────────────────────────────────
@needs_data
def test_accuracy_reproduces_ledger_numbers():
    """台帳の「軸複勝率≒50%・1番人気≒62%」と整合すること。"""
    a = V.accuracy(FULL)
    assert a['races'] > 5000
    assert 0.45 < a['axis_place_rate'] < 0.55, '軸複勝率が台帳と大きく食い違う'
    assert 0.58 < a['pop1_place_rate'] < 0.68, '1番人気の複勝率が想定外'
    # 市場のほうが強い（プロジェクトの前提）
    assert a['axis_place_rate'] < a['pop1_place_rate']
    assert a['spearman'] > 0, '予想順位と着順が逆相関になっている'


@needs_data
def test_maiden_races_are_excluded_by_default():
    without = V.accuracy(FULL)
    with_maiden = V.accuracy({**FULL, 'include_maiden': True})
    assert with_maiden['races'] > without['races'], '新馬・未勝利が既定で除外されていない'
    classes = {b['key'] for b in without['by_class']}
    assert '新馬' not in classes and '未勝利' not in classes


@needs_data
def test_period_filter_narrows_result():
    all_races = V.accuracy(FULL)['races']
    one_year = V.accuracy({**FULL, 'date_from': '20250101'})['races']
    assert 0 < one_year < all_races


@needs_data
def test_baba_breakdown_is_present_and_ordered_by_size():
    a = V.accuracy(FULL)
    keys = [b['key'] for b in a['by_baba']]
    assert '良' in keys and '重' in keys
    sizes = [b['races'] for b in a['by_baba']]
    assert sizes == sorted(sizes, reverse=True)


@needs_data
def test_factor_diagnostics_covers_all_factors():
    d = V.factor_diagnostics(FULL)
    got = {f['factor'] for f in d['factors']}
    assert got == set(V.FACTORS), f'欠けている因子: {set(V.FACTORS) - got}'
    for f in d['factors']:
        c = f['calibration']
        assert c['top1'] is not None and c['rest'] is not None
        # どの因子も「pts上位ほど複勝率が高い」（台帳: 向きのバグは無い）
        assert c['top1'] > c['rest'], f'{f["factor"]} の向きがおかしい'
        assert 0 <= (f['variation_rate'] or 0) <= 1


@needs_data
def test_value_axis_uses_all_races_as_denominator():
    """複勝回収率の母数を「当たったレース」にしていないこと。"""
    v = V.value_axis(FULL)
    assert v['investment'] == v['races'] * 100
    # 的中したレースだけを母数にすると 140% 超になる。全レース母数なら市場水準以下。
    assert v['place']['roi'] < 1.0, (
        f'複勝回収率が {v["place"]["roi"]:.1%}。母数の取り方を間違えている可能性がある'
    )
    assert v['win']['roi'] < 1.0
    # 的中率は精度検証の軸複勝率と一致するはず（同じ軸の定義）
    a = V.accuracy(FULL)
    assert abs(v['place']['hit_rate'] - a['axis_place_rate']) < 0.02


@needs_data
def test_value_formation_reports_investment_and_roi():
    v = V.value_formation({'date_from': None, 'date_to': None})
    if not v['total']['bet_types']:
        pytest.skip('roi_rows.jsonl にデータがありません')
    for bt in v['total']['bet_types']:
        assert bt['investment'] == bt['points'] * 100
        assert bt['payout'] >= 0
        assert bt['roi'] == pytest.approx(bt['payout'] / bt['investment'])
    assert v['total']['axis']['investment'] == v['total']['axis']['races'] * 100


@needs_data
def test_value_formation_period_filter():
    wide = V.value_formation({'date_from': None, 'date_to': None})['total']['races']
    narrow = V.value_formation({'date_from': '20260601', 'date_to': None})['total']['races']
    assert narrow <= wide


@needs_data
def test_data_range_reports_source_and_span():
    r = V.data_range()
    assert r['source'].startswith('factor_rows')
    assert r['accuracy']['from'] < r['accuracy']['to']
    assert r['source_key'] in {s['key'] for s in V.DATA_SOURCES}
    assert r['note']


@needs_data
def test_sources_are_listed_newest_first_and_flagged():
    srcs = V.available_sources()
    assert [s['key'] for s in srcs] == ['p4', 'p3', 'base'], '新しい世代が先頭に来ること'
    for s in srcs:
        assert isinstance(s['exists'], bool)
        if s['exists']:
            assert s['size_mb'] and s['size_mb'] > 0


@needs_data
def test_default_source_prefers_newest_available():
    assert V.default_source() == next(s['key'] for s in V.available_sources() if s['exists'])


@needs_data
def test_p3_source_warns_that_p4_is_missing():
    """P3世代を見ているときは「現行と違う」と分かる注記が出ること。"""
    note = V._source_note('p3')
    assert 'P4' in note and 'P3＋P4' in note


def test_p4_source_note_says_it_matches_production():
    assert '現行モデル' in V._source_note('p4')


def test_unknown_source_is_rejected():
    with pytest.raises(ValueError):
        V.dataset('そんな世代はない')


@needs_data
def test_missing_source_file_raises_with_guidance():
    missing = next((s for s in V.available_sources() if not s['exists']), None)
    if missing is None:
        pytest.skip('未作成の世代がありません')
    with pytest.raises(FileNotFoundError) as e:
        V.dataset(missing['key'])
    assert '採点し直す' in str(e.value), '作り方の案内を出すこと'
