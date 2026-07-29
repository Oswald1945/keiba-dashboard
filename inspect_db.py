# -*- coding: utf-8 -*-
"""
race.db の構造を把握するための調査スクリプト。
- 全テーブルの一覧と行数
- 中核テーブル(NL_RA_RACE / NL_SE_RACE_UMA など)のカラム定義
- 中核テーブルのサンプル数行
を db_schema.txt に書き出す（このスクリプトと同じフォルダ）。
出力は Claude が読んで baseline_time.py / jv_export.py を設計するために使う。
"""
import sqlite3
import os
import sys

DB = r"C:\Users\r-ito\JVLinkToSQLite\race.db"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "db_schema.txt")

# 中核テーブル（存在すればカラム定義とサンプルを詳しく出す）
CORE = [
    "NL_HC_HANRO",       # 坂路調教
    "NL_WC_WOOD",        # ウッドチップ調教
    "NL_CS_COURSE",      # コースマスタ
]

def w(f, s=""):
    f.write(s + "\n")

def main():
    if not os.path.exists(DB):
        print("DB not found:", DB)
        sys.exit(1)

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    with open(OUT, "w", encoding="utf-8") as f:
        w(f, "=== race.db inspection ===")
        w(f, "DB path: " + DB)
        w(f, "DB size (MB): %.1f" % (os.path.getsize(DB) / 1024 / 1024))
        w(f)

        # 全テーブル一覧＋行数
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]
        w(f, "=== tables (%d) with row counts ===" % len(tables))
        counts = {}
        for t in tables:
            try:
                cur.execute('SELECT COUNT(*) FROM "%s"' % t)
                c = cur.fetchone()[0]
            except Exception as e:
                c = "ERR:%s" % e
            counts[t] = c
            w(f, "  %-28s %s" % (t, c))
        w(f)

        # 中核テーブルの詳細
        for t in CORE:
            if t not in tables:
                # 部分一致で候補を探す（坂路/ウッド等は名称違いがあり得る）
                cand = [x for x in tables if t.split("_")[1][:3] in x.upper()]
                w(f, "### %s : NOT FOUND (候補: %s)" % (t, ", ".join(cand) if cand else "なし"))
                w(f)
                continue
            w(f, "### %s (rows=%s) ###" % (t, counts.get(t)))
            cur.execute('PRAGMA table_info("%s")' % t)
            cols = cur.fetchall()
            w(f, "-- columns (%d) --" % len(cols))
            for col in cols:
                w(f, "  %-24s %s" % (col["name"], col["type"]))
            # サンプル2行（値は各120文字までに丸める）
            w(f, "-- sample rows (up to 2) --")
            try:
                cur.execute('SELECT * FROM "%s" LIMIT 2' % t)
                rows = cur.fetchall()
                colnames = [d[0] for d in cur.description]
                for ri, row in enumerate(rows):
                    w(f, "  [row %d]" % ri)
                    for cn in colnames:
                        v = row[cn]
                        sv = "" if v is None else str(v)
                        if len(sv) > 120:
                            sv = sv[:120] + "...(truncated)"
                        w(f, "    %-24s = %s" % (cn, sv))
            except Exception as e:
                w(f, "  sample error: %s" % e)
            w(f)

    con.close()
    print("Wrote:", OUT)

if __name__ == "__main__":
    main()
