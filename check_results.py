# -*- coding: utf-8 -*-
"""
check_results.py ― レース結果(確定着順)の取得状況チェック
==============================================================
race.db に指定日の「確定着順(KakuteiJyuni)」が取り込まれているかを
会場・レース別に一覧表示する。回顧ダッシュボード生成の前段確認用。

使い方:
  python check_results.py            # 既定=今日(YYYYMMDD)
  python check_results.py 20260725   # 日付指定
JV-Linkの差分更新(結果取り込み)を先に実行してから走らせること。
"""
import sqlite3, os, sys, datetime

DB  = r"C:\Users\r-ito\JVLinkToSQLite\race.db"
JYO = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
       "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}


def main():
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().strftime("%Y%m%d")
    if not os.path.exists(DB):
        print("race.db が見つかりません:", DB); sys.exit(1)
    yy, mmdd = date[:4], date[4:]
    con = sqlite3.connect(DB); cur = con.cursor()

    def table_exists(name):
        return cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None

    def counts(table):
        """(jyo,rno)->(n,fin) を返す。テーブルが無ければ空dict。"""
        if not table_exists(table):
            return None
        q = f"""
          SELECT se.idJyoCD, CAST(se.idRaceNum AS INTEGER) rno,
                 COUNT(*) n,
                 SUM(CASE WHEN CAST(se.KakuteiJyuni AS INTEGER)>0 THEN 1 ELSE 0 END) fin
            FROM {table} se
           WHERE se.idYear=? AND se.idMonthDay=?
           GROUP BY se.idJyoCD, se.idRaceNum
        """
        out = {}
        for jyo, rno, n, fin in cur.execute(q, (yy, mmdd)).fetchall():
            out[(jyo, rno)] = (n, fin)
        return out

    nl = counts("NL_SE_RACE_UMA")          # 蓄積系
    rt = counts("RT_SE_RACE_UMA")          # 速報系(RT_)。未生成ならNone
    con.close()

    if not nl:
        print(f"\n{date}: NL_SE_RACE_UMA に該当レースがありません。")
        print("→ JV-Linkの差分更新(結果取り込み)がまだの可能性。更新後に再実行してください。")
        return

    rt_note = "(未生成=速報系未取得)" if rt is None else "(RT_取得あり)"
    print(f"\n=== {yy}-{mmdd[:2]}-{mmdd[2:]} レース結果の取得状況 ===")
    print(f"    NL_=蓄積系 / RT_=速報系 {rt_note}")
    keys = sorted(nl.keys(), key=lambda k: (k[0], k[1]))
    cur_jyo = None
    n_done = n_total = 0
    for k in keys:
        jyo, rno = k
        n, fin_nl = nl[k]
        fin_rt = (rt.get(k, (0, 0))[1] if rt else 0)
        name = JYO.get(jyo, f"地方({jyo})")
        if jyo != cur_jyo:
            print(f"\n[{name}]")
            cur_jyo = jyo
        n_total += 1
        fin = max(fin_nl, fin_rt)                 # NL/RTどちらかで確定していれば確定
        confirmed = (fin >= n - 1 and fin > 0)    # 取消等を許容しほぼ全馬確定なら「確定」
        if confirmed:
            n_done += 1
        src = ""
        if fin > 0:
            src = "  [" + ("NL" if fin_nl >= fin else "RT") + "]"
        mark = "確定" if confirmed else ("一部" if fin > 0 else "未確定")
        print(f"  R{rno:<2}  NL {fin_nl}/{n} · RT {fin_rt}/{n}  → {mark}{src}")
    print(f"\n--- 集計: {n_done}/{n_total} レースが確定 ---")
    if n_done == n_total:
        print("全レース確定。回顧ダッシュボードを生成できます。")
    elif n_done > 0:
        print("一部未確定。確定レースのみ回顧生成できます（時間をおいて再取得推奨）。")
    else:
        print("結果未取り込み。速報系(RT_)の取得 or 蓄積系の再取得を実行してから再確認してください。")


if __name__ == "__main__":
    main()
