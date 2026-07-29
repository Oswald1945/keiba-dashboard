# -*- coding: utf-8 -*-
"""
dump_payouts.py ― 払戻キャッシュ生成（採点なし・DB読むだけ＝高速）
==============================================================
factor_rows.jsonl と同じ期間のJRAレースについて、NL_HR_PAY の確定配当
（単勝/複勝/馬連/ワイド/馬単/三連複/三連単）を payouts_cache.jsonl に1行ずつ保存。
これで重み変更後の「軸単複＋連系フォーメーションの実測ROI」を全部オフラインで比較できる。

使い方: python dump_payouts.py --from 20250601 --to 20260628
"""
import sqlite3, os, json, argparse
import roi_backtest as RB   # build_payouts / enumerate_races を流用

SD = os.path.dirname(os.path.abspath(__file__))
DB = RB.DB
OUT = os.path.join(SD, "payouts_cache.jsonl")


def main(dfrom, dto, limit):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row; cur = con.cursor()
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
        po = RB.build_payouts(cur, yy, md, jyo, rno)
        out.write(json.dumps({"rid": rid, "payouts": po}, ensure_ascii=False) + "\n")
        n += 1
        if n % 500 == 0:
            out.flush(); print("... %d races dumped" % n)
    out.close(); con.close()
    print("完了: %d races -> %s" % (n, OUT))
    print("→ 次: python factor_roi_offline.py で重み別の実測ROIを比較")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="dfrom", default="20250601")
    ap.add_argument("--to", dest="dto", default="20260628")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    main(a.dfrom, a.dto, a.limit)
