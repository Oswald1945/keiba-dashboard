# -*- coding: utf-8 -*-
"""エクスポート → 採点/生成 → 確認 → 公開 の各ステップ。

方針はフェーズ1から変わらない: **既存スクリプトを無改造で、同じコマンドラインで呼ぶ。**
ここがやるのは「どのレースを対象にするか」を決めて順に渡すことだけ。

ハードコードされた run_review_today.bat / run_regen_today.bat の置き換えでもある
（あちらは日付・会場・レース番号がべた書きで、毎回手で書き換える必要があった）。
"""
from __future__ import annotations

import shutil
import sys

from .. import config
from . import jobs, paths, racedb

SMARTRC_PY = config.ROOT_DIR / 'smartrc_fetch.py'


# ── ② エクスポート ───────────────────────────────────────────────
def export_races(job: jobs.Job, targets: list) -> dict:
    """選んだレースを input/ に出す。targets = [{date, jyo, race_no}, ...]"""
    config.INPUT_DIR.mkdir(exist_ok=True)
    job.steps_total = len(targets)
    ok, ng = [], []
    for i, t in enumerate(targets, 1):
        date, jyo, rno = t['date'], t['jyo'], int(t['race_no'])
        venue = racedb.JYO.get(jyo, jyo)
        jobs.log(job, f'--- [{i}/{len(targets)}] {venue} {date} R{rno} をエクスポート ---')
        code = jobs.run_stream(job, [
            sys.executable, config.JV_EXPORT_PY,
            '--date', date, '--jyo', jyo, '--r', str(rno),
            '--outdir', str(config.INPUT_DIR),
        ], timeout=600)
        (ok if code == 0 else ng).append(f'{date}_{racedb.VENUE_ROMAJI.get(jyo, jyo)}{rno}')
        job.steps_done = i
        if job._cancel:
            jobs.log(job, '[中断] 残りのレースは処理していません。')
            break
    jobs.log(job, f'エクスポート完了: 成功 {len(ok)} / 失敗 {len(ng)}')
    if ng:
        jobs.log(job, f'  失敗: {", ".join(ng)}')
    job.result = {'exported': ok, 'failed': ng}
    return job.result


# ── ④ SmartRC ────────────────────────────────────────────────────
def fetch_smartrc(job: jobs.Job, targets: list) -> dict:
    """SmartRC を取得する。rcode は race.db から組み立てる。

    従来は races/view（不安定）で rcode を探していたが、rcode は
    YYYYMMDD+場+開催回+開催日+R で race.db だけから作れる。手入力は不要。
    """
    if not SMARTRC_PY.exists():
        raise RuntimeError(f'smartrc_fetch.py が見つかりません: {SMARTRC_PY}')
    job.steps_total = len(targets)
    ok, ng, skipped = [], [], []
    for i, t in enumerate(targets, 1):
        date, jyo, rno = t['date'], t['jyo'], int(t['race_no'])
        race_id = f'{date}_{racedb.VENUE_ROMAJI.get(jyo, jyo)}{rno}'
        out = paths.smartrc_json(race_id)
        if out.exists() and not t.get('force'):
            skipped.append(race_id)
            job.steps_done = i
            continue
        code_str = t.get('rcode') or racedb.rcode(date, jyo, rno)
        if not code_str:
            jobs.log(job, f'  [{race_id}] rcode を作れません（race.db に該当レースなし）')
            ng.append(race_id)
            job.steps_done = i
            continue
        jobs.log(job, f'--- [{i}/{len(targets)}] {race_id} rcode={code_str} ---')
        rc = jobs.run_stream(job, [
            sys.executable, SMARTRC_PY, '--rcode', code_str, '--out',
        ], timeout=120)
        # smartrc_fetch は race_id 名で出力する。生成されたかで成否を判定する。
        (ok if (rc == 0 and out.exists()) else ng).append(race_id)
        job.steps_done = i
        if job._cancel:
            jobs.log(job, '[中断] 残りのレースは処理していません。')
            break
    jobs.log(job, f'SmartRC: 取得 {len(ok)} / 失敗 {len(ng)} / 既存のためスキップ {len(skipped)}')
    if ng:
        jobs.log(job, f'  失敗: {", ".join(ng)}')
    job.result = {'fetched': ok, 'failed': ng, 'skipped': skipped}
    return job.result


# ── ⑤ 採点・予想生成（公開はしない） ─────────────────────────────
def build_predictions(job: jobs.Job, force: bool = False) -> dict:
    """input/ にあるレースを採点して予想HTMLを作る。**公開はしない。**"""
    cmd = [sys.executable, config.RUN_NEW_PY, '--no-publish', '--no-browser']
    if force:
        cmd.append('--force')
    jobs.log(job, '[生成] 採点 → 予想ダッシュボード（公開はしません）')
    code = jobs.run_stream(job, cmd, timeout=7200)
    if code != 0:
        raise RuntimeError(f'予想の生成に失敗しました (code={code})')
    paths.clear_html_index_cache()
    return {'returncode': code}


