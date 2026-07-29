# -*- coding: utf-8 -*-
"""
dump_racemeta.py ― 条件メタのキャッシュ生成（採点なし・DB読むだけ＝高速）
==============================================================
factor_rows.jsonl と同じ期間のJRAレースについて、NL_RA_RACE から
  場 / 芝ダ / 距離 / 距離帯 / 馬場状態 / コース区分
を racemeta_cache.jsonl に1行ずつ保存。条件別ROI/重み検証（factor_segment.py）に使う。
注: 本バックテストのスコアは --baba 良 固定で採点済み。ここで取るのは【実際の馬場】。

使い方: python dump_racemeta.py --from 20250601 --to 20260628
"""
import sqlite3, os, json, argparse
import roi_backtest as RB
import baseline_time as bt

SD = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(SD, "racemeta_cache.jsonl")


def dist_band(kyori):
    try:
        k = int(kyori)
    except Exception:
        return "?"
    if k <= 1400: return "短"
    if k <= 1800: return "マ"
    if k <= 2200: return "中"
    return "長"


def main(dfrom, dto, limit):
    con = sqlite3.connect(RB.DB); con.row_factory = sqlite3.Row; cur = con.cursor()
    races = RB.enumerate_races(cur, dfrom, dto, limit)
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            try: done.add(json.loads(l)["rid"])
            except Exception: pass
    out = open(OUT, "a", encoding="utf-8")
    n = 0
    for (yy, md, jyo, rno, cnt) in races:
        rid = "%s%s_%s%s" % (yy, md, RB.JYO_ROMAJI[jyo], str(int(rno)))
        if rid in done:
            continue
        ra = cur.execute(
            "SELECT * FROM NL_RA_RACE WHERE idYear=? AND idMonthDay=? "
            "AND idJyoCD=? AND idRaceNum=? LIMIT 1",
            (yy, md, jyo, rno)).fetchone()
        if ra is None:
            continue
        tt = bt.track_type(ra["TrackCD"]) or "?"
        kyori = (ra["Kyori"] or "").strip()
        babac = bt.baba_code(ra)
        baba = bt.BABA_NAME.get(babac, "?")
        try:
            cls_full = bt.class_key(ra)          # 例 "3歳-G1" / "古馬-一勝"
            cls = cls_full.split("-")[-1]         # クラス部分 G1/G2/G3/OP/三勝/二勝/一勝/未勝利/新馬/他
        except Exception:
            cls_full = "?"; cls = "?"
        try: kaiji = int((ra["idKaiji"] or "0").strip())
        except Exception: kaiji = 0
        try: nichiji = int((ra["idNichiji"] or "0").strip())
        except Exception: nichiji = 0
        rec = {"rid": rid, "jyo": jyo, "jyo_name": bt.JYO_NAME.get(jyo, jyo),
               "surface": tt, "kyori": kyori, "band": dist_band(kyori),
               "baba": baba, "course_ku": (ra["CourseKubunCD"] or "").strip(),
               "cls": cls, "cls_full": cls_full, "kaiji": kaiji, "nichiji": nichiji}
        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
        n += 1
        if n % 500 == 0:
            out.flush(); print("... %d races" % n)
    out.close(); con.close()
    print("完了: %d races -> %s" % (n, OUT))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="dfrom", default="20250601")
    ap.add_argument("--to", dest="dto", default="20260628")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    main(a.dfrom, a.dto, a.limit)
