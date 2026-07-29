# -*- coding: utf-8 -*-
"""EV（妙味）判定の「素材」を返す。

計算そのもの（softmax・勝率cap MR=3.0・地方馬除外・採算オッズ）は
既存 pred.html の JavaScript が持っている。サーバ側で計算し直すと
同じロジックが2か所に増えて必ずズレるので、ここでは計算しない。

ここが返すのは build_dashboard_v3.py の EV_DATA と同じ形の配列。
フロントは既存JSを移植した計算をこの配列に対して行う。
中身が本当に同じであることは tests/test_ev_data_parity.py で
既存 pred.html に埋め込まれた EV_DATA と突き合わせて検証する。
"""
from __future__ import annotations

import json

from .. import config
from . import paths


def _memo_map(race_date_yyyymmdd: str) -> dict:
    """build_dashboard_v3.py と同じ条件のメモ馬マップ。

    条件: 元レース日付 < 当該レース日付（同日・未来は除外）。
    同一馬が複数あるときは元レース日付が新しい方を採用。
    """
    try:
        with open(config.MEMO_JSON, encoding='utf-8') as f:
            memo_list = json.load(f)
    except Exception:
        memo_list = []

    def date_key(entry):
        d = (entry.get('元レース') or {}).get('日付', '')
        return d.replace('/', '') if d else ''

    result: dict = {}
    for e in memo_list:
        name = e.get('馬名', '')
        if not name:
            continue
        dk = date_key(e)
        if race_date_yyyymmdd and dk >= race_date_yyyymmdd:
            continue
        if name not in result or dk > date_key(result[name]):
            result[name] = e
    return result


def _date_prefix(meta: dict) -> str:
    ri = meta.get('race_info') or {}
    try:
        y = int(float(ri.get('年')))
        m = int(float(ri.get('月')))
        d = int(float(ri.get('日')))
    except (TypeError, ValueError):
        return ''
    return f'{y:04d}{m:02d}{d:02d}'


def ev_data(race_id: str) -> list | None:
    """race_id の EV_DATA 相当を返す。採点前なら None。"""
    jp = paths.horses_json(race_id)
    if not jp.exists():
        return None
    return ev_data_from(json.loads(jp.read_text(encoding='utf-8')))


def ev_data_from(data: dict) -> list:
    """horses_data.json の中身から EV_DATA 相当を組み立てる。

    ファイルの場所に依存しないので、回帰テストから基準データを直接渡せる。
    """
    horses = data.get('horses') or []
    meta = data.get('meta') or {}
    memo = _memo_map(_date_prefix(meta))
    n = len(horses)

    rows = []
    for h in horses:
        if h.get('過去走なし', False):
            continue          # 過去走なしは softmax を歪めるため既存も除外
        rc = h.get('SmartRC推定人気順')
        rows.append({
            '馬名': h['馬名'],
            '馬番': h.get('馬番'),
            '枠番': h.get('枠番'),
            'スコア': h['総合スコア'],
            '表示スコア': h.get('表示スコア', h['総合スコア']),
            '順位予想': h['順位予想'],
            'オッズ': h.get('単勝オッズ'),
            'コース特徴pts': h.get('コース特徴pts'),
            '複勝下限': h.get('複勝下限'),
            '複勝上限': h.get('複勝上限'),
            '人気': h.get('人気'),
            '脚質': h['脚質'],
            'SmartRC推定人気順': rc,
            '乖離度': (int(rc or 99) - h.get('順位予想', 99)) if rc else None,
            'is_memo': h['馬名'] in memo,
            'is_ana': (rc is not None and int(rc) > n // 2 and h['順位予想'] <= 3),
            'is_dark': (rc is not None and int(rc) >= -(-n * 7 // 10)),
            '地方実績のみ': bool(h.get('地方実績のみ')),
        })
    return rows
