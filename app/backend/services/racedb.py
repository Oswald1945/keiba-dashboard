# -*- coding: utf-8 -*-
"""race.db（JVLinkToSQLite）の読み取り。**書き込みは一切しない。**

読み取り専用(mode=ro)で開く。2GB超あるので接続は都度開いて閉じる。

ここで扱うもの:
  - 予想できるレース（結果未確定）の一覧  … predict_select.py と同じ条件
  - SmartRC の rcode 組み立て              … race.db だけで完結する
  - 結果の取得状況（NL_/RT_）              … check_results.py と同じ判定
  - 発表馬場（レース後に確定する公式値）
"""
from __future__ import annotations

import datetime
import pathlib
import sqlite3
from contextlib import contextmanager

DB_PATH = pathlib.Path(r'C:\Users\r-ito\JVLinkToSQLite\race.db')

# JRA10場。predict_select.py / check_results.py と同じ並び。
JYO = {'01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
       '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'}
JYO_BY_NAME = {v: k for k, v in JYO.items()}

def _venue_romaji() -> dict:
    """場コード -> ファイル名のローマ字。jv_export.py の定義を借りる（写さない）。"""
    from . import legacy_export
    try:
        return legacy_export.jyo_romaji()
    except Exception:
        # jv_export を読めない環境でも一覧が壊れないようにする
        return {'01': 'sp', '02': 'hk', '03': 'fk', '04': 'ng', '05': 'tk',
                '06': 'nk', '07': 'ck', '08': 'ky', '09': 'hs', '10': 'ok'}


class _RomajiMap(dict):
    """使うときに jv_export から読み込む（起動時に重い import をしない）。"""

    def __missing__(self, key):
        self.update(_venue_romaji())
        return dict.__getitem__(self, key) if dict.__contains__(self, key) else None

    def get(self, key, default=None):
        if not self:
            self.update(_venue_romaji())
        return dict.get(self, key, default)


VENUE_ROMAJI = _RomajiMap()

BABA_CODE = {'1': '良', '2': '稍重', '3': '重', '4': '不良'}
TENKO_CODE = {'1': '晴', '2': '曇', '3': '雨', '4': '小雨', '5': '雪', '6': '小雪'}


class RaceDbUnavailable(RuntimeError):
    pass


@contextmanager
def connect():
    if not DB_PATH.exists():
        raise RaceDbUnavailable(
            f'race.db が見つかりません: {DB_PATH}\n'
            'JVLinkToSQLite のインストール先を確認してください。')
    con = sqlite3.connect(DB_PATH.as_uri() + '?mode=ro', uri=True, timeout=15)
    try:
        yield con
    finally:
        con.close()


def _table_exists(cur, name: str) -> bool:
    return cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


# ── クラス表記 ────────────────────────────────────────────────────
def _class_label(syubetu, jyokens, grade='') -> str:
    """新馬 / 未勝利 / 1勝 / 2勝 / 3勝 / OP / G1..G3 を返す。

    判定は既存 jv_export.py の class_key/class_display に合わせる（写さず借りる）。
    """
    from . import legacy_export
    return legacy_export.class_display_from_codes(syubetu, jyokens, grade)


def is_jump(trackcd) -> bool:
    """障害戦かどうか。TrackCD 51〜59 が障害。

    障害戦には芝・ダートの基準タイムが無く、採点できない。
    予想の対象に出してしまうと誤った結果を出すので一覧から外す。
    """
    try:
        return 51 <= int(str(trackcd).strip()) <= 59
    except (TypeError, ValueError):
        return False


