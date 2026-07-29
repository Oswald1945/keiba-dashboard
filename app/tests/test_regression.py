# -*- coding: utf-8 -*-
"""採点数値の回帰テスト。

基準（app/tests/golden/）は make_golden.py が「そのときのコード」で作った出力。
このテストは同じ入力を今のコードで作り直し、1つでも数値が変わっていないかを見る。

見ているもの:
  1. horses_data.json  … 16因子pts・総合スコア・順位予想・地方フラグ 等すべて
  2. scores.csv        … ダッシュボード外で使う採点表
  3. pred/review HTML  … 生成物が同一か（ハッシュ）
  4. EV_DATA           … アプリのEV APIが既存HTML埋め込みと同一か

前提が変わった場合（input/done/ の結果CSVが動いた、メモ馬が変わった）は
不一致ではなく「前提が変わった」とはっきり出す。都合よく合わせにいかない。
"""
from __future__ import annotations

import gzip
import json
import re
from pathlib import Path

import pytest

from app.backend.services import ev
from app.tests import diffutil
from app.tests import golden_lib as gl

CASES = gl.list_cases()

pytestmark = pytest.mark.skipif(
    not CASES,
    reason='基準データがありません。先に run_make_golden.bat を実行してください。',
)


def _ids(p: Path) -> str:
    return p.name


@pytest.fixture(scope='module')
def _memo_now():
    return gl.effective_memo_hash


def _check_premises(manifest: dict):
    """基準作成時と外部依存が変わっていないか。戻り値: (採点に影響, HTMLに影響)。"""
    score_broken = []
    for name, sha in (manifest.get('track_bias_sources') or {}).items():
        p = gl.config.DONE_DIR / name
        if not p.exists():
            score_broken.append(f'{name} が input/done/ から無くなっている')
        elif gl.sha256_file(p) != sha:
            score_broken.append(f'{name} の中身が変わっている')

    html_broken = None
    now = gl.effective_memo_hash(manifest['date'])
    if now != manifest.get('effective_memo_sha256'):
        html_broken = 'memo_horses.json のうちこのレースに効く分が変わっている'
    return score_broken, html_broken


@pytest.mark.parametrize('case_dir', CASES, ids=_ids)
def test_race_regression(case_dir: Path, tmp_path: Path):
    manifest = gl.load_manifest(case_dir)
    race_id = manifest['race_id']

    score_broken, html_broken = _check_premises(manifest)
    if score_broken:
        pytest.skip(
            f'{race_id}: 基準作成時の前提が変わったため判定できません（コードの問題ではない）\n'
            + '\n'.join(f'  - {m}' for m in score_broken)
            + '\n  → run_make_golden.bat --force で基準を作り直してください'
        )

    rep = gl.reproduce(race_id, case_dir, manifest, tmp_path / 'work')
    exp_dir = case_dir / 'expected'

    # 1) horses_data.json（採点数値の本体）
    expected = json.loads(gl.read_gz(exp_dir / 'horses_data.json.gz').decode('utf-8'))
    actual = json.loads(rep.horses_data.decode('utf-8'))
    rows = diffutil.diff(expected, actual, path=race_id)
    assert not rows, f'{race_id}: 採点結果が基準と違います\n{diffutil.format_diff(rows)}'

    # 2) scores.csv
    exp_csv = gl.read_gz(exp_dir / 'scores.csv.gz').decode('utf-8-sig').splitlines()
    act_csv = rep.scores_csv.decode('utf-8-sig').splitlines()
    assert exp_csv == act_csv, (
        f'{race_id}: scores.csv が基準と違います\n'
        + '\n'.join(f'  基準: {e}\n  今回: {a}'
                    for e, a in zip(exp_csv, act_csv) if e != a)[:2000]
    )

    # 3) EV_DATA（アプリのEV APIと既存HTML埋め込みの一致）
    assert rep.pred_html is not None, f'{race_id}: 予想HTMLが生成されませんでした'
    html = rep.pred_html.decode('utf-8')
    m = re.search(r'const EV_DATA = (\[.*?\]);', html, re.S)
    assert m, f'{race_id}: 予想HTMLから EV_DATA を取り出せませんでした'
    embedded = json.loads(m.group(1))
    api_rows = ev.ev_data_from(actual)
    ev_rows = diffutil.diff(embedded, api_rows, path=f'{race_id}/EV_DATA')
    assert not ev_rows, (
        f'{race_id}: EV APIの出力が予想HTML内の EV_DATA と違います\n'
        f'{diffutil.format_diff(ev_rows)}'
    )

    # 4) 生成HTMLのハッシュ
    digests = json.loads((exp_dir / 'digests.json').read_text(encoding='utf-8'))
    if html_broken:
        pytest.skip(f'{race_id}: 数値は一致。HTMLの比較のみ見送り（{html_broken}）')
    if 'pred_html_sha256' in digests:
        assert gl.sha256_bytes(rep.pred_html) == digests['pred_html_sha256'], (
            f'{race_id}: 予想ダッシュボードHTMLが基準と違います '
            f'(基準 {digests["pred_html_bytes"]}バイト / 今回 {len(rep.pred_html)}バイト)'
        )
    if 'review_html_sha256' in digests:
        assert rep.review_html is not None, (
            f'{race_id}: 基準では作れていた回顧HTMLが生成されませんでした'
            + (f'（{rep.review_error}）' if rep.review_error else '')
        )
        assert gl.sha256_bytes(rep.review_html) == digests['review_html_sha256'], (
            f'{race_id}: 回顧ダッシュボードHTMLが基準と違います '
            f'(基準 {digests["review_html_bytes"]}バイト / 今回 {len(rep.review_html)}バイト)'
        )
    elif manifest.get('review_error') and rep.review_html is not None:
        # 基準作成時は作れなかった回顧が作れるようになった＝既存側が直った合図
        pytest.skip(
            f'{race_id}: 基準作成時は回顧を生成できませんでしたが、今回は生成できました。'
            f'\n  基準時のエラー: {manifest["review_error"][:200]}'
            f'\n  → run_make_golden.bat --force で基準を作り直してください'
        )


def test_golden_covers_edge_cases():
    """基準に端ケースが入っているか（入っていないと回帰を見逃す）。"""
    traits = [gl.load_manifest(d).get('traits', {}) for d in CASES]
    for key, label in (
        ('has_local_only', '地方実績のみの馬を含むレース'),
        ('has_result', 'レース結果あり（回顧を検証できる）'),
        ('wide_top_odds', 'スコア1位が人気薄（勝率capで軸が動く）'),
    ):
        n = sum(1 for t in traits if t.get(key))
        assert n > 0, f'基準に「{label}」が1件もありません'
