# -*- coding: utf-8 -*-
"""race_id の解析と、レース1件に紐づく成果物の場所を決める。

成果物の命名は既存パイプラインが決めているので、ここでは「探し方」だけを持つ。
実データには **3種類** の命名が混在しているので全部拾う（実測 2026-07-27）:
  新（現行）        20260726_sp9_pred.html                    … pred 167 / review 150
  中（旧バージョン） 20260530_kt12_C2_review.html              … pred  21 / review  55
                    20260620_hs11_Open_TenpouzanS_review.html
  旧（さらに前）    20260222_TK11R_G1_FeburariiS_pred.html    … pred  51 / review 160

中形式を拾えていないと「回顧が作られていない」と誤判定する（実際に6月分54レースを
未作成と誤って表示していた）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .. import config, legacy

RACE_ID_RE = re.compile(r'^(\d{8})_([A-Za-z]+)(\d{1,2})$')

# 旧命名の pred/review HTML: {YYYYMMDD}_{VENUE}{R}R_{クラス}_{レース名}_pred.html
LEGACY_HTML_RE = re.compile(r'^(\d{8})_([A-Z]+)(\d{1,2})R_.*_(pred|review)\.html$')

# 中間命名: {race_id}_{クラス}_{レース名}_pred.html（race_id で始まるが後ろに付属あり）
MIDDLE_HTML_RE = re.compile(r'^(\d{8}_[A-Za-z]+\d{1,2})_.+_(pred|review)\.html$')

# 旧命名で使われる会場コード（build_dashboard_v3._VENUE_CODE と同じ並び）
_LEGACY_VENUE_CODE = {
    '東京': 'TK', '阪神': 'HN', '京都': 'KY', '中山': 'NK',
    '中京': 'CK', '新潟': 'NG', '小倉': 'KK', '札幌': 'SP',
    '函館': 'HK', '福島': 'FK',
}


@dataclass(frozen=True)
class RaceKey:
    race_id: str
    date: str          # YYYYMMDD
    venue_code: str    # race_id 内の会場コード（元の大小文字）
    race_no: int
    venue: str | None  # 会場名（不明なら None）

    @property
    def is_jra(self) -> bool:
        return self.venue in jra_place_names()


# 公開サーバーには採点エンジンを置かない（pandas/numpy が要るうえ、
# 閲覧に採点機能は不要なため）。借りられないときはこの控えを使う。
_JRA_PLACE_FALLBACK = frozenset(
    ['札幌', '函館', '福島', '新潟', '東京', '中山', '中京', '京都', '阪神', '小倉'])


@lru_cache(maxsize=1)
def jra_place_names() -> frozenset:
    """JRA10場の会場名。既存 score_horse_v3.JRA_PLACE_NAMES を借りる。

    公開サーバーのように score_horse_v3.py が置かれていない環境では、
    上の控えを使う（JRAの10場は固定なので齟齬は生じない）。
    """
    import importlib
    import sys
    root = str(config.ROOT_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        mod = importlib.import_module('score_horse_v3')
    except Exception:
        return _JRA_PLACE_FALLBACK
    return frozenset(mod.JRA_PLACE_NAMES)


def parse_race_id(race_id: str) -> RaceKey | None:
    """'20260726_sp9' -> RaceKey。形式が違えば None。"""
    m = RACE_ID_RE.match((race_id or '').strip())
    if not m:
        return None
    date, code, no = m.group(1), m.group(2), m.group(3)
    return RaceKey(
        race_id=race_id,
        date=date,
        venue_code=code,
        race_no=int(no),
        venue=legacy.venue_from_race_id(race_id),
    )


# ── 成果物のパス ────────────────────────────────────────────────────
def horses_json(race_id: str):
    return config.OUT_DIR / f'horses_data_{race_id}.json'


def scores_csv(race_id: str):
    return config.OUT_DIR / f'scores_{race_id}.csv'


def review_done_marker(race_id: str):
    return config.OUT_DIR / f'{race_id}_review.done'


def smartrc_json(race_id: str):
    return config.OUT_DIR / f'smartrc_{race_id}.json'


def baba_json(race_id: str):
    return config.OUT_DIR / f'baba_{race_id}.json'


@lru_cache(maxsize=1)
def _html_index() -> tuple:
    """ルート直下のHTMLを1回だけ走査して、中間命名・旧命名を引けるようにする。

    戻り値: (中間命名 {(race_id, kind): Path}, 旧命名 {(date, venue, R, kind): Path})
    """
    middle: dict = {}
    legacy_idx: dict = {}
    for p in sorted(config.OUT_DIR.glob('*.html')):
        m = MIDDLE_HTML_RE.match(p.name)
        if m:
            middle.setdefault((m.group(1), m.group(2)), p)
            continue
        m = LEGACY_HTML_RE.match(p.name)
        if not m:
            continue
        date, code, no, kind = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        venue = legacy.venue_code_map().get(code)
        if venue is None:
            continue
        legacy_idx.setdefault((date, venue, no, kind), p)
    return middle, legacy_idx


def clear_html_index_cache() -> None:
    """HTMLを新規生成した後に呼ぶ（命名インデックスの作り直し）。"""
    _html_index.cache_clear()


def _find_html(race_id: str, kind: str):
    """kind は 'pred' か 'review'。新 → 中間 → 旧 の順に探す。"""
    p = config.OUT_DIR / f'{race_id}_{kind}.html'
    if p.exists():
        return p
    middle, legacy_idx = _html_index()
    hit = middle.get((race_id, kind))
    if hit is not None:
        return hit
    key = parse_race_id(race_id)
    if key is None or key.venue is None:
        return None
    return legacy_idx.get((key.date, key.venue, key.race_no, kind))


def pred_html(race_id: str):
    return _find_html(race_id, 'pred')


def review_html(race_id: str):
    return _find_html(race_id, 'review')


def input_files(race_id: str) -> dict:
    """入力CSVを input/ と input/done/ から探す。種別名 -> Path。

    input/ を優先（未処理＝これから生成する分）。
    """
    found: dict = {}
    for base in (config.INPUT_DIR, config.DONE_DIR):
        if not base.exists():
            continue
        for kind in legacy.input_kinds():
            if kind in found:
                continue
            for ext in ('.csv', '.xlsx', '.html', '.htm'):
                p = base / f'{kind}_{race_id}{ext}'
                if p.exists():
                    found[kind] = p
                    break
    return found
