# -*- coding: utf-8 -*-
"""
roi_backtest.py ― JV完結パイプラインの大規模ROIバックテスト
==============================================================
指定期間のJRAレース（結果確定済み）について、
  jv_export.py で入力生成 → score_horse_v3.py で採点 → bet_recon.reconstruct で買い判定
を再現し、race.db の実着順・単勝オッズ・複勝配当(NL_HR_PAY)で
  軸勝率 / 軸複勝率 / 軸単勝ROI / 軸複勝ROI
を判定別（購入推奨/非推奨）＋全体で集計する。

注意:
  - 買い判定は「軸のコース特徴pts」と「推定人気」を使う。ライブはSmartRCの想定人気を使うが、
    過去レースの想定人気は保存が無いため、本バックテストは【確定人気を推定人気の代用】とする
    （実際のライブ判定とは差が出る。上限側の目安として解釈）。
  - 馬場は各予想で --baba 良 固定（予想時点の想定に相当）。
  - resumable: roi_rows.jsonl に1行ずつ記録し、再実行で続きから。

使い方:
  python roi_backtest.py --from 20260501 --to 20260630 [--limit 300]
  python roi_backtest.py report        # 集計のみ（roi_rows.jsonl から）
"""
import sqlite3, os, sys, json, subprocess, tempfile, argparse

SD = os.path.dirname(os.path.abspath(__file__))
DB = r"C:\Users\r-ito\JVLinkToSQLite\race.db"
ROWS = os.path.join(SD, "roi_rows.jsonl")
JYO_ROMAJI = {"01": "sp", "02": "hk", "03": "fk", "04": "ng", "05": "tk",
              "06": "nk", "07": "ck", "08": "ky", "09": "hs", "10": "ok"}


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


def race_facts(cur, yy, md, jyo, rno):
    """馬番→人気, 馬番→(着順,単勝倍率), 馬番→複勝倍率 を返す。"""
    ninki, fin = {}, {}
    for r in cur.execute(
            "SELECT Umaban,Ninki,KakuteiJyuni,Odds FROM NL_SE_RACE_UMA "
            "WHERE idYear=? AND idMonthDay=? AND idJyoCD=? AND idRaceNum=?",
            (yy, md, jyo, rno)):
        try:
            u = int((r[0] or "").strip())
        except ValueError:
            continue
        try:
            ninki[u] = int((r[1] or "").strip())
        except ValueError:
            ninki[u] = None
        kj = (r[2] or "").strip()
        od = (r[3] or "").strip()
        fin[u] = (int(kj) if kj.isdigit() and int(kj) > 0 else None,
                  (int(od) / 10.0) if od.isdigit() and int(od) > 0 else None)
    # 複勝配当（NL_HR_PAY）
    fuk = {}
    hp = cur.execute(
        "SELECT PayFukusyo0Umaban,PayFukusyo0Pay,PayFukusyo1Umaban,PayFukusyo1Pay,"
        "PayFukusyo2Umaban,PayFukusyo2Pay,PayFukusyo3Umaban,PayFukusyo3Pay,"
        "PayFukusyo4Umaban,PayFukusyo4Pay FROM NL_HR_PAY "
        "WHERE idYear=? AND idMonthDay=? AND idJyoCD=? AND idRaceNum=? LIMIT 1",
        (yy, md, jyo, rno)).fetchone()
    if hp:
        for k in range(5):
            ub = (hp[k * 2] or "").strip(); pay = (hp[k * 2 + 1] or "").strip()
            if ub.isdigit() and pay.isdigit() and int(pay) > 0:
                fuk[int(ub)] = int(pay) / 100.0   # 倍率
    return ninki, fin, fuk


