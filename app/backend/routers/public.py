# -*- coding: utf-8 -*-
"""公開（閲覧）API。読み取りのみ。既存ファイルを一切書き換えない。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from pydantic import BaseModel

from ..services import catalog, ev, featured_store, paths

router = APIRouter(prefix='/api', tags=['public'])


@router.get('/health')
def health():
    from .. import config
    return {
        'status': 'ok',
        'root': str(config.ROOT_DIR),
        'root_exists': config.ROOT_DIR.exists(),
        'score_py': config.SCORE_PY.exists(),
        'frontend_built': config.FRONTEND_DIST.exists(),
    }


@router.get('/mode')
def mode(request: Request):
    """公開モードかどうかと、ログイン中の利用者ID。

    画面側は、これを見て管理モードの切替を出すかどうかを決める。
    公開モードでは管理・検証のルーターをそもそも読み込んでいないので、
    切替を出しても押せる機能が無く、あるように見えるだけで紛らわしい。
    """
    from .. import config
    from ..services import auth
    return {
        'public_mode': config.PUBLIC_MODE,
        'user_id': auth.read_session(request.cookies.get(auth.COOKIE_NAME, '')),
    }


@router.get('/races')
def list_races(
    date: str | None = Query(None, description='YYYYMMDD で絞り込み'),
    venue: str | None = Query(None, description='会場名で絞り込み'),
    jra_only: bool = Query(False, description='JRAのみ'),
    q: str | None = Query(None, description='レース名・クラス・馬名の部分一致'),
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    rows = catalog.list_races()
    if date:
        rows = [r for r in rows if r['date'] == date]
    if venue:
        rows = [r for r in rows if r['venue'] == venue]
    if jra_only:
        rows = [r for r in rows if r['is_jra']]
    if q:
        needle = q.lower()

        def hit(r: dict) -> bool:
            if needle in (r.get('race_name') or '').lower():
                return True
            if needle in (r.get('race_class') or '').lower():
                return True
            if needle in r['race_id'].lower():
                return True
            # 馬名でも探せるようにする（出走馬から探す使い方に対応）
            return any(needle in (n or '').lower() for n in (r.get('horse_names') or []))

        rows = [r for r in rows if hit(r)]
    total = len(rows)
    return {'total': total, 'offset': offset, 'limit': limit,
            'races': rows[offset:offset + limit]}


class FeaturedPayload(BaseModel):
    race_id: str
    featured: bool


def _who(request: Request) -> str:
    """注目レースを誰のものとして扱うか。

    公開サーバーではログイン中の利用者ID。このPCにはログインが無いので 'local'。
    """
    from ..services import auth
    user = auth.read_session(request.cookies.get(auth.COOKIE_NAME, ''))
    return user or featured_store.LOCAL_USER


@router.get('/featured')
def list_featured(request: Request):
    """自分が注目の印を付けたレースID（他の利用者の分は返さない）。"""
    return {'race_ids': featured_store.list_ids(_who(request))}


@router.post('/featured')
def set_featured(payload: FeaturedPayload, request: Request):
    """注目レースの印を付ける / 外す。自分の分だけが変わる。"""
    try:
        return featured_store.set_featured(
            payload.race_id, payload.featured, _who(request))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get('/races/{race_id}')
def get_race(race_id: str):
    row = catalog.get_race(race_id)
    if row is None:
        raise HTTPException(404, f'レースが見つかりません: {race_id}')
    return row


@router.get('/races/{race_id}/ev-data')
def get_ev_data(race_id: str):
    """EV判定の素材（build_dashboard_v3 の EV_DATA と同じ形）。"""
    if paths.parse_race_id(race_id) is None:
        raise HTTPException(400, f'race_id の形式が不正です: {race_id}')
    rows = ev.ev_data(race_id)
    if rows is None:
        raise HTTPException(404, f'まだ採点されていません: {race_id}')
    return {'race_id': race_id, 'horses': rows}


def _html_response(path, race_id: str, kind: str):
    if path is None:
        raise HTTPException(404, f'{kind} がまだ生成されていません: {race_id}')
    return FileResponse(path, media_type='text/html; charset=utf-8')


@router.get('/races/{race_id}/pred.html')
def get_pred_html(race_id: str):
    """既存の予想ダッシュボードHTMLをそのまま配信する。"""
    return _html_response(paths.pred_html(race_id), race_id, '予想ダッシュボード')


@router.get('/races/{race_id}/review.html')
def get_review_html(race_id: str):
    """既存の回顧ダッシュボードHTMLをそのまま配信する。"""
    return _html_response(paths.review_html(race_id), race_id, '回顧ダッシュボード')
