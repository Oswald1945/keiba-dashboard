# -*- coding: utf-8 -*-
"""ゴールデン（回帰テストの基準データ）の共通処理。

make_golden.py（基準を作る）と test_*.py（基準と比べる）の両方から使う。
「1レースをどう再現するか」の手順はここ1か所だけに置く。
"""
from __future__ import annotations

import gzip
import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from app.backend import config                      # noqa: E402
from app.backend.services import paths, runner      # noqa: E402

GOLDEN_DIR = config.GOLDEN_DIR
MANIFEST_NAME = 'manifest.json'

KIND_KAKO = '過去走'
KIND_SHUTUBA = '出馬表'
KIND_SAKURO = '坂路'
KIND_WOOD = 'ウッド'
KIND_RESULT = 'レース結果'
KIND_RACEDATA = 'レースデータ'


# ── 小道具 ───────────────────────────────────────────────────────
def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(p: Path) -> str:
    return sha256_bytes(Path(p).read_bytes())


def write_gz(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(data, mtime=0))


def read_gz(path: Path) -> bytes:
    return gzip.decompress(Path(path).read_bytes())


def find_optional(name: str) -> Path | None:
    """ルート直下 → _archive の順で探す（既存の退避運用に合わせる）。"""
    for base in (config.OUT_DIR, config.ARCHIVE_DIR):
        p = base / name
        if p.exists():
            return p
    return None


# ── 外部依存（時間で変わりうるもの）の記録 ────────────────────────
def _result_venue_codes() -> dict:
    import importlib
    root = str(config.ROOT_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)
    return importlib.import_module('score_horse_v3')._RESULT_VENUE_CODES


_TB_MAX_BACK = 21   # score_horse_v3._TB_MAX_BACK と同じ意味（遡り上限日数）


def track_bias_sources(race_id: str, venue: str | None) -> dict:
    """トラックバイアス実測が読む input/done/レース結果_*.csv の候補一覧。

    score_horse_v3.measure_track_bias は input/done/ を直接見るため、
    done/ の中身が変わるとスコアが変わりうる。基準作成時の候補を記録し、
    テスト時に食い違ったら「基準の前提が変わった」と明示する。
    """
    key = paths.parse_race_id(race_id)
    if key is None or not venue:
        return {}
    codes = _result_venue_codes().get(str(venue).strip())
    if not codes:
        return {}
    race_int = int(key.date)
    rd = date(int(key.date[:4]), int(key.date[4:6]), int(key.date[6:8]))
    floor_int = int((rd - timedelta(days=_TB_MAX_BACK)).strftime('%Y%m%d'))

    found = {}
    if not config.DONE_DIR.exists():
        return {}
    for p in sorted(config.DONE_DIR.iterdir()):
        m = re.search(r'レース結果_(\d{8})_([A-Za-z]+)(\d+)\.(?:csv|html)$', p.name)
        if not m:
            continue
        di, code = int(m.group(1)), m.group(2).lower()
        if code not in codes or di >= race_int or di < floor_int:
            continue
        found[p.name] = sha256_file(p)
    return found


def effective_memo_hash(race_date_yyyymmdd: str) -> str:
    """このレースに効くメモ馬だけを取り出してハッシュ化する。

    memo_horses.json 全体を見ると、新しいレースのメモが増えるたびに
    過去レースの基準まで無効になってしまう。build_dashboard_v3 と同じ
    「元レース日付 < レース日付」の条件で絞ってから比べる。
    """
    try:
        memo_list = json.loads(config.MEMO_JSON.read_text(encoding='utf-8'))
    except Exception:
        memo_list = []

    def date_key(e):
        d = (e.get('元レース') or {}).get('日付', '')
        return d.replace('/', '') if d else ''

    eff = {}
    for e in memo_list:
        name = e.get('馬名', '')
        if not name:
            continue
        dk = date_key(e)
        if race_date_yyyymmdd and dk >= race_date_yyyymmdd:
            continue
        if name not in eff or dk > date_key(eff[name]):
            eff[name] = e
    blob = json.dumps([eff[k] for k in sorted(eff)], ensure_ascii=False, sort_keys=True)
    return sha256_bytes(blob.encode('utf-8'))


