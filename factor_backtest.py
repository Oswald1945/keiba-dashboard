# -*- coding: utf-8 -*-
"""
factor_backtest.py ― 因子有効性の大規模測定（JV完結）
==============================================================
指定期間のJRAレース（結果確定済み）について
  jv_export.py → score_horse_v3.py で採点し、
  各馬の「因子pts一式 + 実着順 + 人気 + 単勝」を factor_rows.jsonl に1行ずつ記録する。

roi_backtest.py と同じ列挙・採点パイプラインを流用。
resumable: factor_rows.jsonl に rid を記録し、再実行で続きから。

集計は factor_analysis.py（DB不要・factor_rows.jsonl のみ）で行う。

使い方:
  python factor_backtest.py --from 20260401 --to 20260628 [--limit 300]
"""
import sqlite3, os, sys, json, subprocess, tempfile, argparse

SD = os.path.dirname(os.path.abspath(__file__))
DB = r"C:\Users\r-ito\JVLinkToSQLite\race.db"
ROWS = os.path.join(SD, "factor_rows.jsonl")
JYO_ROMAJI = {"01": "sp", "02": "hk", "03": "fk", "04": "ng", "05": "tk",
              "06": "nk", "07": "ck", "08": "ky", "09": "hs", "10": "ok"}

# horses_data.json の各馬エントリに入っている因子pts（+総合スコア）
FACTOR_KEYS = [
    "最高出力pts", "クラスpts", "時計pts", "コース特徴pts", "トラックバイアスpts",
    "斤量pts", "距離pts", "コース適性pts", "臨戦pts", "人気補正pts", "騎手pts",
    "馬体重pts", "継続pts", "着差pts", "枠順pts", "昇級pts", "クラス適応pts",
    "上がりpts", "馬場適性pts", "SmartRC評価pts", "総合スコア",
    "補正タイム最良",   # P1較正・検証用（絶対水準devの母集団分布確認）
]


def enumerate_races(cur, dfrom, dto, limit):
    q = """
      SELECT se.idYear, se.idMonthDay, se.idJyoCD, se.idRaceNum, COUNT(*) n
        FROM NL_SE_RACE_UMA se
       WHERE se.idJyoCD IN ('01','02','03','04','05','06','07','08','09','10')
         AND (se.idYear||se.idMonthDay) BETWEEN ? AND ?
       GROUP BY se.idYear, se.idMonthDay, se.idJyoCD, se.idKaiji, se.idNichiji, se.idRaceNum
      HAVING SUM(CASE WHEN CAST(se.KakuteiJyuni AS INTEGER)>0 THEN 1 ELSE 0 END) >= 5
       ORDER BY (se.idYear||se.idMonthDay), se.idJyoCD, CAST(se.idRaceNum AS INTEGER)
    """
    rows = cur.execute(q, (dfrom, dto)).fetchall()
    if limit:
        rows = rows[:limit]
    return rows


def race_results(cur, yy, md, jyo, rno):
    """馬番 -> (着順, 人気, 単勝倍率)。"""
    out = {}
    for r in cur.execute(
            "SELECT Umaban,KakuteiJyuni,Ninki,Odds FROM NL_SE_RACE_UMA "
            "WHERE idYear=? AND idMonthDay=? AND idJyoCD=? AND idRaceNum=?",
            (yy, md, jyo, rno)):
        try:
            u = int((r[0] or "").strip())
        except ValueError:
            continue
        kj = (r[1] or "").strip(); nk = (r[2] or "").strip(); od = (r[3] or "").strip()
        fin = int(kj) if kj.isdigit() and int(kj) > 0 else None
        ninki = int(nk) if nk.isdigit() and int(nk) > 0 else None
        tan = (int(od) / 10.0) if od.isdigit() and int(od) > 0 else None
        out[u] = (fin, ninki, tan)
    return out


def collect(dfrom, dto, limit, out_path=None):
    out_path = out_path or ROWS
    con = sqlite3.connect(DB); cur = con.cursor()
    races = enumerate_races(cur, dfrom, dto, limit)
    done = set()
    if os.path.exists(out_path):
        for l in open(out_path, encoding="utf-8"):
            try: done.add(json.loads(l)["rid"])
            except Exception: pass
    out = open(out_path, "a", encoding="utf-8")
    ok = fail = nrows = 0
    for (yy, md, jyo, rno, n) in races:
        rid = "%s%s_%s%s" % (yy, md, JYO_ROMAJI[jyo], str(int(rno)))
        if rid in done:
            continue
        with tempfile.TemporaryDirectory() as td:
            e = subprocess.run([sys.executable, os.path.join(SD, "jv_export.py"),
                                "--date", yy + md, "--jyo", jyo, "--r", str(int(rno)),
                                "--outdir", td], capture_output=True, text=True)

            def f(pre):
                p = os.path.join(td, "%s_%s%s_%s%s.csv" % (pre, yy, md, JYO_ROMAJI[jyo], str(int(rno))))
                return p if os.path.exists(p) else None
            kako, shu, sak, wood = f("過去走"), f("出馬表"), f("坂路"), f("ウッド")
            if not (kako and shu):
                fail += 1; print("skip(export)", rid); continue
            cmd = [sys.executable, os.path.join(SD, "score_horse_v3.py"),
                   "--excel", kako, "--shutuba", shu, "--outdir", td, "--baba", "良"]
            if sak: cmd += ["--sakuro", sak]
            if wood: cmd += ["--wood", wood]
            sc = subprocess.run(cmd, capture_output=True, text=True)
            jp = os.path.join(td, "horses_data.json")
            if not os.path.exists(jp):
                fail += 1
                print("FAIL(score)", rid, "|", (sc.stderr or "")[-160:].replace("\n", " "))
                continue
            d = json.load(open(jp, encoding="utf-8"))

        res = race_results(cur, yy, md, jyo, rno)
        wrote_any = False
        for h in d["horses"]:
            u = h.get("馬番")
            if u is None:
                continue
            try: u = int(u)
            except (TypeError, ValueError): continue
            fin, ninki, tan = res.get(u, (None, None, None))
            if fin is None:
                continue  # 取消/除外
            row = {"rid": rid, "umaban": u, "着順": fin, "人気": ninki, "単勝": tan}
            for k in FACTOR_KEYS:
                v = h.get(k)
                if v is not None:
                    row[k] = v
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            nrows += 1; wrote_any = True
        if wrote_any:
            out.flush(); ok += 1
            if ok % 20 == 0:
                print("... %d races done (%d horse-rows)" % (ok, nrows))
    out.close(); con.close()
    print("collect 完了: races=%d fail=%d horse-rows=%d" % (ok, fail, nrows))
    print("→ 集計: python factor_analysis.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="dfrom", default="20260401")
    ap.add_argument("--to", dest="dto", default="20260628")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", dest="out", default=None, help="出力先(既定 factor_rows.jsonl)。検証時は別ファイルに")
    a = ap.parse_args()
    collect(a.dfrom, a.dto, a.limit, a.out)
