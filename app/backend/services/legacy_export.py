# -*- coding: utf-8 -*-
"""クラス判定を既存スクリプトから借りる（写さない）。

新馬・未勝利を選択画面で見分けるために使う。判定は
  baseline_time.class_key(row) -> jv_export.class_display(key)
の2段で、これは jv_export.py が出馬表CSVの「クラス名」を作るのと同じ経路。
自前で書き直すと、CSVに出るクラス名と画面のクラス名がズレる。
"""
from __future__ import annotations

import importlib
import sys
import threading

from .. import config

_lock = threading.Lock()
_bt = None
_jv = None


def _load():
    global _bt, _jv
    with _lock:
        if _bt is not None and _jv is not None:
            return _bt, _jv
        root = str(config.ROOT_DIR)
        if root not in sys.path:
            sys.path.insert(0, root)
        saved = sys.argv
        sys.argv = ['jv_export.py']       # 読み込み時に引数を拾わせない
        try:
            _bt = importlib.import_module('baseline_time')
            _jv = importlib.import_module('jv_export')
        finally:
            sys.argv = saved
        return _bt, _jv


def jyo_romaji() -> dict:
    """場コード -> ファイル名のローマ字。**jv_export.py の定義をそのまま借りる。**

    ここを写すと、jv_export 側を直したときに必ずズレる。実際、過去に生成された
    ファイル名（fs/hd/kt/kk）と現在の定義（fk/hk/ky/ok）は食い違っている。
    これから作るファイルの名前は現在の定義で決まるので、必ず現物を参照する。
    """
    _bt, jv = _load()
    return dict(jv.JYO_ROMAJI)


def class_display_from_codes(syubetu, jyoken_codes, grade=''):
    """NL_RA_RACE の各コードから「新馬/未勝利/1勝/…/OP/G1」表記を得る。"""
    bt, jv = _load()
    row = {
        'GradeCD': grade or '',
        'JyokenInfoSyubetuCD': syubetu or '',
    }
    for i in range(5):
        row['JyokenInfoJyokenCD%d' % i] = (jyoken_codes[i] if i < len(jyoken_codes) else '') or ''
    return jv.class_display(bt.class_key(row))
