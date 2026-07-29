# -*- coding: utf-8 -*-
"""管理API（実行系）。

このPCの中からのみ受け付ける。実行は必ず1本ずつ（jobs.runner が直列化）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..services import (baba_store, jobs, jvlink, pipeline, racedb,
                        review_status)

router = APIRouter(prefix='/api/admin', tags=['admin'])

ALLOWED_HOSTS = {'127.0.0.1', '::1', 'localhost'}


def _local_only(request: Request) -> None:
    host = request.client.host if request.client else None
    if host not in ALLOWED_HOSTS:
        raise HTTPException(403, '管理機能はこのPCの中からのみ利用できます。')


def _busy_guard() -> None:
    cur = jobs.runner.current()
    if cur is not None and cur.status == 'running':
        raise HTTPException(
            409, f'いま「{cur.name}」を実行中です。終わってから実行してください。')


# ── 状態 ─────────────────────────────────────────────────────────
@router.get('/status')
def status(request: Request):
    _local_only(request)
    cur = jobs.runner.current()
    return {
        'race_db': racedb.available(),
        'jvlink': jvlink.environment(),
        'realtime': jvlink.realtime_setting(),
        'running_job': (cur.public(after=max(0, len(cur.lines) - 5)) if cur else None),
        'recent_jobs': jobs.runner.recent(10),
    }


@router.get('/races/predictable')
def predictable(request: Request):
    """これから予想できるレース（結果未確定）。新馬・未勝利には印を付ける。"""
    _local_only(request)
    try:
        return {'groups': racedb.predictable_races()}
    except racedb.RaceDbUnavailable as e:
        raise HTTPException(503, str(e)) from e


@router.get('/generated')
def generated(request: Request, date: str):
    """指定日の生成物と公開状況。「確認してから公開」の画面で使う。"""
    _local_only(request)
    from ..services import catalog, paths

    published = {}
    log = config_share_log()
    if log.exists():
        for line in log.read_text(encoding='utf-8').splitlines():
            parts = line.split('\t')
            if len(parts) == 2:
                published[parts[0]] = parts[1]

    rows = []
    for r in catalog.list_races():
        if r['date'] != date:
            continue
        rid = r['race_id']
        pred = paths.pred_html(rid)
        review = paths.review_html(rid)
        rows.append({
            **r,
            'published_pred': published.get(f'{rid}_pred') or published.get(rid),
            'published_review': published.get(f'{rid}_review'),
            'pred_size': (pred.stat().st_size if pred else None),
            'review_size': (review.stat().st_size if review else None),
        })
    return {'date': date, 'races': rows}


def config_share_log():
    from .. import config
    return config.ROOT_DIR / 'shared_urls.txt'


@router.get('/reviews/status')
def reviews_status(request: Request):
    """回顧が未作成のもの／速報のままで作り直せるもの。"""
    _local_only(request)
    return review_status.overview()


# ── 馬場 ─────────────────────────────────────────────────────────
@router.get('/baba/preview')
def baba_preview(request: Request, date: str):
    """JRAから取得した値と保存済みの値を並べて返す（保存はしない）。"""
    _local_only(request)
    return baba_store.preview(date)


class BabaSave(BaseModel):
    date: str
    venues: dict = Field(..., description='会場 -> {芝, ダート, 天候, クッション値, ...}')


@router.post('/baba/save')
def baba_save(request: Request, payload: BabaSave):
    """確認・修正済みの馬場を baba_manual.json に保存する。"""
    _local_only(request)
    try:
        return baba_store.save(payload.date, payload.venues)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get('/baba/saved')
def baba_saved(request: Request, date: str):
    _local_only(request)
    return {'date': date, 'venues': baba_store.get(date)}


# ── ジョブ ───────────────────────────────────────────────────────
@router.get('/jobs/{job_id}')
def job_detail(request: Request, job_id: str, after: int = 0):
    _local_only(request)
    job = jobs.runner.get(job_id)
    if job is None:
        raise HTTPException(404, f'ジョブが見つかりません: {job_id}')
    return job.public(after=after)


@router.post('/jobs/{job_id}/cancel')
def job_cancel(request: Request, job_id: str):
    _local_only(request)
    if not jobs.runner.cancel(job_id):
        raise HTTPException(400, 'このジョブは中断できません（すでに終了している可能性があります）')
    return {'cancelled': job_id}


class RaceTargets(BaseModel):
    targets: list = Field(default_factory=list,
                          description='[{date, jyo, race_no}, ...]')


class ForceFlag(BaseModel):
    force: bool = False


class DateBody(BaseModel):
    date: str


class PublishBody(BaseModel):
    race_ids: list = Field(default_factory=list)


def _submit(name: str, fn):
    _busy_guard()
    job = jobs.runner.submit(name, fn)
    return {'job_id': job.id, 'name': job.name, 'status': job.status}


@router.post('/update')
def run_update(request: Request):
    """① race.db の差分更新。"""
    _local_only(request)
    return _submit('データ更新（JV-Link差分）', lambda job: jvlink.update(job))


@router.post('/export')
def run_export(request: Request, body: RaceTargets):
    """② 選んだレースを input/ にエクスポート。"""
    _local_only(request)
    if not body.targets:
        raise HTTPException(400, 'レースが選ばれていません')
    return _submit(f'エクスポート（{len(body.targets)}レース）',
                   lambda job: pipeline.export_races(job, body.targets))


@router.post('/smartrc')
def run_smartrc(request: Request, body: RaceTargets):
    """④ SmartRC取得（rcodeは race.db から自動生成）。"""
    _local_only(request)
    if not body.targets:
        raise HTTPException(400, 'レースが選ばれていません')
    return _submit(f'SmartRC取得（{len(body.targets)}レース）',
                   lambda job: pipeline.fetch_smartrc(job, body.targets))


@router.post('/predict')
def run_predict(request: Request, body: ForceFlag):
    """⑤ 採点 → 予想ダッシュボード生成（公開はしない）。"""
    _local_only(request)
    return _submit('予想の生成', lambda job: pipeline.build_predictions(job, force=body.force))


@router.post('/realtime-date')
def run_set_realtime(request: Request, body: DateBody):
    """⑥ 速報系の対象開催日を設定（当日・前日の結果を取り込むため）。"""
    _local_only(request)
    return _submit(f'速報の対象日を{body.date}に設定',
                   lambda job: jvlink.set_realtime_date(job, body.date))


@router.post('/fetch-results')
def run_fetch_results(request: Request, body: DateBody):
    """⑥ 対象日を設定してから差分更新（速報結果の取り込み）を続けて行う。"""
    _local_only(request)

    def fn(job):
        jvlink.set_realtime_date(job, body.date)
        jvlink.update(job)
        job.result['result_status'] = racedb.result_status(body.date)

    return _submit(f'結果の取り込み（{body.date}）', fn)


@router.get('/results/{date}')
def results(request: Request, date: str):
    """結果の取得状況（check_results.py 相当）。"""
    _local_only(request)
    try:
        return racedb.result_status(date)
    except racedb.RaceDbUnavailable as e:
        raise HTTPException(503, str(e)) from e


@router.post('/review')
def run_review(request: Request, body: RaceTargets):
    """⑦ 回顧の生成（結果込みで再エクスポート → 回顧HTML）。公開はしない。"""
    _local_only(request)
    return _submit(f'回顧の生成（{len(body.targets)}レース）',
                   lambda job: pipeline.build_reviews(job, body.targets))


class RescoreBody(BaseModel):
    date_from: str = Field('20210601', description='YYYYMMDD')
    date_to: str = Field('20260628', description='YYYYMMDD')
    out_file: str = Field('factor_rows_p4.jsonl')


@router.post('/rescore')
def run_rescore(request: Request, body: RescoreBody):
    """検証用の5年データを、いまの採点ロジックで作り直す（長時間・再開可能）。"""
    _local_only(request)
    for d in (body.date_from, body.date_to):
        if not d.isdigit() or len(d) != 8:
            raise HTTPException(400, f'日付は YYYYMMDD で指定してください: {d}')
    if not body.out_file.startswith('factor_rows') or not body.out_file.endswith('.jsonl'):
        raise HTTPException(400, '出力先は factor_rows*.jsonl にしてください')
    if body.out_file in ('factor_rows.jsonl', 'factor_rows_p3.jsonl'):
        raise HTTPException(400, '既存の検証データは上書きできません（別ファイル名にしてください）')
    return _submit(
        f'検証データの作り直し（{body.date_from}〜{body.date_to}）',
        lambda job: pipeline.rescore_factors(job, body.date_from, body.date_to, body.out_file),
    )


@router.post('/publish')
def run_publish(request: Request, body: PublishBody):
    """確認したものを GitHub Pages へ公開する。

    公開サーバーへの反映は /app-publish に移したので、画面からは呼んでいない。
    """
    _local_only(request)
    if not body.race_ids:
        raise HTTPException(400, '公開するレースが選ばれていません')
    return _submit(f'公開（{len(body.race_ids)}レース）',
                   lambda job: pipeline.publish(job, body.race_ids))


@router.post('/app-publish')
def run_app_publish(request: Request, body: PublishBody):
    """確認したものを公開サーバー（アプリ）へ送る。"""
    _local_only(request)
    if not body.race_ids:
        raise HTTPException(400, '公開するレースが選ばれていません')
    return _submit(f'アプリ公開（{len(body.race_ids)}レース）',
                   lambda job: pipeline.publish_to_app(job, body.race_ids))


@router.get('/generated/dates')
def generated_dates(request: Request):
    """ダッシュボードを作ってある日付（新しい順）。

    アプリ公開の日付選びに使う。「回顧待ちの日」から作ると、作り終えた
    とたんに候補から消えて公開できなくなるため、成果物の有無で決める。
    """
    _local_only(request)
    from ..services import catalog
    counts: dict = {}
    for r in catalog.list_races():
        if r.get('has_pred') or r.get('has_review'):
            counts[r['date']] = counts.get(r['date'], 0) + 1
    return {'dates': [{'date': d, 'races': counts[d]}
                      for d in sorted(counts, reverse=True)]}


@router.get('/app-publish/status')
def app_publish_status(request: Request, date: str):
    """その日の各レースが、サーバーに反映済みかどうか。

    同期ツールに聞く（判定の仕方を2箇所に持たないため）。
    サーバーに繋がらないときは空を返し、画面は「不明」として扱う。
    """
    _local_only(request)
    import json
    import subprocess
    import sys
    r = subprocess.run(
        [sys.executable, str(pipeline.SYNC_PY), '--status', date],
        capture_output=True, timeout=120)
    out = r.stdout.decode('utf-8', 'replace').strip()
    if r.returncode != 0 or not out:
        return {'date': date, 'available': False, 'races': {}}
    try:
        return {'date': date, 'available': True, 'races': json.loads(out)}
    except ValueError:
        return {'date': date, 'available': False, 'races': {}}


@router.post('/review-auto')
def run_review_auto(request: Request):
    """速報か確定かを自動で判断して、回顧をまとめて作る。"""
    _local_only(request)
    return _submit('回顧の作成（速報/確定を自動判定）',
                   lambda job: pipeline.build_reviews_auto(job))
