# -*- coding: utf-8 -*-
"""EVパリティテスト。

移植した app/frontend/src/ev/evCore.js が、既存 pred.html に埋め込まれている
JavaScript と「同じ入力に対して同じ結果」を出すことを確認する。

比べるもの:
  - 単勝/複勝の勝率・EV（全馬）
  - オッズ入力欄の初期値（採算オッズ）
  - 買い目の軸（勝率cap後1位）
  - 購入推奨/非推奨とその理由の文言
  - 券種ごとの点数・的中率・合成採算オッズ・買い目
  - 内訳（1点ずつ）の全行

重要:
  ルート直下にある古い pred.html は、当時の build_dashboard_v3.py で作られており
  現行版と実装が違う（実測: 2026-07-17以前のものは買い目パネルの仕様が別物）。
  そのため参照HTMLは必ず「今のコードで作り直したもの」を使う。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.backend import config
from app.backend.services import runner
from app.tests import golden_lib as gl

CASES = gl.list_cases()

pytestmark = pytest.mark.skipif(
    not CASES,
    reason='基準データがありません。先に run_make_golden.bat を実行してください。',
)

PARITY_JS = config.TESTS_DIR / 'ev_parity.mjs'


def _node_available() -> bool:
    try:
        subprocess.run(['node', '--version'], capture_output=True, timeout=30, check=True)
        return True
    except Exception:
        return False


@pytest.fixture(scope='module')
def generated_preds(tmp_path_factory) -> list:
    """基準の horses_data から、今のコードで pred.html を作り直す。

    採点はやり直さない（基準の採点結果をそのまま使う）ので速い。
    """
    work = tmp_path_factory.mktemp('parity')
    if config.MEMO_JSON.exists():
        shutil.copy2(config.MEMO_JSON, work / 'memo_horses.json')

    made = []
    for case_dir in CASES:
        manifest = gl.load_manifest(case_dir)
        race_id = manifest['race_id']
        hj = work / f'horses_data_{race_id}.json'
        hj.write_bytes(gl.read_gz(case_dir / 'expected' / 'horses_data.json.gz'))

        baba_json = None
        if manifest.get('baba_json'):
            src = case_dir / 'inputs' / manifest['baba_json']
            if src.exists():
                baba_json = work / manifest['baba_json']
                shutil.copy2(src, baba_json)

        res = runner.build_pred(race_id, hj, work, baba_json=baba_json)
        assert res.ok, f'{race_id}: 予想HTMLを生成できません\n{res.stderr[-1500:]}'
        made.append(res.outputs['pred_html'])
    return made


def test_node_is_available():
    assert _node_available(), (
        'Node.js が見つかりません。EVパリティ検証には Node.js が必要です。'
    )


def test_ev_core_matches_existing_dashboard(generated_preds, tmp_path):
    assert PARITY_JS.exists(), f'検証スクリプトがありません: {PARITY_JS}'

    # 引数が長くなりすぎないよう、ファイル一覧を分割して渡す
    failures = []
    total = 0
    version = None
    chunk = 25
    for i in range(0, len(generated_preds), chunk):
        args = ['node', str(PARITY_JS)] + [str(p) for p in generated_preds[i:i + chunk]]
        proc = subprocess.run(args, capture_output=True, cwd=str(config.ROOT_DIR))
        out = (proc.stdout or b'').decode('utf-8', errors='replace')
        err = (proc.stderr or b'').decode('utf-8', errors='replace')
        assert out.strip(), f'検証スクリプトが結果を返しませんでした\n{err[-2000:]}'
        data = json.loads(out)
        version = data['ev_core_version']
        total += data['total']
        failures += [r for r in data['results'] if not r['ok']]

    if failures:
        lines = [f'EV計算が既存ダッシュボードと一致しません（{len(failures)}/{total} レース、'
                 f'ロジック版 {version}）']
        for r in failures[:5]:
            lines.append(f'  [{r["race_id"]}]')
            for d in r['diffs'][:6]:
                lines.append(f'    - {d}')
        if len(failures) > 5:
            lines.append(f'  ... 他 {len(failures) - 5} レース')
        pytest.fail('\n'.join(lines))

    assert total == len(CASES)
