# -*- coding: utf-8 -*-
"""既存スクリプトの定義を「写さずに借りる」ための入口。

会場コード表などをアプリ側にコピーすると、既存を直したときに必ずズレる。
そこで run_new.py をモジュールとして読み込んで参照する。

run_new.py はモジュール読み込み時に sys.argv を見てフラグを立てる
（DRY_RUN / FORCE_PRED など）ので、読み込みの間だけ sys.argv を
差し替えて副作用が起きないようにする。main() は呼ばれない。
"""
from __future__ import annotations

import importlib
import sys
import threading

from . import config

_lock = threading.Lock()
_run_new = None


def run_new_module():
    """run_new.py をフラグ無しの状態で読み込んで返す（1回だけ）。"""
    global _run_new
    with _lock:
        if _run_new is not None:
            return _run_new
        root = str(config.ROOT_DIR)
        if root not in sys.path:
            sys.path.insert(0, root)
        saved_argv = sys.argv
        sys.argv = ['run_new.py']          # --force 等を拾わせない
        try:
            _run_new = importlib.import_module('run_new')
        finally:
            sys.argv = saved_argv
        return _run_new


def venue_code_map() -> dict:
    """会場コード(大文字) -> 会場名。JRA10場＋地方。"""
    return dict(run_new_module()._VENUE_CODE_MAP)


def venue_from_race_id(race_id: str):
    """race_id から会場名を得る（既存 run_new.extract_venue_from_race_id と同一）。"""
    return run_new_module().extract_venue_from_race_id(race_id)


# 入力CSVの種別名と命名規則も既存に合わせる（写さず借りる）
def input_kinds() -> list:
    return list(run_new_module().ALL_KINDS)


def filename_re():
    return run_new_module().FILENAME_RE
