# -*- coding: utf-8 -*-
"""検証API（的中精度・妙味）。読み取りのみ。"""
from __future__ import annotations

import datetime

from fastapi import APIRouter, HTTPException, Query

from ..services import validation

router = APIRouter(prefix='/api/validation', tags=['validation'])


def _filters(
    date_from: str | None,
    date_to: str | None,
    venues: list | None,
    classes: list | None,
    babas: list | None,
    surfaces: list | None,
    include_maiden: bool,
    source: str | None = None,
) -> dict:
    return {
        'source': source or None,
        'date_from': date_from or None,
        'date_to': date_to or None,
        'venues': venues or None,
        'classes': classes or None,
        'babas': babas or None,
        'surfaces': surfaces or None,
        'include_maiden': bool(include_maiden),
    }


@router.get('/range')
def data_range(source: str | None = None):
    """使えるデータの世代・期間と、期間プリセット。"""
    try:
        rng = validation.data_range(source)
    except FileNotFoundError as e:
        raise HTTPException(503, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    today = datetime.date.today()

    def back(years: int) -> str:
        try:
            return today.replace(year=today.year - years).strftime('%Y%m%d')
        except ValueError:      # 2/29
            return today.replace(year=today.year - years, day=28).strftime('%Y%m%d')

    acc = rng.get('accuracy') or {}
    presets = [
        {'key': '1y', 'label': '過去1年', 'date_from': back(1), 'date_to': None},
        {'key': '5y', 'label': '過去5年', 'date_from': back(5), 'date_to': None},
        {'key': '10y', 'label': '過去10年', 'date_from': back(10), 'date_to': None},
        {'key': 'all', 'label': '全期間', 'date_from': None, 'date_to': None},
    ]
    for p in presets:
        # データが無い期間を選んでも「無い」と分かるようにしておく
        p['covered_from'] = max(filter(None, [p['date_from'], acc.get('from')]), default=None)
    return {**rng, 'presets': presets, 'today': today.strftime('%Y%m%d')}


@router.get('/accuracy')
def accuracy(
    date_from: str | None = None,
    date_to: str | None = None,
    venues: list[str] | None = Query(None),
    classes: list[str] | None = Query(None),
    babas: list[str] | None = Query(None),
    surfaces: list[str] | None = Query(None),
    include_maiden: bool = False,
    source: str | None = None,
):
    """的中精度（軸複勝率・順位相関・上位3頭重複・1番人気ベースライン）。"""
    f = _filters(date_from, date_to, venues, classes, babas, surfaces,
                 include_maiden, source)
    try:
        return {'filters': f, **validation.accuracy(f)}
    except FileNotFoundError as e:
        raise HTTPException(503, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get('/factors')
def factors(
    date_from: str | None = None,
    date_to: str | None = None,
    venues: list[str] | None = Query(None),
    classes: list[str] | None = Query(None),
    babas: list[str] | None = Query(None),
    surfaces: list[str] | None = Query(None),
    include_maiden: bool = False,
    source: str | None = None,
):
    """16因子それぞれの単独複勝率・キャリブレーション・順位相関・変動率。"""
    f = _filters(date_from, date_to, venues, classes, babas, surfaces,
                 include_maiden, source)
    try:
        return {'filters': f, **validation.factor_diagnostics(f)}
    except FileNotFoundError as e:
        raise HTTPException(503, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get('/value')
def value(
    date_from: str | None = None,
    date_to: str | None = None,
    venues: list[str] | None = Query(None),
    classes: list[str] | None = Query(None),
    babas: list[str] | None = Query(None),
    surfaces: list[str] | None = Query(None),
    include_maiden: bool = False,
    source: str | None = None,
):
    """妙味（監視・確認用）。軸の単複は5年分、券種は roi_rows の範囲。"""
    f = _filters(date_from, date_to, venues, classes, babas, surfaces,
                 include_maiden, source)
    try:
        return {
            'filters': f,
            'axis': validation.value_axis(f),
            'formation': validation.value_formation(f),
            'notice': ('モデルは市場に妙味では勝てないことが検証済みです。'
                       'この画面は監視・確認のためのもので、収益を前提としたものではありません。'),
        }
    except FileNotFoundError as e:
        raise HTTPException(503, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
