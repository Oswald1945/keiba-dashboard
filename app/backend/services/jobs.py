# -*- coding: utf-8 -*-
"""管理ジョブの実行基盤。

守ること:
  - **必ず1本ずつ直列に実行する。** 採点は固定名の中間ファイル
    (horses_data.json / scores.csv) を経由するため、並行させると壊れる。
  - 出力は1行ずつ溜めて画面に流す（どのレースで止まったかが分かるように）。
  - 中断できる。長い処理を押し間違えたときに待たされない。
"""
from __future__ import annotations

import itertools
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

from .. import config

JST = timezone(timedelta(hours=9))
_ids = itertools.count(1)


@dataclass
class Job:
    id: str
    name: str
    status: str = 'queued'          # queued / running / ok / error / cancelled
    lines: list = field(default_factory=list)
    started_at: str | None = None
    ended_at: str | None = None
    error: str | None = None
    result: dict = field(default_factory=dict)
    steps_done: int = 0
    steps_total: int = 0
    _proc: subprocess.Popen | None = None
    _cancel: bool = False

    def public(self, after: int = 0) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'status': self.status,
            'started_at': self.started_at,
            'ended_at': self.ended_at,
            'error': self.error,
            'result': self.result,
            'steps_done': self.steps_done,
            'steps_total': self.steps_total,
            'line_count': len(self.lines),
            'lines': self.lines[after:],
        }


class JobRunner:
    """ジョブを1本ずつ順に実行する。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._current: Job | None = None
        self._worker: threading.Thread | None = None
        self._queue: list[tuple[Job, Callable]] = []

    # ── 参照 ──────────────────────────────────────────────
    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def current(self) -> Job | None:
        return self._current

    def recent(self, limit: int = 20) -> list:
        """最近のジョブの概要（ログ本文は含めない）。"""
        with self._lock:
            ids = self._order[-limit:][::-1]
        return [self._jobs[i].public(after=len(self._jobs[i].lines)) for i in ids]

    def busy(self) -> bool:
        return self._current is not None and self._current.status == 'running'

    # ── 実行 ──────────────────────────────────────────────
    def submit(self, name: str, fn: Callable) -> Job:
        """fn(job) を直列キューに積む。fn は job.log(...) で進捗を書ける。"""
        job = Job(id=f'j{next(_ids)}', name=name)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._queue.append((job, fn))
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._loop, daemon=True)
                self._worker.start()
        return job

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status not in ('queued', 'running'):
            return False
        job._cancel = True
        if job._proc and job._proc.poll() is None:
            try:
                job._proc.terminate()
            except Exception:
                pass
        if job.status == 'queued':
            job.status = 'cancelled'
            job.ended_at = _now()
        return True

    def _loop(self):
        while True:
            with self._lock:
                if not self._queue:
                    self._worker = None
                    self._current = None
                    return
                job, fn = self._queue.pop(0)
            if job.status == 'cancelled':
                continue
            self._current = job
            job.status = 'running'
            job.started_at = _now()
            try:
                fn(job)
                if job._cancel:
                    job.status = 'cancelled'
                elif job.status == 'running':
                    job.status = 'ok'
            except Exception as e:
                job.status = 'error'
                job.error = f'{type(e).__name__}: {e}'
                job.lines.append(f'[エラー] {job.error}')
            finally:
                job.ended_at = _now()
                job._proc = None


def _now() -> str:
    return datetime.now(JST).isoformat(timespec='seconds')


# ── Job のヘルパ（実行関数から使う） ──────────────────────────
def log(job: Job, text: str) -> None:
    for line in str(text).splitlines() or ['']:
        job.lines.append(line)


def run_stream(job: Job, cmd: list, cwd=None, timeout: int | None = None) -> int:
    """子プロセスを起動し、出力を1行ずつ job に流す。戻り値は終了コード。"""
    log(job, f'$ {" ".join(str(c) for c in cmd)}')
    proc = subprocess.Popen(
        [str(c) for c in cmd],
        cwd=str(cwd or config.ROOT_DIR),
        env=config.child_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    job._proc = proc
    deadline = (time.time() + timeout) if timeout else None
    assert proc.stdout is not None
    for raw in proc.stdout:
        job.lines.append(raw.decode('utf-8', errors='replace').rstrip('\r\n'))
        if job._cancel:
            proc.terminate()
            log(job, '[中断] 実行を止めました。')
            break
        if deadline and time.time() > deadline:
            proc.terminate()
            log(job, '[中断] 時間切れで止めました。')
            break
    proc.wait()
    job._proc = None
    return proc.returncode


# アプリ全体で1つだけ使う
runner = JobRunner()
