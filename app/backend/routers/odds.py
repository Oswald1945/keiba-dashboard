# -*- coding: utf-8 -*-
"""手入力オッズの保存API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import odds_store, paths

router = APIRouter(prefix='/api', tags=['odds'])


class OddsPayload(BaseModel):
    tansho: dict[str, float] = Field(default_factory=dict, description='馬番 -> 単勝オッズ')
    bets: dict[str, float] = Field(default_factory=dict, description='買い目キー -> オッズ')
    ev_core_version: str | None = Field(None, description='入力時のEV計算ロジック版')


def _check(race_id: str) -> None:
    if paths.parse_race_id(race_id) is None:
        raise HTTPException(400, f'race_id の形式が不正です: {race_id}')


@router.get('/races/{race_id}/odds')
def get_odds(race_id: str):
    _check(race_id)
    return odds_store.get(race_id)


@router.put('/races/{race_id}/odds')
def put_odds(race_id: str, payload: OddsPayload):
    _check(race_id)
    return odds_store.put(race_id, payload.tansho, payload.bets, payload.ev_core_version)


@router.delete('/races/{race_id}/odds')
def delete_odds(race_id: str):
    _check(race_id)
    return odds_store.clear(race_id)
