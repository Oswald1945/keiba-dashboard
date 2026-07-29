# -*- coding: utf-8 -*-
"""
inspect_upcoming.py ― race.db 内の「まだ結果が出ていない（＝これから予想できる）レース」を一覧。
出馬表が確定して差分更新でDBに入ると、ここに出走頭数付きで並ぶ。
日付・場コード・R を run_predict.bat / jv_export.py に渡して予想する。
"""
import sqlite3, os, sys, datetime

DB = r"C:\Users\r-ito\JVLinkToSQLite\race.db"
JYO = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
       "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}

def main():
    if not os.path.exists(DB):
        print("DB not found:", DB); sys.exit(1)
    con = sqlite3.connect(DB); cur = con.cursor()

    # 直近の「結果確定済み」最終日（データの新しさ確認用）
    cur.execute("SELECT MAX(idYear||idMonthDay) FROM NL_SE_RACE_UMA "
                "WHERE CAST(KakuteiJyuni AS INTEGER)>0")
    last_fin = cur.fetchone()[0]
    print("結果確定済みの最終レース日:", last_fin)

    cutoff = (datetime.date.today() - datetime.timedelta(days=3)).strftime("%Y%m%d")
    # 結果未確定（fin=0）のレース＝出馬表段階
    q = """
      SELECT se.idYear, se.idMonthDay, se.idJyoCD, se.idRaceNum, COUNT(*) n,
             SUM(CASE WHEN CAST(se.KakuteiJyuni AS INTEGER)>0 THEN 1 ELSE 0 END) fin
        FROM NL_SE_RACE_UMA se
       WHERE (se.idYear||se.idMonthDay) >= ?
       GROUP BY se.idYear, se.idMonthDay, se.idJyoCD, se.idKaiji, se.idNichiji, se.idRaceNum
      HAVING fin=0
       ORDER BY se.idYear, se.idMonthDay, se.idJyoCD, CAST(se.idRaceNum AS INTEGER)
    """
    rows = cur.execute(q, (cutoff,)).fetchall()
    if not rows:
        print("\n出馬表段階（結果未確定）のレースは見つかりません。")
        print("→ 週末の出馬表が未発表か、差分更新が未実行の可能性。金曜以降に更新して再確認してください。")
    else:
        print("\n=== これから予想できるレース（結果未確定）===")
        print(" 日付       場   R   頭数  レース名")
        # レース名を引く
        for (yy, md, jyo, rno, n, fin) in rows:
            ra = cur.execute(
                "SELECT RaceInfoHondai, RaceInfoRyakusyo10 FROM NL_RA_RACE "
                "WHERE idYear=? AND idMonthDay=? AND idJyoCD=? AND idRaceNum=? LIMIT 1",
                (yy, md, jyo, rno)).fetchone()
            nm = ((ra[0] or ra[1]) if ra else "").strip()
            print(" %s%s %s(%s) R%-2s %3d  %s"
                  % (yy, md, JYO.get(jyo, jyo), jyo, str(int(rno)), n, nm))
    con.close()

if __name__ == "__main__":
    main()