def build_payouts(cur, yy, md, jyo, rno):
    """NL_HR_PAY → bet_recon.eval_race が使う払戻dict（組番-配当円）。"""
    hp = cur.execute("SELECT * FROM NL_HR_PAY WHERE idYear=? AND idMonthDay=? "
                     "AND idJyoCD=? AND idRaceNum=? LIMIT 1",
                     (yy, md, jyo, rno)).fetchone()
    po = {'tansho': [], 'fukusho': [], 'umaren': [], 'wide': [],
          'umatan': [], 'sanrenpuku': [], 'sanrentan': []}
    if not hp:
        return po
    keys = hp.keys()

    def g(name):
        return ((hp[name] or "").strip() if name in keys else "")

    def combo(kumi, k):
        kumi = kumi.strip()
        if len(kumi) == 2 * k and kumi.isdigit():
            return "-".join(str(int(kumi[i * 2:i * 2 + 2])) for i in range(k))
        return None

    def add_uma(dst, cnt, pre):   # 単勝/複勝: Umaban/Pay
        for n in range(cnt):
            ub = g("%s%dUmaban" % (pre, n)); pay = g("%s%dPay" % (pre, n))
            if ub.isdigit() and pay.isdigit() and int(pay) > 0:
                po[dst].append((str(int(ub)), int(pay)))

    def add_kumi(dst, cnt, pre, k):  # 連系: Kumi/Pay
        for n in range(cnt):
            c = combo(g("%s%dKumi" % (pre, n)), k); pay = g("%s%dPay" % (pre, n))
            if c and pay.isdigit() and int(pay) > 0:
                po[dst].append((c, int(pay)))

    add_uma('tansho', 3, 'PayTansyo')
    add_uma('fukusho', 5, 'PayFukusyo')
    add_kumi('umaren', 3, 'PayUmaren', 2)
    add_kumi('wide', 7, 'PayWide', 2)
    add_kumi('umatan', 6, 'PayUmatan', 2)
    add_kumi('sanrenpuku', 3, 'PaySanrenpuku', 3)
    add_kumi('sanrentan', 6, 'PaySanrentan', 3)
    return po


def collect(dfrom, dto, limit):
    import bet_recon as BR
    import pandas as pd
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row; cur = con.cursor()
    races = enumerate_races(cur, dfrom, dto, limit)
    done = set()
    if os.path.exists(ROWS):
        for l in open(ROWS, encoding="utf-8"):
            try: done.add(json.loads(l)["rid"])
            except Exception: pass
    out = open(ROWS, "a", encoding="utf-8")
    ok = fail = 0
    for (yy, md, jyo, rno, n) in races:
        rid = "%s%s_%s%s" % (yy, md, JYO_ROMAJI[jyo], str(int(rno)))
        if rid in done:
            continue
        with tempfile.TemporaryDirectory() as td:
            # 1) 入力生成
            e = subprocess.run([sys.executable, os.path.join(SD, "jv_export.py"),
                                "--date", yy + md, "--jyo", jyo, "--r", str(int(rno)),
                                "--outdir", td], capture_output=True, text=True)
            def f(pre):
                p = os.path.join(td, "%s_%s%s_%s%s.csv" % (pre, yy, md, JYO_ROMAJI[jyo], str(int(rno))))
                return p if os.path.exists(p) else None
            kako, shu, sak, wood = f("過去走"), f("出馬表"), f("坂路"), f("ウッド")
            if not (kako and shu):
                fail += 1; print("skip(export)", rid); continue
            # 2) 採点
            cmd = [sys.executable, os.path.join(SD, "score_horse_v3.py"),
                   "--excel", kako, "--shutuba", shu, "--outdir", td, "--baba", "良"]
            if sak: cmd += ["--sakuro", sak]
            if wood: cmd += ["--wood", wood]
            sc = subprocess.run(cmd, capture_output=True, text=True)
            jp = os.path.join(td, "horses_data.json")
            if not os.path.exists(jp):
                fail += 1
                print("FAIL(score)", rid, "|", (sc.stderr or "")[-200:].replace("\n", " "))
                continue
            d = json.load(open(jp, encoding="utf-8"))

        ninki, fin, fuk = race_facts(cur, yy, md, jyo, rno)
        # ev 構築（推定人気=確定人気の代用）
        ev = []
        for h in d["horses"]:
            u = h.get("馬番")
            if u is None:
                continue
            try: u = int(u)
            except (TypeError, ValueError): continue
            ev.append({"馬名": h.get("馬名"), "馬番": u, "スコア": h.get("総合スコア"),
                       "順位予想": h.get("順位予想"), "枠番": h.get("枠番"),
                       "コース特徴pts": h.get("コース特徴pts"),
                       "SmartRC推定人気順": ninki.get(u)})
        if len(ev) < 5:
            fail += 1; continue
        try:
            rc = BR.reconstruct(ev)
        except Exception as ex:
            fail += 1; print("FAIL(recon)", rid, ex); continue
        if not rc:
            fail += 1; continue
        umA = rc["umA"]
        f_fin, f_tan = fin.get(umA, (None, None))
        # 券種フォーメーションROI（推奨券種の実配当）
        bets = {}
        try:
            df_rows = [{"入線順位": v[0], "馬番": u} for u, v in fin.items() if v[0]]
            if len(df_rows) >= 3:
                res_df = pd.DataFrame(df_rows)
                payouts = build_payouts(cur, yy, md, jyo, rno)
                er = BR.eval_race(rc, res_df, payouts)
                if er:
                    bets = {k: [v[0], v[1]] for k, v in er["bets"].items()}  # 券種->[点数,払戻]
        except Exception as ex:
            print("warn(eval_race)", rid, ex)
        rec = {"rid": rid, "verdict": rc["verdict"], "umA": umA,
               "fin": f_fin, "tan": f_tan, "fuk": fuk.get(umA),
               "srcA": rc.get("srcA"), "bets": bets}
        out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
        ok += 1
        if ok % 20 == 0:
            print("... %d races done" % ok)
    out.close(); con.close()
    print("collect 完了: ok=%d fail=%d" % (ok, fail))


