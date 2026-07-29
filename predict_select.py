# -*- coding: utf-8 -*-
"""
predict_select.py ― 予想対象レースの対話セレクタ（会場・レースをまとめて選択）
==============================================================
race.db から「これから予想できる（結果未確定）」レースを会場単位で一覧し、
番号で会場を選び、レースを all / 7-12 / 7,9,11 のように柔軟指定して、
選んだ全レースを jv_export で input フォルダに一括出力する。
バッチ(run_predict_select.bat)から呼ぶ想定。将来のUI自動化の土台。
"""
import sqlite3, os, sys, subprocess, datetime

SD = os.path.dirname(os.path.abspath(__file__))
DB = r"C:\Users\r-ito\JVLinkToSQLite\race.db"
INPUT = os.path.join(SD, "input")
JYO = {"01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
       "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉"}


def predictable(cur):
    """(date, jyo) -> [(rno, n, name), ...] の未確定レース一覧。"""
    cutoff = (datetime.date.today() - datetime.timedelta(days=3)).strftime("%Y%m%d")
    q = """
      SELECT se.idYear, se.idMonthDay, se.idJyoCD, se.idRaceNum, COUNT(*) n,
             SUM(CASE WHEN CAST(se.KakuteiJyuni AS INTEGER)>0 THEN 1 ELSE 0 END) fin
        FROM NL_SE_RACE_UMA se
       WHERE (se.idYear||se.idMonthDay) >= ?
       GROUP BY se.idYear, se.idMonthDay, se.idJyoCD, se.idKaiji, se.idNichiji, se.idRaceNum
      HAVING fin=0
       ORDER BY se.idYear, se.idMonthDay, se.idJyoCD, CAST(se.idRaceNum AS INTEGER)
    """
    rows = cur.execute(q, (cutoff,)).fetchall()   # 先に全件取得（内側クエリでカーソルを潰さない）
    cur2 = cur.connection.cursor()
    groups = {}
    for yy, md, jyo, rno, n, fin in rows:
        if jyo not in JYO:
            continue
        ra = cur2.execute("SELECT RaceInfoHondai,RaceInfoRyakusyo10 FROM NL_RA_RACE "
                          "WHERE idYear=? AND idMonthDay=? AND idJyoCD=? AND idRaceNum=? LIMIT 1",
                          (yy, md, jyo, rno)).fetchone()
        nm = ((ra[0] or ra[1]) if ra else "").strip()
        groups.setdefault((yy + md, jyo), []).append((int(rno), n, nm))
    return groups


def parse_races(s, avail):
    """'all' / '7-12' / '7,9,11' / '7' を レース番号リストへ。avail=そのカードの実在R集合。"""
    s = s.strip().lower()
    if s in ("all", "a", "*", "全部", "すべて"):
        return sorted(avail)
    out = set()
    for part in s.replace("、", ",").replace("　", " ").replace(" ", ",").split(","):
        part = part.strip().lstrip("rR")
        if not part:
            continue
        if "-" in part or "~" in part or "〜" in part:
            part = part.replace("~", "-").replace("〜", "-")
            try:
                a, b = part.split("-")
                for x in range(int(a.strip("rR ")), int(b.strip("rR ")) + 1):
                    out.add(x)
            except Exception:
                pass
        else:
            try:
                out.add(int(part.strip("rR ")))
            except Exception:
                pass
    return sorted(x for x in out if x in avail)


def main():
    if not os.path.exists(DB):
        print("race.db が見つかりません:", DB); sys.exit(1)
    os.makedirs(INPUT, exist_ok=True)
    con = sqlite3.connect(DB); cur = con.cursor()
    groups = predictable(cur)
    if not groups:
        print("\n予想できるレース（結果未確定）がありません。週末の出馬表発表後に再実行してください。")
        return
    keys = sorted(groups.keys())
    print("\n=== 予想できる会場（結果未確定）===")
    for i, (d, jyo) in enumerate(keys, 1):
        rr = groups[(d, jyo)]
        ds = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        print(f"  [{i:2d}] {ds} {JYO[jyo]}  ({len(rr)}レース: R{rr[0][0]}-R{rr[-1][0]})")
    sel = input("\n会場を選択（番号・複数可 例 1,3）: ").strip()
    chosen = []
    for p in sel.replace("、", ",").replace(" ", ",").split(","):
        p = p.strip()
        if p.isdigit() and 1 <= int(p) <= len(keys):
            chosen.append(keys[int(p) - 1])
    if not chosen:
        print("会場が選ばれませんでした。"); return

    targets = []  # (date, jyo, rno)
    for (d, jyo) in chosen:
        rr = groups[(d, jyo)]
        avail = {r[0] for r in rr}
        print(f"\n--- {d[:4]}-{d[4:6]}-{d[6:]} {JYO[jyo]} ---")
        print("  " + "  ".join(f"R{r[0]}({r[1]}){('/'+r[2]) if r[2] else ''}" for r in rr))
        rs = input("  買うレース（all / 7-12 / 7,9,11）: ")
        for rno in parse_races(rs, avail):
            targets.append((d, jyo, rno))
    con.close()

    if not targets:
        print("レースが選ばれませんでした。"); return
    print(f"\n=== 出力対象 {len(targets)}レース ===")
    for d, jyo, rno in targets:
        print(f"  {d} {JYO[jyo]} R{rno}")
    if input("\nこの内容でエクスポートしますか？ (y/n): ").strip().lower() not in ("y", "yes", ""):
        print("中止しました。"); return

    ok = ng = 0
    for d, jyo, rno in targets:
        print(f"--- exporting {JYO[jyo]} {d} R{rno} ---")
        r = subprocess.run([sys.executable, os.path.join(SD, "jv_export.py"),
                            "--date", d, "--jyo", jyo, "--r", str(rno),
                            "--outdir", INPUT])
        if r.returncode == 0:
            ok += 1
        else:
            ng += 1
    print(f"\n完了: 出力{ok}レース / 失敗{ng}。 input\\ に生成しました。")
    print("次: SmartRC・馬場を用意して run_predict_dash.bat（採点→ダッシュボード）")


if __name__ == "__main__":
    main()
