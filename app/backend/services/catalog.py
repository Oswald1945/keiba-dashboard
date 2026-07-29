# -*- coding: utf-8 -*-
"""レース一覧の構築（読み取り専用）。

DBは使わない。既存の生成物（horses_data_*.json）と input/ の中身を
そのまま真実として扱う。

horses_data_*.json は1件あたり約170KB・327件あるため、毎回全部読むと遅い。
ファイルの更新時刻とサイズをキーにしたディスクキャッシュを持ち、
変わったファイルだけ読み直す。
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

from .. import config
from . import paths

CACHE_FILE = config.BACKEND_DIR / '.cache' / 'race_index.json'
CACHE_VERSION = 3   # 回顧が速報かどうかを持たせたので上げる（発走時刻はキャッシュしない）

_lock = threading.Lock()


def _load_cache() -> dict:
    if not CACHE_FILE.exists():
        return {'version': CACHE_VERSION, 'races': {}}
    try:
        data = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
        if data.get('version') != CACHE_VERSION:
            return {'version': CACHE_VERSION, 'races': {}}
        return data
    except Exception:
        return {'version': CACHE_VERSION, 'races': {}}


def _save_cache(cache: dict) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
    tmp.replace(CACHE_FILE)


def _int_or_none(v: Any):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _summarize(race_id: str, json_path) -> dict:
    """horses_data_*.json から一覧表示に要る分だけ取り出す。"""
    data = json.loads(json_path.read_text(encoding='utf-8'))
    meta = data.get('meta') or {}
    ri = meta.get('race_info') or {}
    horses = data.get('horses') or []

    entry = {
        'race_id': race_id,
        # 馬名でも検索できるようにする（一覧の絞り込み用。表示はしない）
        'horse_names': [str(h.get('馬名', '')).strip() for h in horses if h.get('馬名')],
        'race_name': (str(ri.get('レース名', '')).strip() or None),
        'race_class': (str(ri.get('クラス名', '')).strip() or None),
        'surface': (str(ri.get('芝ダ', '')).strip() or None),
        'distance': _int_or_none(ri.get('距離')),
        'num_horses': _int_or_none(ri.get('頭数')) or len(horses),
        'baba': meta.get('baba'),
        'has_local_only': any(h.get('地方実績のみ') for h in horses),
    }
    if entry['race_name'] in ('nan', 'None', 'レース名不明'):
        entry['race_name'] = None
    return entry


def _scan_scored() -> dict:
    """horses_data_*.json を走査し、キャッシュを更新して要約を返す。"""
    cache = _load_cache()
    races = cache.get('races', {})
    result: dict = {}
    dirty = False
    seen = set()

    for p in config.OUT_DIR.glob('horses_data_*.json'):
        race_id = p.name[len('horses_data_'):-len('.json')]
        if paths.parse_race_id(race_id) is None:
            continue
        seen.add(race_id)
        st = p.stat()
        stamp = [int(st.st_mtime), st.st_size]
        cached = races.get(race_id)
        if cached and cached.get('stamp') == stamp:
            result[race_id] = cached['summary']
            continue
        try:
            summary = _summarize(race_id, p)
        except Exception as e:
            summary = {'race_id': race_id, 'error': f'{type(e).__name__}: {e}'}
        races[race_id] = {'stamp': stamp, 'summary': summary}
        result[race_id] = summary
        dirty = True

    for stale in [k for k in races if k not in seen]:
        races.pop(stale)
        dirty = True

    if dirty:
        cache['races'] = races
        with _lock:
            _save_cache(cache)
    return result


def _pending_from_input() -> set:
    """input/ にCSVはあるがまだ採点されていない race_id。"""
    pending = set()
    if not config.INPUT_DIR.exists():
        return pending
    fre = __import__('re').compile(r'^(.+?)_(\d{8}_[A-Za-z]+\d{1,2})\.(csv|xlsx|html?)$')
    for p in config.INPUT_DIR.iterdir():
        if p.is_dir():
            continue
        m = fre.match(p.name)
        if not m:
            continue
        pending.add(m.group(2))
    return pending


_LIST_CACHE: dict = {}


def _out_signature() -> tuple:
    """出力フォルダの状態を表す軽い指紋。

    一覧の組み立ては 380ms ほどかかるが、中身が変わっていなければ作り直す必要がない。
    ファイル数といちばん新しい更新時刻を見れば、増減も上書きも拾える（22ms程度）。
    """
    latest = 0.0
    count = 0
    try:
        with os.scandir(config.OUT_DIR) as it:
            for e in it:
                nm = e.name
                if nm.endswith(('_pred.html', '_review.html')) or nm.startswith(
                        ('horses_data_', 'scores_')):
                    try:
                        latest = max(latest, e.stat().st_mtime)
                    except OSError:
                        continue
                    count += 1
    except OSError:
        return (0, 0.0, 0.0)
    extra = 0.0
    for p in (config.MEMO_JSON, config.DATA_DIR / 'featured_races.json'):
        try:
            extra = max(extra, p.stat().st_mtime)
        except OSError:
            pass
    return (count, round(latest, 3), round(extra, 3))


def invalidate_list_cache() -> None:
    """一覧を作り直させる（メモや注目レースを更新したときなど）。"""
    _LIST_CACHE.clear()


def list_races() -> list:
    """全レースの一覧を新しい順で返す。

    中身が変わっていなければ前回の結果を返す（毎回380msかかるのを避ける）。
    """
    sig = _out_signature()
    hit = _LIST_CACHE.get('rows')
    if hit is not None and _LIST_CACHE.get('sig') == sig:
        return hit
    rows = _build_list()
    _LIST_CACHE['sig'] = sig
    _LIST_CACHE['rows'] = rows
    return rows


def _build_list() -> list:
    scored = _scan_scored()
    rows = []

    for race_id, summary in scored.items():
        rows.append(_build_row(race_id, summary, scored=True))

    for race_id in _pending_from_input() - set(scored):
        rows.append(_build_row(race_id, {'race_id': race_id}, scored=False))

    if config.PUBLIC_MODE:
        # 見せられるダッシュボードが1つも無いレースは、行だけ残っても押せないので出さない。
        rows = [r for r in rows if r['has_pred'] or r['has_review']]

    _attach_kaisai(rows)
    rows.sort(key=lambda r: (r['date'], r['venue'] or '', r['race_no']), reverse=True)
    return rows


def _kaisai_from_cache() -> tuple:
    """race.db が無い環境（公開サーバー）用の控えを読む。

    このPCで `python app/tools/export_kaisai.py` を実行して作り、
    同期時に送る。無ければ空を返す（開催回・発走時刻が出ないだけ）。
    """
    p = config.DATA_DIR / 'kaisai_cache.json'
    try:
        data = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}, {}
    info = {}
    for k, v in (data.get('kaisai') or {}).items():
        d, j = k.split('|')
        info[(d, j)] = v
    times = {}
    for k, v in (data.get('start_times') or {}).items():
        d, j, r = k.split('|')
        times[(d, j, int(r))] = v
    return info, times


def _attach_kaisai(rows: list) -> None:
    """「第2回2日目」と発走時刻を各レースに付ける。

    まず race.db を見る（このPC）。読めなければ書き出し済みの控えを使う（公開サーバー）。
    どちらも無ければ、その情報を出さないだけで一覧は表示できる。
    """
    from . import racedb
    dates = sorted({r['date'] for r in rows})
    try:
        info = racedb.kaisai_info(dates)
        times = racedb.start_times(dates)
    except Exception:
        info, times = _kaisai_from_cache()
    if not info and not times:
        return
    for r in rows:
        jyo = racedb.JYO_BY_NAME.get(r.get('venue') or '')
        if not jyo:
            continue
        k = info.get((r['date'], jyo))
        if k:
            r['kaiji'] = k['kaiji']
            r['nichiji'] = k['nichiji']
        t = times.get((r['date'], jyo, r['race_no']))
        if t:
            r['start_time'] = t


RT_MARKER = '速報回顧では取得不可'

# Phase 6（2026-07）で入れた折り畳みの作り。これを含まないHTMLは、それ以前の
# コードで作られたもの＝配色もスマホ対応も古い。公開サーバーでは一覧に出さない。
# 該当レースを再採点して作り直せば、目印が入って自動的に表示に戻る。
LOOK_MARKER = 'note-fold'

_html_cache: dict = {}
_NO_MARKS = {'realtime': False, 'current_look': False}


def _scan_html(path) -> dict:
    """HTMLを1回だけ読んで、中の目印の有無をまとめて返す。

    速報かどうかと見た目の世代は同じファイルから分かるので、読むのは1回で足りる。
    中身が変わらない限り読み直さない（全365件で0.24秒かかるため）。
    """
    if path is None:
        return _NO_MARKS
    try:
        st = path.stat()
    except OSError:
        return _NO_MARKS
    key = (str(path), int(st.st_mtime), st.st_size)
    hit = _html_cache.get(key)
    if hit is None:
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
            hit = {'realtime': RT_MARKER in text, 'current_look': LOOK_MARKER in text}
        except OSError:
            hit = _NO_MARKS
        if len(_html_cache) > 4000:
            _html_cache.clear()
        _html_cache[key] = hit
    return hit


def is_realtime_review(path) -> bool:
    """回顧HTMLが速報(RT_)の成績で作られたものかどうか。

    build_review.py は、生成時にレースラップが取れないと
    「速報回顧では取得不可」と書き込む。それを目印にする。
    確定情報(NL_)で作り直せば、この表示は消える。
    """
    return _scan_html(path)['realtime']


def is_current_look(path) -> bool:
    """いまの見た目で作られたHTMLかどうか。"""
    return _scan_html(path)['current_look']


def _build_row(race_id: str, summary: dict, scored: bool) -> dict:
    key = paths.parse_race_id(race_id)
    pred = paths.pred_html(race_id)
    review = paths.review_html(race_id)
    if config.PUBLIC_MODE:
        # 公開サーバーでは、古いコードで作った見た目のものは出さない。
        # ファイルは残したまま、一覧に出さないだけ（削除ではない）。
        if not is_current_look(pred):
            pred = None
        if not is_current_look(review):
            review = None
    files = paths.input_files(race_id)
    row = {
        'race_id': race_id,
        'date': key.date if key else '',
        'venue': key.venue if key else None,
        'venue_code': key.venue_code if key else '',
        'race_no': key.race_no if key else 0,
        'is_jra': bool(key and key.is_jra),
        'scored': scored,
        'has_pred': pred is not None,
        'has_review': review is not None,
        'review_is_realtime': is_realtime_review(review),
        'has_result': 'レース結果' in files,
        'pred_file': pred.name if pred else None,
        'review_file': review.name if review else None,
    }
    for k in ('race_name', 'race_class', 'surface', 'distance', 'num_horses',
              'baba', 'has_local_only', 'error', 'horse_names'):
        if k in summary:
            row[k] = summary[k]
    return row


def get_race(race_id: str) -> dict | None:
    """1レースの詳細（一覧の1行＋馬ごとのスコア要約）。"""
    if paths.parse_race_id(race_id) is None:
        return None
    jp = paths.horses_json(race_id)
    if not jp.exists():
        rows = [r for r in list_races() if r['race_id'] == race_id]
        return rows[0] if rows else None
    summary = _summarize(race_id, jp)
    return _build_row(race_id, summary, scored=True)
