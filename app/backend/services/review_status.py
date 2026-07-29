# -*- coding: utf-8 -*-
"""回顧の状態を判定する。

2つの状態を出す。
  1. 予想は作ったが回顧がまだ  → 結果を取り込んで回顧を作る対象
  2. 回顧が速報(RT)のまま      → 確定情報(NL)で作り直せる対象

「速報のまま」の判定は、回顧HTMLに build_review.py が入れる
「速報回顧では取得不可」の表示があるか（＝生成時にレースラップが無かった）と、
いま race.db に確定ラップが来ているかの2つを突き合わせる。
"""
from __future__ import annotations

import collections
import datetime

from . import catalog, paths, racedb

# 目印の判定は一覧の作成時に済ませてキャッシュしてある（catalog）。
RT_MARKER = catalog.RT_MARKER


def _nl_has_lap(date: str, jyo: str, race_no: int) -> bool:
    """確定成績のレースラップが race.db に来ているか。"""
    try:
        with racedb.connect() as con:
            row = con.execute(
                'SELECT HaronTimeS3, HaronTimeL3, LapTime0 FROM NL_RA_RACE '
                'WHERE idYear=? AND idMonthDay=? AND idJyoCD=? '
                'AND CAST(idRaceNum AS INTEGER)=? LIMIT 1',
                (date[:4], date[4:], jyo, int(race_no))).fetchone()
    except Exception:
        return False
    if not row:
        return False
    return any(str(v or '').strip() not in ('', '0', '000', '0000') for v in row)


def _target(row: dict) -> dict:
    key = paths.parse_race_id(row['race_id'])
    jyo = racedb.JYO_BY_NAME.get(key.venue or '', '') if key else ''
    return {'date': row['date'], 'jyo': jyo, 'race_no': row['race_no'],
            'race_id': row['race_id'], 'venue': row['venue'],
            'race_name': row.get('race_name'), 'race_class': row.get('race_class')}


def overview() -> dict:
    """回顧まわりの全体像を1回で返す。"""
    rows = [r for r in catalog.list_races() if r['scored'] and r['is_jra']]

    pending = collections.defaultdict(list)      # 回顧未作成
    upgradable = collections.defaultdict(list)   # 速報のまま＝作り直せる
    rt_waiting = collections.defaultdict(list)   # 速報のままだが確定ラップがまだ

    for r in rows:
        if not r['has_review']:
            pending[r['date']].append(_target(r))
            continue
        if not r.get('review_is_realtime'):
            continue
        t = _target(r)
        if _nl_has_lap(r['date'], t['jyo'], r['race_no']):
            upgradable[r['date']].append(t)
        else:
            rt_waiting[r['date']].append(t)

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    recent = {today.strftime('%Y%m%d'), yesterday.strftime('%Y%m%d')}

    def pack(d: dict) -> list:
        return [{'date': k, 'count': len(v), 'races': v} for k, v in sorted(d.items(), reverse=True)]

    pending_days = pack(pending)
    for day in pending_days:
        # 当日・前日は確定成績がまだ来ないので速報系(RT_)を取りに行く必要がある。
        # それ以前は蓄積系(NL_)に入っているはずなので、差分更新だけでよい。
        day['needs_realtime'] = day['date'] in recent

    return {
        'pending': pending_days,
        'pending_total': sum(d['count'] for d in pending_days),
        'upgradable': pack(upgradable),
        'upgradable_total': sum(len(v) for v in upgradable.values()),
        'realtime_waiting': pack(rt_waiting),
        'realtime_waiting_total': sum(len(v) for v in rt_waiting.values()),
        'realtime_target_dates': [d['date'] for d in pending_days if d['needs_realtime']],
    }