def report():
    from collections import defaultdict
    buckets = defaultdict(list); allrows = []
    if not os.path.exists(ROWS):
        print("roi_rows.jsonl が無い。先に collect を実行。"); return
    for l in open(ROWS, encoding="utf-8"):
        r = json.loads(l)
        if r.get("fin") is None:
            continue  # 軸が取消/除外等
        buckets[r["verdict"]].append(r); allrows.append(r)

    def roi(b):
        n = len(b)
        if not n: return None
        win = sum(1 for x in b if x["fin"] == 1)
        plc = sum(1 for x in b if x["fin"] and x["fin"] <= 3)
        tr = sum((x["tan"] if x["fin"] == 1 and x["tan"] else 0) for x in b)
        fr = sum((x["fuk"] if x["fin"] and x["fin"] <= 3 and x["fuk"] else 0) for x in b)
        return dict(n=n, win=100*win/n, plc=100*plc/n, tanROI=100*tr/n, fukROI=100*fr/n)

    lines = ["# JV ROIバックテスト（軸=モデル偏差値1位 / %dR）\n" % len(allrows)]
    lines.append("| 判定 | R数 | 軸勝率 | 軸複勝率 | 軸単勝ROI | 軸複勝ROI |")
    lines.append("|---|--:|--:|--:|--:|--:|")
    for v in ("購入推奨", "購入非推奨"):
        m = roi(buckets.get(v, []))
        if m:
            lines.append("| %s | %d | %.0f%% | %.0f%% | %.0f%% | %.0f%% |"
                         % (v, m["n"], m["win"], m["plc"], m["tanROI"], m["fukROI"]))
    m = roi(allrows)
    if m:
        lines.append("| 全レース | %d | %.0f%% | %.0f%% | %.0f%% | %.0f%% |"
                     % (m["n"], m["win"], m["plc"], m["tanROI"], m["fukROI"]))
    lines.append("\n※軸単勝ROI・複勝ROIは100%超で控除率を越える妙味。")
    lines.append("※推定人気は確定人気で代用（ライブのSmartRC想定人気とは差あり）。")

    # ── 券種フォーメーションROI（推奨券種を各1点購入した場合） ──
    def form_agg(rows):
        agg = defaultdict(lambda: [0, 0.0])  # 券種->[総点数,総払戻]
        for r in rows:
            for bt, pr in (r.get("bets") or {}).items():
                agg[bt][0] += pr[0]; agg[bt][1] += pr[1]
        return agg
    order_bt = ["馬連", "ワイド", "馬単", "三連複", "三連単"]
    lines.append("\n## 券種フォーメーションROI（軸流し・各組1点購入）")
    for label, rows in (("購入推奨", buckets.get("購入推奨", [])),
                        ("全レース", allrows)):
        agg = form_agg(rows)
        if not any(agg[bt][0] for bt in order_bt):
            continue
        lines.append("\n### %s（%dR）" % (label, len(rows)))
        lines.append("| 券種 | 総点数 | 総払戻 | ROI |")
        lines.append("|---|--:|--:|--:|")
        for bt in order_bt:
            pts, ret = agg[bt]
            if pts:
                lines.append("| %s | %d | %d | %.0f%% |" % (bt, pts, int(ret), 100 * ret / (pts * 100)))
    lines.append("\n※フォーメーションROI=総払戻÷(総点数×100)。確定配当はNL_HR_PAYから取得。")
    rep = os.path.join(SD, "roi_backtest_report.md")
    open(rep, "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines)); print("\nwrote", rep)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", help="run(既定) / report")
    ap.add_argument("--from", dest="dfrom", default="20260501")
    ap.add_argument("--to", dest="dto", default="20260630")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "report":
        report()
    else:
        collect(a.dfrom, a.dto, a.limit)
        report()
