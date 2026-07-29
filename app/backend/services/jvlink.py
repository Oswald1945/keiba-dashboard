# -*- coding: utf-8 -*-
"""JV-Link（JVLinkToSQLite）まわりの操作。

できること:
  - 差分更新（jvlink_update.ps1 -m exec）
  - 速報系(RT_)の対象開催日の設定・確認

できないこと（正直に）:
  - **JV-Linkキーの有効化（設定ダイアログを開いてOK）はGUI操作でスクリプト化できない。**
    怠ると RC=-303（利用キー空値）で更新が失敗する。日次で切れることが多いので、
    実行前チェックリストを毎回出し、-303 を検出したら画面で明示する。
"""
from __future__ import annotations

import re
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import config
from . import jobs

JST = timezone(timedelta(hours=9))

TOOL_DIR = Path(r'C:\Users\r-ito\JVLinkToSQLite')
EXE = TOOL_DIR / 'jvlinktosqlite.exe'
SETTING_XML = TOOL_DIR / 'setting.xml'
UPDATE_PS1 = config.ROOT_DIR / 'jvlink_update.ps1'

# 速報系の対象開催日を持つノード（ライブ予想_運用手順.md の手順と同じ）
KAISAI_XPATH = ('//JVRealTimeDataUpdateSetting/DataSpecSettings/JVDataSpecSetting'
                '/JVKaisaiDateKey/KaisaiDate')

# JV-Link のエラーコード（画面に意味を出すため）
ERROR_HINTS = {
    -303: ('JV-Linkの利用キーが有効になっていません。'
           'JV-Link設定を開いて「OK」を押してから、もう一度実行してください。'),
    -504: 'JRA-VAN側がメンテナンス中の可能性があります。時間をおいて再実行してください。',
    -3001: '引数の指定が不正です。',
    -3002: '注意点ありで終了しました。setting.xml を確認してください。',
    -3003: 'JV-Link以外の例外が発生しました。',
}

CHECKLIST = [
    'JV-Link設定を開いて「OK」を押しましたか？（利用キーは日次で切れることがあります）',
    'インターネットに接続されていますか？',
]


def environment() -> dict:
    """実行環境が揃っているか。画面の状態表示用。"""
    return {
        'tool_dir': str(TOOL_DIR),
        'exe_exists': EXE.exists(),
        'setting_exists': SETTING_XML.exists(),
        'update_script_exists': UPDATE_PS1.exists(),
        'checklist': CHECKLIST,
    }


def realtime_setting() -> dict:
    """速報系の有効/無効と、いま設定されている対象開催日を読む。"""
    if not SETTING_XML.exists():
        return {'available': False, 'error': f'setting.xml が見つかりません: {SETTING_XML}'}
    try:
        root = ET.parse(SETTING_XML).getroot()
    except Exception as e:
        return {'available': False, 'error': f'setting.xml を読めません: {e}'}

    node = root.find('.//JVRealTimeDataUpdateSetting')
    if node is None:
        return {'available': False, 'error': 'JVRealTimeDataUpdateSetting が見つかりません'}

    enabled = (node.findtext('IsEnabled') or '').strip().lower() == 'true'
    specs = []
    dates = set()
    for s in node.findall('.//JVDataSpecSetting'):
        spec = (s.findtext('DataSpec') or '').strip()
        on = (s.findtext('IsEnabled') or '').strip().lower() == 'true'
        kd = s.findtext('.//JVKaisaiDateKey/KaisaiDate')
        specs.append({'data_spec': spec, 'enabled': on, 'kaisai_date': kd})
        if on and kd:
            dates.add(kd[:10])
    return {
        'available': True,
        'enabled': enabled,
        'kaisai_dates': sorted(dates),
        'specs': specs,
    }


def _backup_setting(reason: str) -> Path | None:
    if not SETTING_XML.exists():
        return None
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(JST).strftime('%Y%m%d_%H%M%S')
    dest = config.BACKUP_DIR / f'setting_{stamp}_{reason}.xml'
    shutil.copy2(SETTING_XML, dest)
    return dest


def set_realtime_date(job: jobs.Job, date: str) -> None:
    """速報系の対象開催日を YYYYMMDD に設定する。

    XMLを直接書き換えず、公式の `jvlinktosqlite setting` コマンドを使う。
    変更前に setting.xml を退避する。
    """
    if not (date or '').isdigit() or len(date) != 8:
        raise ValueError(f'日付は YYYYMMDD で指定してください: {date}')
    if not EXE.exists():
        raise RuntimeError(f'jvlinktosqlite.exe が見つかりません: {EXE}')

    value = f'{date[:4]}-{date[4:6]}-{date[6:]}T00:00:00'
    backup = _backup_setting('kaisai')
    if backup:
        jobs.log(job, f'[設定] setting.xml を退避しました: {backup.name}')
    jobs.log(job, f'[設定] 速報系の対象開催日を {date[:4]}-{date[4:6]}-{date[6:]} に設定します')

    code = jobs.run_stream(
        job, [EXE, 'setting', '-x', KAISAI_XPATH, '-v', value, '-f'],
        cwd=TOOL_DIR, timeout=120)
    if code != 0:
        raise RuntimeError(f'対象開催日の設定に失敗しました (code={code})')

    now = realtime_setting()
    jobs.log(job, f'[設定] 現在の対象開催日: {", ".join(now.get("kaisai_dates") or []) or "(なし)"}')


def update(job: jobs.Job, mode: str = 'exec') -> int:
    """差分更新（jvlink_update.ps1）。戻り値は終了コード。"""
    if not UPDATE_PS1.exists():
        raise RuntimeError(f'jvlink_update.ps1 が見つかりません: {UPDATE_PS1}')
    jobs.log(job, '[更新] race.db の差分更新を開始します（数分かかることがあります）')
    code = jobs.run_stream(job, [
        'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', str(UPDATE_PS1), '-Mode', mode,
    ], timeout=3600)

    if code == 0:
        jobs.log(job, '[更新] 完了しました。')
        return code

    hint = ERROR_HINTS.get(code)
    text = '\n'.join(job.lines[-40:])
    if hint is None and re.search(r'-303\b', text):
        hint = ERROR_HINTS[-303]
    jobs.log(job, f'[更新] 終了コード {code}')
    if hint:
        jobs.log(job, f'[要対応] {hint}')
        job.result['hint'] = hint
    job.result['returncode'] = code
    raise RuntimeError(hint or f'差分更新に失敗しました (code={code})')