# ── ⑦ 回顧生成 ───────────────────────────────────────────────────
def build_reviews(job: jobs.Job, targets: list, force: bool = True) -> dict:
    """結果込みで再エクスポートしてから回顧を作る。**公開はしない。**

    run_review_today.bat がやっていたことと同じだが、日付・会場・レース番号は
    画面で選んだものを使う（バッチのべた書きを置き換える）。
    """
    if targets:
        jobs.log(job, f'[回顧] 結果込みで {len(targets)} レースを再エクスポートします')
        export_races(job, targets)
        if job._cancel:
            return {'cancelled': True}

    cmd = [sys.executable, config.RUN_NEW_PY, '--review', '--no-publish', '--no-browser']
    if force:
        cmd.append('--force')
    jobs.log(job, '[回顧] 回顧ダッシュボードを生成します（公開はしません）')
    code = jobs.run_stream(job, cmd, timeout=7200)
    if code != 0:
        raise RuntimeError(f'回顧の生成に失敗しました (code={code})')
    paths.clear_html_index_cache()
    return {'returncode': code}


# ── 公開 ─────────────────────────────────────────────────────────
def publish(job: jobs.Job, race_ids: list) -> dict:
    """確認済みのHTMLを GitHub Pages へ公開する。"""
    if not race_ids:
        raise ValueError('公開するレースが選ばれていません')
    jobs.log(job, f'[公開] {len(race_ids)} レースを公開します')
    code = jobs.run_stream(job, [
        sys.executable, config.RUN_NEW_PY, '--publish', *race_ids,
    ], timeout=1800)
    if code != 0:
        raise RuntimeError(f'公開に失敗しました (code={code})')
    return {'published': race_ids}


# ── 検証データの作り直し（現行スコアラーで5年分を採点し直す） ────
FACTOR_BACKTEST_PY = config.ROOT_DIR / 'factor_backtest.py'


def rescore_factors(job: jobs.Job, date_from: str, date_to: str,
                    out_file: str = 'factor_rows_p4.jsonl') -> dict:
    """検証用の5年データを、いまの採点ロジックで作り直す。

    P4（成績重み付きコース適性）のように採点ロジックを変えると、既存の
    factor_rows_*.jsonl は古い世代のままになる。これを走らせて初めて
    検証画面が現行モデルの成績を表すようになる。

    既存の factor_rows.jsonl / factor_rows_p3.jsonl は**上書きしない**（別ファイル）。
    途中で止めても、もう一度実行すれば続きから再開する（resumable）。
    実測 約2.8秒/レース → 5年16,048レースで約12.7時間。
    """
    if not FACTOR_BACKTEST_PY.exists():
        raise RuntimeError(f'factor_backtest.py が見つかりません: {FACTOR_BACKTEST_PY}')
    out_path = config.ROOT_DIR / out_file
    done = 0
    if out_path.exists():
        with open(out_path, encoding='utf-8') as fh:
            done = len({__import__('json').loads(x).get('rid') for x in fh if x.strip()})
        jobs.log(job, f'[再採点] 既に {done} レース分あります。続きから再開します。')

    jobs.log(job, f'[再採点] {date_from} 〜 {date_to} を現行スコアラーで採点し直します')
    jobs.log(job, f'[再採点] 出力先: {out_file}（既存の factor_rows*.jsonl は変更しません）')
    jobs.log(job, '[再採点] 5年分はおおよそ12〜13時間かかります。途中で止めても再開できます。')

    code = jobs.run_stream(job, [
        sys.executable, FACTOR_BACKTEST_PY,
        '--from', date_from, '--to', date_to, '--limit', '0',
        '--out', str(out_path),
    ], timeout=None)

    if code != 0 and not job._cancel:
        raise RuntimeError(f'再採点に失敗しました (code={code})')

    total = 0
    if out_path.exists():
        with open(out_path, encoding='utf-8') as fh:
            total = len({__import__('json').loads(x).get('rid') for x in fh if x.strip()})
    jobs.log(job, f'[再採点] 現在 {total} レース分（今回 +{total - done}）')

    # 検証画面が新しいファイルを読み直せるようにする
    from . import validation
    validation.reset_cache()
    return {'out': out_file, 'races': total, 'added': total - done}


# ── 入力の巻き戻し（回顧のため done/ から input/ へ戻す） ────────
def restore_inputs(job: jobs.Job, race_ids: list) -> dict:
    """done/ にある入力CSVを input/ に戻す（再生成用）。move ではなく copy はしない。"""
    moved, missing = [], []
    for rid in race_ids:
        found = False
        for p in sorted(config.DONE_DIR.glob(f'*_{rid}.*')):
            dest = config.INPUT_DIR / p.name
            if not dest.exists():
                shutil.move(str(p), str(dest))
            found = True
        (moved if found else missing).append(rid)
    jobs.log(job, f'[戻し] input/ に戻したレース: {len(moved)}')
    if missing:
        jobs.log(job, f'  done/ に入力が無いレース: {", ".join(missing)}')
    return {'restored': moved, 'missing': missing}
