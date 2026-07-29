# -*- coding: utf-8 -*-
"""既存スクリプトを「無改造のまま」子プロセスとして呼ぶ共通ラッパ。

方針（重要）:
  採点ロジックをアプリ側に書き写さない。run_new.py が組み立てているのと
  同じコマンドライン・同じ順序で python を起動するだけにする。
  これで「アプリ経由の結果＝現行バッチの結果」が構造的に保証される。

score_horse_v3.py は --outdir に固定名 horses_data.json / scores.csv を
出力してから run_new.py がレース別名にコピーしている。その手順もそのまま
再現する（＝複数レースを同時に走らせると壊れる。呼び出し側で直列化すること）。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .. import config


@dataclass
class RunResult:
    ok: bool
    returncode: int
    cmd: list
    stdout: str = ''
    stderr: str = ''
    outputs: dict = field(default_factory=dict)

    def raise_for_status(self) -> 'RunResult':
        if not self.ok:
            raise RuntimeError(
                f'既存スクリプトの実行に失敗しました (code={self.returncode})\n'
                f'コマンド: {" ".join(str(c) for c in self.cmd)}\n'
                f'--- 標準出力 ---\n{self.stdout[-4000:]}\n'
                f'--- 標準エラー ---\n{self.stderr[-4000:]}'
            )
        return self


def _run(cmd: list, timeout: int | None = None) -> RunResult:
    proc = subprocess.run(
        [str(c) for c in cmd],
        cwd=str(config.ROOT_DIR),
        env=config.child_env(),
        capture_output=True,
        timeout=timeout,
    )
    return RunResult(
        ok=(proc.returncode == 0),
        returncode=proc.returncode,
        cmd=cmd,
        stdout=(proc.stdout or b'').decode('utf-8', errors='replace'),
        stderr=(proc.stderr or b'').decode('utf-8', errors='replace'),
    )


def score_race(
    race_id: str,
    kako: Path,
    shutuba: Path,
    outdir: Path,
    baba: str = '良',
    sakuro: Path | None = None,
    wood: Path | None = None,
    smartrc: Path | None = None,
    baba_json: Path | None = None,
    timeout: int | None = 900,
) -> RunResult:
    """採点（score_horse_v3.py）。run_new.process_race と同じ引数構成。"""
    cmd = [sys.executable, config.SCORE_PY,
           '--excel', kako, '--shutuba', shutuba, '--outdir', outdir,
           '--baba', baba]
    if sakuro:
        cmd += ['--sakuro', sakuro]
    if wood:
        cmd += ['--wood', wood]
    if smartrc:
        cmd += ['--smartrc', smartrc]
    if baba_json:
        cmd += ['--baba-json', str(baba_json)]

    result = _run(cmd, timeout=timeout)
    if not result.ok:
        return result

    # run_new.py と同じ後始末: 固定名 -> レース別名にコピーして固定名を消す
    outdir = Path(outdir)
    src_json = outdir / 'horses_data.json'
    src_scores = outdir / 'scores.csv'
    dst_json = outdir / f'horses_data_{race_id}.json'
    dst_scores = outdir / f'scores_{race_id}.csv'
    if src_json.exists():
        shutil.copy2(src_json, dst_json)
        src_json.unlink()
        result.outputs['horses_json'] = dst_json
    if src_scores.exists():
        shutil.copy2(src_scores, dst_scores)
        src_scores.unlink()
        result.outputs['scores_csv'] = dst_scores
    return result


def build_pred(
    race_id: str,
    horses_json: Path,
    outdir: Path,
    baba_json: Path | None = None,
    timeout: int | None = 600,
) -> RunResult:
    """予想ダッシュボード生成（build_dashboard_v3.py）。

    出力名は build_dashboard_v3 側が --json のファイル名から決める
    （horses_data_{race_id}.json -> {race_id}_pred.html）。
    メモ馬バッジは --json と同じフォルダの memo_horses.json を読むので、
    一時フォルダで動かす場合は呼び出し側でコピーしておくこと。
    """
    cmd = [sys.executable, config.DASH_PY, '--json', horses_json, '--outdir', outdir]
    if baba_json:
        cmd += ['--baba-json', str(baba_json)]
    result = _run(cmd, timeout=timeout)
    if result.ok:
        p = Path(outdir) / f'{race_id}_pred.html'
        if p.exists():
            result.outputs['pred_html'] = p
    return result


def build_review(
    race_id: str,
    result_file: Path,
    horses_json: Path,
    scores_csv: Path,
    outdir: Path,
    racedata: Path | None = None,
    timeout: int | None = 600,
) -> RunResult:
    """回顧ダッシュボード生成（build_review.py）。"""
    cmd = [sys.executable, config.REVIEW_PY,
           '--result', result_file, '--horses', horses_json,
           '--scores', scores_csv, '--outdir', outdir]
    if racedata:
        cmd += ['--racedata', racedata]
    res = _run(cmd, timeout=timeout)
    if res.ok:
        for p in Path(outdir).glob('*_review.html'):
            res.outputs['review_html'] = p
            break
    return res
