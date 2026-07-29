# -*- coding: utf-8 -*-
"""アプリ全体のパス定義。既存ルート直下の構成には一切手を触れない。

このファイルが「どこに何があるか」の唯一の真実。
他モジュールはここ以外でパスを組み立てないこと。
"""
from __future__ import annotations

import os
import pathlib

# app/backend/config.py -> app/backend -> app -> リポジトリルート
BACKEND_DIR = pathlib.Path(__file__).resolve().parent
APP_DIR = BACKEND_DIR.parent
ROOT_DIR = APP_DIR.parent

# ── 既存パイプラインの資産（読み取り中心） ──────────────────────────
INPUT_DIR = ROOT_DIR / 'input'
DONE_DIR = INPUT_DIR / 'done'
ARCHIVE_DIR = ROOT_DIR / '_archive'

# 生成物（horses_data_*.json / *_pred.html / *_review.html）はルート直下
OUT_DIR = ROOT_DIR

SCORE_PY = ROOT_DIR / 'score_horse_v3.py'
DASH_PY = ROOT_DIR / 'build_dashboard_v3.py'
REVIEW_PY = ROOT_DIR / 'build_review.py'
RUN_NEW_PY = ROOT_DIR / 'run_new.py'
JV_EXPORT_PY = ROOT_DIR / 'jv_export.py'

MEMO_JSON = ROOT_DIR / 'memo_horses.json'
BABA_MANUAL_JSON = ROOT_DIR / 'baba_manual.json'

# ── アプリ固有 ────────────────────────────────────────────────────
DATA_DIR = APP_DIR / 'data'          # アプリが書き込む小さなJSON置き場
FRONTEND_DIST = APP_DIR / 'frontend' / 'dist'

# ── 公開モード ────────────────────────────────────────────────────
# 環境変数 KEIBA_PUBLIC=1 で外部公開用の動作になる。
#   ・ログインを要求する（招待制）
#   ・管理タブ／検証タブの API を**そもそも登録しない**
#     （画面で隠すだけでは、URLを直接叩かれると動いてしまうため）
# 自分のPCで動かすときは未設定のままでよい（従来どおり誰でも全機能）。
PUBLIC_MODE = os.environ.get('KEIBA_PUBLIC', '').strip() in ('1', 'true', 'yes', 'on')
TESTS_DIR = APP_DIR / 'tests'
GOLDEN_DIR = TESTS_DIR / 'golden'

# 書き込み系の退避先（物理削除はしない方針。上書き前に必ずここへ退避する）
BACKUP_DIR = ARCHIVE_DIR / 'app_backups'


def child_env() -> dict:
    """既存スクリプトを子プロセス起動するときの環境変数。

    run_new.py が smartrc_fetch / fetch_baba を呼ぶときと同じく
    PYTHONIOENCODING=utf-8 を立てて、標準出力の文字化けを防ぐ。
    """
    return {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
