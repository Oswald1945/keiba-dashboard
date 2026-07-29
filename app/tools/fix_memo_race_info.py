# -*- coding: utf-8 -*-
"""memo_horses.json のレース情報を race.db の値で直す。

直す対象:
  1. 会場が「sp」「fs」などローマ字のまま入っているもの
     （run_new.py の変換表もれ。原因は修正済み）
  2. レース名がローマ字（「G1_FeburariiS」）、またはクラス名（「1勝クラス」）に
     なっているもの（run_new.py のタイトル解析の誤り。原因は修正済み）
  3. クラスが空のもの（race.db から補える場合のみ）
  4. 会場そのものが違うもの（例: 6/20 の「京都11R」。実際は阪神11R 天保山S）
     → 馬名＋日付で race.db を引き、**出走が1件だけ**かつ **R番号が一致**する
       ときに限って会場を直す。候補が複数ある・R が違う場合は触らない。

やらないこと:
  - 馬名・登録日・メモ本文には触れない
  - race.db に該当レースが無いものは**そのまま残す**（推測で埋めない）

使い方:
    python app/tools/fix_memo_race_info.py            # 確認のみ（書き換えない）
    python app/tools/fix_memo_race_info.py --apply    # 実際に書き換える
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.backend import config                       # noqa: E402
from app.backend.services import memo_store, racedb  # noqa: E402

JYO_NAME = {
    '01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
    '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉',
}

ASCII_NAME = re.compile(r'^[A-Za-z0-9_\-. ]+$')
# 「1勝」「1勝クラス」「3勝クラス」など、クラス名がレース名欄に入ってしまったもの
CLASS_LIKE = re.compile(r'^(新馬|未勝利|[1-3]勝(クラス)?|オープン|OP|Ｇ[1-3]|G[1-3])$')


def venue_from_horse(cur, horse: str, ymd: str, rnum) -> str | None:
    """馬名＋日付から出走レースを特定し、会場コードを返す。

    確実なときだけ直したいので、次の条件をすべて満たす場合に限る。
      - その日の出走が **1件だけ**（複数なら特定できないので触らない）
      - メモの R 番号と一致する（一致しなければ別のレースの記録かもしれない）
    """
    try:
        rows = cur.execute(
            'SELECT idJyoCD, CAST(idRaceNum AS INTEGER) FROM NL_SE_RACE_UMA '
            ' WHERE Bamei=? AND idYear=? AND idMonthDay=?',
            (horse, ymd[:4], ymd[4:])).fetchall()
    except Exception:
        return None
    if len(rows) != 1:
        return None
    jyo, r = rows[0]
    if rnum is None or int(rnum) != int(r):
        return None
    return jyo


def looks_wrong(name: str) -> bool:
    n = (name or '').strip()
    if not n:
        return True                     # 空。race.db に名前があれば埋める
    if ASCII_NAME.match(n):
        return True                     # ローマ字
    return bool(CLASS_LIKE.match(n))    # クラス名が入っている


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='実際に書き換える（既定は確認のみ）')
    args = ap.parse_args()

    path = config.MEMO_JSON
    memo = json.loads(path.read_text(encoding='utf-8'))

    fixed_venue = fixed_name = fixed_class = 0
    fixed_venue_by_horse = 0
    untouched = 0
    changes = []

    with racedb.connect() as con:
        cur = con.cursor()
        for e in memo:
            src = e.get('元レース') or {}
            before = dict(src)

            # ① 会場をローマ字から会場名へ
            venue = memo_store.normalize_venue(src.get('場所'))
            if venue and venue != src.get('場所'):
                src['場所'] = venue
                fixed_venue += 1

            d = str(src.get('日付', '')).replace('/', '')
            jyo = racedb.JYO_BY_NAME.get(venue or '')
            r = src.get('R')
            if not (len(d) == 8 and jyo and r):
                untouched += 1
                continue

            def _race_row(jyo_cd):
                return cur.execute(
                    'SELECT RaceInfoHondai, RaceInfoRyakusyo10, JyokenInfoSyubetuCD, '
                    '       JyokenInfoJyokenCD0, JyokenInfoJyokenCD1, JyokenInfoJyokenCD2, '
                    '       JyokenInfoJyokenCD3, JyokenInfoJyokenCD4, GradeCD '
                    '  FROM NL_RA_RACE WHERE idYear=? AND idMonthDay=? AND idJyoCD=? '
                    '   AND CAST(idRaceNum AS INTEGER)=? LIMIT 1',
                    (d[:4], d[4:], jyo_cd, int(r))).fetchone()

            row = _race_row(jyo)
            if not row:
                # 会場そのものが違う可能性。馬名から引き当て直す。
                real_jyo = venue_from_horse(cur, e.get('馬名', ''), d, r)
                if real_jyo and real_jyo != jyo:
                    row = _race_row(real_jyo)
                    if row:
                        jyo = real_jyo
                        src['場所'] = JYO_NAME.get(real_jyo, src.get('場所'))
                        fixed_venue_by_horse += 1
            if not row:
                untouched += 1
                continue

            # ② レース名
            #   race.db に名前があればそれに直す。
            #   名前が無い（平場）のに誤った値が入っていたら**空にする**。
            #   「1勝」のようなクラス名がレース名欄に残ると二重表示になるため。
            real = ((row[0] or row[1]) or '').strip()
            cur_name = str(src.get('レース名', '')).strip()
            if looks_wrong(cur_name):
                if real:
                    if cur_name != real:
                        src['レース名'] = real
                        fixed_name += 1
                elif cur_name:
                    src['レース名'] = ''
                    fixed_name += 1

            # ③ クラス（空のときだけ補う）
            if not str(src.get('クラス', '')).strip():
                try:
                    from app.backend.services import legacy_export
                    cls = legacy_export.class_display_from_codes(row[2], list(row[3:8]), row[8])
                except Exception:
                    cls = ''
                if cls:
                    src['クラス'] = cls
                    fixed_class += 1

            if src != before and len(changes) < 12:
                changes.append((e.get('馬名', ''), before, dict(src)))
            e['元レース'] = src

    print(f'対象 {len(memo)} 件')
    print(f'  会場を会場名に直した     : {fixed_venue} 件')
    print(f'  レース名を正しい名前に直した: {fixed_name} 件')
    print(f'  クラスを補った            : {fixed_class} 件')
    print(f'  会場そのものを直した(馬名照合): {fixed_venue_by_horse} 件')
    print(f'  race.db に無く手を付けなかった: {untouched} 件')
    print()
    print('変更の例:')
    for horse, b, a in changes:
        print(f'  {horse}')
        print(f'     前: {b.get("場所")}{b.get("R")}R 「{b.get("レース名")}」 {b.get("クラス")}')
        print(f'     後: {a.get("場所")}{a.get("R")}R 「{a.get("レース名")}」 {a.get("クラス")}')

    total = fixed_venue + fixed_name + fixed_class + fixed_venue_by_horse
    if not args.apply:
        print()
        print(f'※ 確認のみです。書き換えるには --apply を付けてください（変更 {total} 箇所）')
        return 0
    if not total:
        print('\n直すところはありませんでした。')
        return 0

    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = config.BACKUP_DIR / f'memo_horses_{stamp}_before_fix.json'
    shutil.copy2(path, backup)

    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(memo, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    print(f'\n書き換えました（{total} 箇所）。書き換え前の控え: {backup.name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