def predictable_races(days_back: int = 3) -> list:
    """結果が確定していない＝これから予想できるレースを日付・会場ごとに返す。

    条件は predict_select.py の predictable() と同じ（確定着順が1頭も無い）。
    """
    cutoff = (datetime.date.today() - datetime.timedelta(days=days_back)).strftime('%Y%m%d')
    with connect() as con:
        cur = con.cursor()
        rows = cur.execute("""
          SELECT se.idYear, se.idMonthDay, se.idJyoCD, se.idKaiji, se.idNichiji,
                 se.idRaceNum, COUNT(*) n,
                 SUM(CASE WHEN CAST(se.KakuteiJyuni AS INTEGER)>0 THEN 1 ELSE 0 END) fin
            FROM NL_SE_RACE_UMA se
           WHERE (se.idYear||se.idMonthDay) >= ?
           GROUP BY se.idYear, se.idMonthDay, se.idJyoCD, se.idKaiji, se.idNichiji, se.idRaceNum
          HAVING fin=0
           ORDER BY se.idYear, se.idMonthDay, se.idJyoCD, CAST(se.idRaceNum AS INTEGER)
        """, (cutoff,)).fetchall()

        cur2 = con.cursor()
        groups: dict = {}
        for yy, md, jyo, kai, nichi, rno, n, _fin in rows:
            if jyo not in JYO:
                continue
            ra = cur2.execute(
                'SELECT RaceInfoHondai, RaceInfoRyakusyo10, JyokenInfoSyubetuCD, '
                '       JyokenInfoJyokenCD0, JyokenInfoJyokenCD1, JyokenInfoJyokenCD2, '
                '       JyokenInfoJyokenCD3, JyokenInfoJyokenCD4, GradeCD, Kyori, TrackCD, '
                '       HassoTime '
                '  FROM NL_RA_RACE WHERE idYear=? AND idMonthDay=? AND idJyoCD=? '
                '   AND idRaceNum=? LIMIT 1', (yy, md, jyo, rno)).fetchone()
            if ra is not None and is_jump(ra[10]):
                continue        # 障害戦は採点の対象外なので一覧に出さない
            name = ''
            cls = ''
            if ra:
                name = ((ra[0] or ra[1]) or '').strip()
                try:
                    cls = _class_label(ra[2], list(ra[3:8]), ra[8])
                except Exception:
                    cls = ''
            date = yy + md
            key = (date, jyo)
            groups.setdefault(key, {
                'date': date, 'jyo': jyo, 'venue': JYO[jyo],
                'kaiji': str(kai).zfill(2), 'nichiji': str(nichi).zfill(2),
                'races': [],
            })
            groups[key]['races'].append({
                'race_no': int(rno),
                'start_time': _fmt_time(ra[11] if ra and len(ra) > 11 else None),
                'race_id': f'{date}_{VENUE_ROMAJI[jyo]}{int(rno)}',
                'name': name,
                'race_class': cls,
                'num_horses': n,
                'is_maiden': cls in ('新馬', '未勝利'),
                'rcode': f'{date}{jyo}{str(kai).zfill(2)}{str(nichi).zfill(2)}{str(rno).zfill(2)}',
            })
    out = list(groups.values())
    out.sort(key=lambda g: (g['date'], g['jyo']))
    return out


def _fmt_time(v) -> str | None:
    """'1000' -> '10:00'。空や 0 は None。"""
    t = str(v or '').strip()
    if len(t) != 4 or not t.isdigit() or t == '0000':
        return None
    return f'{t[:2]}:{t[2:]}'


def start_times(dates: list) -> dict:
    """(日付, 場コード, R番号) -> '10:00'。一覧に発走時刻を出すために使う。"""
    if not dates:
        return {}
    out: dict = {}
    with connect() as con:
        cur = con.cursor()
        for date in sorted(set(dates)):
            if len(date) != 8:
                continue
            for jyo, rno, t in cur.execute(
                'SELECT idJyoCD, CAST(idRaceNum AS INTEGER), HassoTime FROM NL_RA_RACE '
                'WHERE idYear=? AND idMonthDay=?', (date[:4], date[4:])).fetchall():
                v = _fmt_time(t)
                if v:
                    out[(date, jyo, int(rno))] = v
    return out


def rcode(date: str, jyo: str, race_no: int) -> str | None:
    """SmartRC の rcode を race.db から組み立てる。

    rcode = YYYYMMDD + 場コード(2) + 開催回(2) + 開催日(2) + レース番号(2)
    races/view（不安定）を呼ばずに済むので、SmartRC取得を自動化できる。
    """
    with connect() as con:
        r = con.execute(
            'SELECT idKaiji, idNichiji FROM NL_RA_RACE '
            'WHERE idYear=? AND idMonthDay=? AND idJyoCD=? AND CAST(idRaceNum AS INTEGER)=? '
            'LIMIT 1', (date[:4], date[4:], jyo, int(race_no))).fetchone()
    if not r:
        return None
    kai, nichi = r
    return f'{date}{jyo}{str(kai).zfill(2)}{str(nichi).zfill(2)}{str(race_no).zfill(2)}'


def kaisai_info(dates: list) -> dict:
    """(日付, 場コード) -> {'kaiji': 第N回, 'nichiji': M日目}。

    一覧の見出しに「第2回2日目」を出すために使う。race.db が無くても
    画面が壊れないよう、呼び出し側で空扱いにできるようにしてある。
    """
    if not dates:
        return {}
    out: dict = {}
    with connect() as con:
        cur = con.cursor()
        for date in sorted(set(dates)):
            if len(date) != 8:
                continue
            for jyo, kai, nichi in cur.execute(
                'SELECT idJyoCD, idKaiji, idNichiji FROM NL_RA_RACE '
                'WHERE idYear=? AND idMonthDay=? GROUP BY idJyoCD, idKaiji, idNichiji',
                    (date[:4], date[4:])).fetchall():
                try:
                    out[(date, jyo)] = {'kaiji': int(kai), 'nichiji': int(nichi)}
                except (TypeError, ValueError):
                    continue
    return out


