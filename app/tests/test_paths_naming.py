# -*- coding: utf-8 -*-
"""pred/review HTML の命名ゆれを全部拾えること。

実データには3種類の命名が混在している（2026-07-27 実測）:
  新   20260726_sp9_pred.html
  中   20260530_kt12_C2_review.html / 20260620_hs11_Open_TenpouzanS_review.html
  旧   20260222_TK11R_G1_FeburariiS_pred.html

中形式を拾えないと「回顧が作られていない」と誤判定する
（実際に6月分54レースを未作成と誤表示していた）。
"""
from __future__ import annotations

import pytest

from app.backend.services import paths


@pytest.fixture
def rooted(tmp_path, monkeypatch):
    monkeypatch.setattr(paths.config, 'OUT_DIR', tmp_path)
    paths.clear_html_index_cache()
    yield tmp_path
    paths.clear_html_index_cache()


def _touch(d, name):
    p = d / name
    p.write_text('<html></html>', encoding='utf-8')
    return p


def test_new_naming(rooted):
    _touch(rooted, '20260726_sp9_pred.html')
    _touch(rooted, '20260726_sp9_review.html')
    paths.clear_html_index_cache()
    assert paths.pred_html('20260726_sp9').name == '20260726_sp9_pred.html'
    assert paths.review_html('20260726_sp9').name == '20260726_sp9_review.html'


def test_middle_naming_with_class_and_race_name(rooted):
    _touch(rooted, '20260620_hs11_Open_TenpouzanS_review.html')
    _touch(rooted, '20260530_kt12_C2_pred.html')
    paths.clear_html_index_cache()
    assert paths.review_html('20260620_hs11').name == '20260620_hs11_Open_TenpouzanS_review.html'
    assert paths.pred_html('20260530_kt12').name == '20260530_kt12_C2_pred.html'


def test_middle_naming_with_numeric_suffix(rooted):
    """20260621_hs12_2_review.html のように数字だけ付くものも拾う。"""
    _touch(rooted, '20260621_hs12_2_review.html')
    paths.clear_html_index_cache()
    assert paths.review_html('20260621_hs12').name == '20260621_hs12_2_review.html'


def test_legacy_naming(rooted):
    _touch(rooted, '20260222_TK11R_G1_FeburariiS_pred.html')
    paths.clear_html_index_cache()
    assert paths.pred_html('20260222_t11').name == '20260222_TK11R_G1_FeburariiS_pred.html'


def test_new_naming_wins_over_middle(rooted):
    _touch(rooted, '20260530_kt12_C2_review.html')
    _touch(rooted, '20260530_kt12_review.html')
    paths.clear_html_index_cache()
    assert paths.review_html('20260530_kt12').name == '20260530_kt12_review.html'


def test_similar_race_ids_are_not_confused(rooted):
    """kt1 と kt12 を取り違えないこと。"""
    _touch(rooted, '20260530_kt12_C2_review.html')
    paths.clear_html_index_cache()
    assert paths.review_html('20260530_kt1') is None
    assert paths.review_html('20260530_kt12') is not None


def test_pred_and_review_are_not_mixed_up(rooted):
    _touch(rooted, '20260530_kt12_C2_pred.html')
    paths.clear_html_index_cache()
    assert paths.pred_html('20260530_kt12') is not None
    assert paths.review_html('20260530_kt12') is None


def test_missing_race_returns_none(rooted):
    paths.clear_html_index_cache()
    assert paths.pred_html('20260101_tk1') is None
    assert paths.review_html('20260101_tk1') is None
