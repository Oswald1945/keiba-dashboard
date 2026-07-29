# -*- coding: utf-8 -*-
"""メモ馬の閲覧・編集API。

キーに日本語と「|」が入るので、更新系はURLではなく本文でキーを渡す。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services import memo_store

router = APIRouter(prefix='/api/memo', tags=['memo'])


class SourceRace(BaseModel):
    日付: str = Field(..., description='YYYY/MM/DD。空は不可（全レースに出てしまうため）')
    場所: str = ''
    R: int | str = ''
    レース名: str = ''
    クラス: str = ''


class AddPayload(BaseModel):
    馬名: str
    元レース: SourceRace
    メモ: str = ''
    追加者: str = ''
    expected_hash: str | None = None
    overwrite: bool = False


class UpdatePayload(BaseModel):
    key: str
    メモ: str | None = None
    追加者: str | None = None
    元レース: SourceRace | None = None
    expected_hash: str | None = None


class KeyPayload(BaseModel):
    key: str
    expected_hash: str | None = None


def _handle(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except memo_store.MemoConflict as e:
        raise HTTPException(409, str(e)) from e
    except memo_store.MemoDuplicate as e:
        raise HTTPException(
            409,
            {'code': 'duplicate', 'key': str(e),
             'message': '同じ馬・同じ元レースの登録が既にあります。'},
        ) from e
    except memo_store.MemoNotFound as e:
        raise HTTPException(404, f'該当のメモが見つかりません: {e}') from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e


@router.get('')
def list_memo():
    """馬名ごとにまとめた一覧。file_hash は保存時の競合検出に使う。"""
    return _handle(memo_store.list_all)


@router.get('/check')
def check_duplicate(name: str = Query(..., description='馬名')):
    """同じ馬名の既存登録を返す（手動追加前の重複確認）。"""
    entries = _handle(memo_store.find_by_name, name)
    return {'name': name, 'exists': bool(entries), 'entries': entries}


@router.get('/archived')
def list_deleted():
    """削除予定の一覧（7日で完全削除）。URLは互換のため archived のまま。"""
    return _handle(memo_store.list_deleted)


@router.post('/add')
def add_memo(payload: AddPayload):
    return _handle(
        memo_store.add,
        payload.馬名,
        payload.元レース.model_dump(),
        payload.メモ,
        payload.追加者,
        payload.expected_hash,
        payload.overwrite,
    )


@router.post('/update')
def update_memo(payload: UpdatePayload):
    return _handle(
        memo_store.update,
        payload.key,
        payload.メモ,
        payload.追加者,
        payload.元レース.model_dump() if payload.元レース else None,
        payload.expected_hash,
    )


@router.post('/archive')
def delete_memo(payload: KeyPayload):
    """削除（すぐには消さず7日間は戻せる）。URLは互換のため archive のまま。"""
    return _handle(memo_store.delete, payload.key, payload.expected_hash)


@router.post('/restore')
def restore_memo(payload: KeyPayload):
    return _handle(memo_store.restore, payload.key, payload.expected_hash)