def result_status(date: str) -> dict:
    """指定日の結果取得状況。check_results.py と同じ判定。"""
    yy, mmdd = date[:4], date[4:]
    with connect() as con:
        cur = con.cursor()

        def counts(table):
            if not _table_exists(cur, table):
                return None
            out = {}
            for jyo, rno, n, fin in cur.execute(f"""
                SELECT se.idJyoCD, CAST(se.idRaceNum AS INTEGER), COUNT(*),
                       SUM(CASE WHEN CAST(se.KakuteiJyuni AS INTEGER)>0 THEN 1 ELSE 0 END)
                  FROM {table} se WHERE se.idYear=? AND se.idMonthDay=?
                 GROUP BY se.idJyoCD, se.idRaceNum""", (yy, mmdd)).fetchall():
                out[(jyo, rno)] = (n, fin or 0)
            return out

        nl = counts('NL_SE_RACE_UMA')
        rt = counts('RT_SE_RACE_UMA')

    races = []
    done = 0
    for key in sorted((nl or {}).keys()):
        jyo, rno = key
        n, fin_nl = nl[key]
        fin_rt = (rt.get(key, (0, 0))[1] if rt else 0)
        fin = max(fin_nl, fin_rt)
        confirmed = (fin >= n - 1 and fin > 0)   # 取消等を許容
        if confirmed:
            done += 1
        races.append({
            'jyo': jyo, 'venue': JYO.get(jyo, f'地方({jyo})'), 'race_no': rno,
            'race_id': f'{date}_{VENUE_ROMAJI[jyo]}{rno}' if jyo in VENUE_ROMAJI else None,
            'num_horses': n, 'fin_nl': fin_nl, 'fin_rt': fin_rt,
            'source': ('NL' if fin_nl >= fin and fin > 0 else ('RT' if fin > 0 else None)),
            'state': '確定' if confirmed else ('一部' if fin > 0 else '未確定'),
        })
    return {
        'date': date,
        'has_realtime_table': rt is not None,
        'total': len(races),
        'confirmed': done,
        'all_confirmed': bool(races) and done == len(races),
        'races': races,
    }


def announced_going(date: str, jyo: str) -> dict:
    """発表馬場（レース当日に確定する公式値）。無ければ空。

    レースごとに芝かダートの該当する方だけ入るので、その日の会場単位で集約する。
    """
    yy, mmdd = date[:4], date[4:]
    out = {'芝': None, 'ダート': None, '天候': None, 'source': None}
    with connect() as con:
        cur = con.cursor()
        for table, tag in (('NL_RA_RACE', 'NL'), ('RT_RA_RACE', 'RT')):
            if not _table_exists(cur, table):
                continue
            rows = cur.execute(
                f'SELECT TenkoBabaTenkoCD, TenkoBabaSibaBabaCD, TenkoBabaDirtBabaCD '
                f'  FROM {table} WHERE idYear=? AND idMonthDay=? AND idJyoCD=?',
                (yy, mmdd, jyo)).fetchall()
            for tenko, siba, dirt in rows:
                if BABA_CODE.get(str(siba)) and not out['芝']:
                    out['芝'] = BABA_CODE[str(siba)]
                    out['source'] = tag
                if BABA_CODE.get(str(dirt)) and not out['ダート']:
                    out['ダート'] = BABA_CODE[str(dirt)]
                    out['source'] = tag
                if TENKO_CODE.get(str(tenko)) and not out['天候']:
                    out['天候'] = TENKO_CODE[str(tenko)]
    return out


def available() -> dict:
    """race.db を読めるか。画面の状態表示用。"""
    try:
        with connect() as con:
            latest = con.execute(
                'SELECT MAX(idYear||idMonthDay) FROM NL_SE_RACE_UMA').fetchone()[0]
            rt_latest = None
            if _table_exists(con.cursor(), 'RT_SE_RACE_UMA'):
                rt_latest = con.execute(
                    'SELECT MAX(idYear||idMonthDay) FROM RT_SE_RACE_UMA').fetchone()[0]
        return {'ok': True, 'path': str(DB_PATH), 'latest_nl': latest, 'latest_rt': rt_latest}
    except Exception as e:
        return {'ok': False, 'path': str(DB_PATH), 'error': str(e)}
