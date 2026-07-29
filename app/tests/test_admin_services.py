# -*- coding: utf-8 -*-
"""管理まわりのサービス（race.db読み取り・馬場保存・ジョブ実行）。"""
from __future__ import annotations

import json
import sys
import time

import pytest

from app.backend.services import baba_store, jobs, racedb

# ── race.db（このPCにある実DBを読むだけ。書き込みはしない） ──────
needs_db = pytest.mark.skipif(
    not racedb.DB_PATH.exists(),
    reason='race.db が見つかりません（このPC以外では実行しません）',
)


@needs_db
def test_rcode_matches_smartrc_format():
    """rcode = YYYYMMDD + 場(2) + 開催回(2) + 開催日(2) + R(2)。

    実機のSmartRC画面で確認した 2026/07/25 札幌7R の値と一致すること。
    ここが合っていれば rcode を手で調べる必要がなくなる。
    """
    got = racedb.rcode('20260725', '01', 7)
    assert got == '2026072501010107'
    assert len(got) == 16


@needs_db
def test_rcode_returns_none_for_unknown_race():
    assert racedb.rcode('20991231', '01', 1) is None


@needs_db
def test_predictable_races_shape():
    groups = racedb.predictable_races()
    if not groups:
        pytest.skip('いま予想できるレースがありません')
    g = groups[0]
    assert set(g) >= {'date', 'jyo', 'venue', 'kaiji', 'nichiji', 'races'}
    assert g['venue'] in racedb.JYO.values()
    r = g['races'][0]
    assert set(r) >= {'race_no', 'race_id', 'race_class', 'is_maiden', 'rcode'}
    assert r['rcode'].startswith(g['date'])
    # 新馬・未勝利のフラグがクラス表記と矛盾しないこと
    for race in g['races']:
        assert race['is_maiden'] == (race['race_class'] in ('新馬', '未勝利'))


@needs_db
def test_result_status_counts_confirmed():
    st = racedb.result_status('20260725')
    assert st['date'] == '20260725'
    assert st['total'] == len(st['races'])
    assert st['confirmed'] <= st['total']
    for r in st['races']:
        assert r['state'] in ('確定', '一部', '未確定')


# ── 馬場の保存 ───────────────────────────────────────────────────
@pytest.fixture
def baba_file(tmp_path, monkeypatch):
    p = tmp_path / 'baba_manual.json'
    p.write_text(json.dumps({
        '_注意': 'これは残らないといけない',
        '20260725': {'新潟': {'芝': '稍重', 'ダート': '重'}},
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    monkeypatch.setattr(baba_store.config, 'BABA_MANUAL_JSON', p)
    monkeypatch.setattr(baba_store.config, 'BACKUP_DIR', tmp_path / 'backups')
    return p


def test_save_keeps_other_dates_and_note(baba_file):
    baba_store.save('20260726', {'新潟': {'芝': '良', 'ダート': '稍重', 'クッション値': 9.6}})
    data = json.loads(baba_file.read_text(encoding='utf-8'))
    assert '_注意' in data, '注意書きを消してはいけない'
    assert data['20260725']['新潟']['芝'] == '稍重', '別日付を消してはいけない'
    assert data['20260726']['新潟'] == {'芝': '良', 'ダート': '稍重', 'クッション値': 9.6}


def test_save_rejects_invalid_going(baba_file):
    with pytest.raises(ValueError):
        baba_store.save('20260726', {'新潟': {'芝': 'やや重'}})   # 表記ゆれは受け付けない
    with pytest.raises(ValueError):
        baba_store.save('20260726', {'新潟': {'天候': '曇'}})     # 芝もダートも無い
    with pytest.raises(ValueError):
        baba_store.save('2026726', {'新潟': {'芝': '良'}})        # 日付の桁数


def test_save_rejects_non_numeric_cushion(baba_file):
    with pytest.raises(ValueError):
        baba_store.save('20260726', {'新潟': {'芝': '良', 'クッション値': 'かたい'}})


def test_save_makes_backup(baba_file, tmp_path):
    baba_store.save('20260726', {'新潟': {'芝': '良'}})
    backups = list((tmp_path / 'backups').glob('baba_manual_*.json'))
    assert backups, '上書き前の退避が作られていない'
    old = json.loads(backups[0].read_text(encoding='utf-8'))
    assert '20260726' not in old


def test_get_returns_empty_for_unknown_date(baba_file):
    assert baba_store.get('20990101') == {}


# ── ジョブ実行 ───────────────────────────────────────────────────
def test_jobs_run_one_at_a_time():
    """採点は固定名の中間ファイルを使うので、並行実行させてはいけない。"""
    runner = jobs.JobRunner()
    order = []

    def make(tag):
        def fn(job):
            order.append(f'{tag}-start')
            time.sleep(0.15)
            order.append(f'{tag}-end')
        return fn

    a = runner.submit('A', make('a'))
    b = runner.submit('B', make('b'))
    for _ in range(100):
        if a.status in ('ok', 'error') and b.status in ('ok', 'error'):
            break
        time.sleep(0.05)
    assert a.status == 'ok' and b.status == 'ok'
    assert order == ['a-start', 'a-end', 'b-start', 'b-end'], '直列に実行されていない'


def test_job_captures_output_lines():
    runner = jobs.JobRunner()
    job = runner.submit('echo', lambda j: jobs.run_stream(
        j, [sys.executable, '-c', 'print("いち"); print("に")']))
    for _ in range(100):
        if job.status in ('ok', 'error'):
            break
        time.sleep(0.05)
    assert job.status == 'ok'
    assert 'いち' in job.lines and 'に' in job.lines


def test_job_records_error():
    runner = jobs.JobRunner()

    def boom(job):
        raise RuntimeError('わざと失敗')

    job = runner.submit('fail', boom)
    for _ in range(100):
        if job.status in ('ok', 'error'):
            break
        time.sleep(0.05)
    assert job.status == 'error'
    assert 'わざと失敗' in (job.error or '')


def test_job_public_returns_lines_after_offset():
    runner = jobs.JobRunner()
    job = runner.submit('lines', lambda j: [jobs.log(j, f'line{i}') for i in range(5)])
    for _ in range(100):
        if job.status in ('ok', 'error'):
            break
        time.sleep(0.05)
    assert job.public(after=0)['lines'] == [f'line{i}' for i in range(5)]
    assert job.public(after=3)['lines'] == ['line3', 'line4']