# ── 1レースの再現 ────────────────────────────────────────────────
@dataclass
class Reproduced:
    horses_data: bytes
    scores_csv: bytes
    pred_html: bytes | None
    review_html: bytes | None
    stdout: str
    review_error: str | None = None   # 回顧生成が既存コード側の理由で失敗した場合


def reproduce(race_id: str, case_dir: Path, manifest: dict, workdir: Path) -> Reproduced:
    """基準作成・テストの両方で使う「1レースを今のコードで作り直す」処理。

    workdir（一時フォルダ）にだけ書き出す。既存ルートには何も書かない。
    """
    workdir.mkdir(parents=True, exist_ok=True)
    inputs = case_dir / 'inputs'

    def inp(kind: str) -> Path | None:
        name = manifest['inputs'].get(kind)
        return (inputs / name) if name else None

    # memo_horses.json は --json と同じ場所から読まれる（メモ馬バッジ用）
    if config.MEMO_JSON.exists():
        shutil.copy2(config.MEMO_JSON, workdir / 'memo_horses.json')
    # 速報払戻キャッシュ（回顧で使う）
    hp = manifest.get('haraimodoshi')
    if hp and (inputs / hp).exists():
        shutil.copy2(inputs / hp, workdir / hp)

    smartrc = (inputs / manifest['smartrc']) if manifest.get('smartrc') else None
    baba_json = (inputs / manifest['baba_json']) if manifest.get('baba_json') else None

    r = runner.score_race(
        race_id=race_id,
        kako=inp(KIND_KAKO),
        shutuba=inp(KIND_SHUTUBA),
        outdir=workdir,
        baba=manifest['baba'],
        sakuro=inp(KIND_SAKURO),
        wood=inp(KIND_WOOD),
        smartrc=smartrc,
        baba_json=baba_json,
    ).raise_for_status()

    horses_json = r.outputs['horses_json']
    scores_csv = r.outputs['scores_csv']
    stdout = r.stdout

    rp = runner.build_pred(race_id, horses_json, workdir, baba_json=baba_json).raise_for_status()
    stdout += rp.stdout
    pred_html = rp.outputs.get('pred_html')

    review_html = None
    review_error = None
    result_file = inp(KIND_RESULT)
    if result_file is not None:
        rv = runner.build_review(
            race_id=race_id,
            result_file=result_file,
            horses_json=horses_json,
            scores_csv=scores_csv,
            outdir=workdir,
            racedata=inp(KIND_RACEDATA),
        )
        stdout += rv.stdout
        if rv.ok:
            review_html = rv.outputs.get('review_html')
        else:
            # 既存 build_review 側の失敗。採点の基準づくりまで止めない。
            # 何が起きたかは必ず残す（黙って無かったことにしない）。
            tail = (rv.stderr or '').strip().splitlines()
            review_error = tail[-1] if tail else f'returncode={rv.returncode}'

    return Reproduced(
        horses_data=Path(horses_json).read_bytes(),
        scores_csv=Path(scores_csv).read_bytes(),
        pred_html=Path(pred_html).read_bytes() if pred_html else None,
        review_html=Path(review_html).read_bytes() if review_html else None,
        stdout=stdout,
        review_error=review_error,
    )


def list_cases() -> list:
    """基準が作られているレースの一覧（race_id順）。"""
    if not GOLDEN_DIR.exists():
        return []
    out = []
    for d in sorted(GOLDEN_DIR.iterdir()):
        if d.is_dir() and (d / MANIFEST_NAME).exists():
            out.append(d)
    return out


def load_manifest(case_dir: Path) -> dict:
    return json.loads((case_dir / MANIFEST_NAME).read_text(encoding='utf-8'))
