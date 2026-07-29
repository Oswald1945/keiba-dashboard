# -*- coding: utf-8 -*-
"""
baseline_time.py  ―  独自「基準タイム」＋「馬場差補正」テーブルの生成
=====================================================================
案2（TARGET全廃・JV完結）の中核。race.db の 15年分レース結果から、

  ・TF_BASELINE     : クラス×場所×距離×芝ダ ごとの「良馬場の基準タイム」
  ・TF_BABA_ADJUST  : 場所×距離×芝ダ×馬場状態 ごとの「良馬場比の遅速(秒)」

を算出して race.db に書き戻す。これらを使うと、各馬の過去走を
   独自補正タイム = 基準タイム − (実走タイム − 馬場補正)
に換算でき、TARGET の 補正タイム/TGX の代替になる。

設計メモ:
  - バケット基準は「馬場差」を吸収しないため、馬場差は TF_BABA_ADJUST で明示補正する。
  - ペース(PCI)補正は後段(スコアラー側)で別途行う。ここでは素の時計の基準づくりに徹する。
  - 芝/ダートの障害(障害競走)は対象外。地方・海外(場コード>10)も対象外。
  - 実行は race.db に対して行う（DBは書き換わるが、追加テーブルのみで既存は不変）。

出力:
  - race.db 内 TF_BASELINE / TF_BABA_ADJUST（既存なら作り直し）
  - baseline_summary.txt（このスクリプトと同じフォルダ。人間/Claudeの検証用）
"""

import sqlite3
import os
import sys
import statistics
from collections import defaultdict

DB = r"C:\Users\r-ito\JVLinkToSQLite\race.db"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline_summary.txt")

# JRA10場のみ対象（01札幌〜10小倉）
JRA_JYO = {"01", "02", "03", "04", "05", "06", "07", "08", "09", "10"}
JYO_NAME = {
    "01": "札幌", "02": "函館", "03": "福島", "04": "新潟", "05": "東京",
    "06": "中山", "07": "中京", "08": "京都", "09": "阪神", "10": "小倉",
}

# ── コード変換 ─────────────────────────────────────────────

def track_type(trackcd):
    """TrackCD → '芝' / 'ダ' / None(障害・不明)"""
    try:
        cd = int(trackcd)
    except (TypeError, ValueError):
        return None
    if 10 <= cd <= 22:
        return "芝"
    if 23 <= cd <= 29:
        return "ダ"
    return None  # 51〜59 障害 等は対象外


def baba_code(row):
    """芝なら芝馬場、ダならダート馬場の状態コード(1良2稍3重4不)。'0'/空は None。"""
    tt = track_type(row["TrackCD"])
    v = row["TenkoBabaSibaBabaCD"] if tt == "芝" else row["TenkoBabaDirtBabaCD"]
    v = (v or "").strip()
    return v if v in ("1", "2", "3", "4") else None


BABA_NAME = {"1": "良", "2": "稍重", "3": "重", "4": "不良"}


def age_group(syubetu):
    """JyokenInfoSyubetuCD → 年齢区分"""
    return {"11": "2歳", "12": "3歳", "13": "古馬", "14": "古馬"}.get((syubetu or "").strip(), "他")


# 競走条件コード → クラス名（優先度高い順に判定）
_JYOKEN_PRIO = ["999", "016", "010", "005", "703", "701", "702"]
_JYOKEN_LABEL = {
    "999": "OP", "016": "3勝", "010": "2勝", "005": "1勝",
    "703": "未勝利", "701": "新馬", "702": "未出走",
}
_GRADE = {"A": "G1", "B": "G2", "C": "G3"}


def class_key(row):
    """クラス名を返す。重賞は G1/G2/G3、それ以外はリステッド/特別含めOP/条件クラスへ。"""
    grade = (row["GradeCD"] or "").strip()
    if grade in _GRADE:
        return _GRADE[grade]
    age = age_group(row["JyokenInfoSyubetuCD"])
    codes = [(row["JyokenInfoJyokenCD%d" % i] or "").strip() for i in range(5)]
    best = None
    for p in _JYOKEN_PRIO:
        if p in codes:
            best = p
            break
    cls = _JYOKEN_LABEL.get(best, "他")
    # グレード欄が A/B/C 以外で埋まっている(L・重賞未区分など)は OP 扱い
    if grade and grade not in _GRADE and cls in ("他", "OP"):
        cls = "OP"
    return "%s-%s" % (age, cls)


def parse_time(s):
    """走破タイム 'MSSF'(分・秒・1/10秒) → 秒(float)。無効は None。
    例 '1497' → 1分49秒7 = 109.7 / '2035' → 2分03秒5 = 123.5"""
    s = (s or "").strip()
    if not s or not s.isdigit() or int(s) == 0:
        return None
    if len(s) < 4:
        s = s.zfill(4)
    mm = int(s[:-3])
    ss = int(s[-3:-1])
    ff = int(s[-1])
    if ss >= 60:
        return None
    return mm * 60 + ss + ff / 10.0


def q(vals, p):
    """百分位(0-100)。statistics.quantiles を使い、サンプル僅少でも落ちないように。"""
    vals = sorted(vals)
    n = len(vals)
    if n == 0:
        return None
    if n == 1:
        return vals[0]
    # 位置補間
    idx = (p / 100.0) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return vals[lo] * (1 - frac) + vals[hi] * frac


# ── 本体 ─────────────────────────────────────────────────

def main():
    if not os.path.exists(DB):
        print("DB not found:", DB)
        sys.exit(1)

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    sql = """
        SELECT ra.idYear, ra.idMonthDay, ra.idJyoCD, ra.idKaiji, ra.idNichiji, ra.idRaceNum,
               ra.Kyori, ra.TrackCD, ra.CourseKubunCD, ra.GradeCD,
               ra.JyokenInfoSyubetuCD,
               ra.JyokenInfoJyokenCD0, ra.JyokenInfoJyokenCD1, ra.JyokenInfoJyokenCD2,
               ra.JyokenInfoJyokenCD3, ra.JyokenInfoJyokenCD4,
               ra.TenkoBabaSibaBabaCD, ra.TenkoBabaDirtBabaCD,
               se.Time, se.KakuteiJyuni, se.IJyoCD
        FROM NL_SE_RACE_UMA se
        JOIN NL_RA_RACE ra
          ON ra.idYear=se.idYear AND ra.idMonthDay=se.idMonthDay AND ra.idJyoCD=se.idJyoCD
         AND ra.idKaiji=se.idKaiji AND ra.idNichiji=se.idNichiji AND ra.idRaceNum=se.idRaceNum
    """

    # race_id -> レース属性＋出走馬の有効タイム集合
    races = {}
    # 集計用カウンタ（サマリ用）
    cnt_rows = 0
    cnt_track = defaultdict(int)     # 芝/ダ/対象外
    cnt_class = defaultdict(int)     # クラス出現頻度（レース単位）

    for r in cur.execute(sql):
        cnt_rows += 1
        if r["idJyoCD"] not in JRA_JYO:
            continue
        tt = track_type(r["TrackCD"])
        if tt is None:
            continue
        t = parse_time(r["Time"])
        # 有効完走のみ（異常区分0・タイム有）
        if (r["IJyoCD"] or "").strip() not in ("0", ""):
            continue
        if t is None:
            continue

        rid = (r["idYear"], r["idMonthDay"], r["idJyoCD"], r["idKaiji"], r["idNichiji"], r["idRaceNum"])
        rec = races.get(rid)
        if rec is None:
            cls = class_key(r)
            rec = {
                "jyo": r["idJyoCD"],
                "kyori": (r["Kyori"] or "").strip(),
                "tt": tt,
                "cls": cls,
                "baba": baba_code(r),
                "times": [],
            }
            races[rid] = rec
            cnt_track[tt] += 1
            cnt_class[cls] += 1
        rec["times"].append(t)

    # ── バケット集計 ──
    # 基準(良馬場のみ): key=(cls,jyo,tt,kyori)
    base = defaultdict(lambda: {"win": [], "all": []})
    # 上級(G1/G2/G3/OP)をまとめたフォールバック用: key=(jyo,tt,kyori)
    base_upper = defaultdict(lambda: {"win": [], "all": []})
    # 馬場補正: key=(jyo,tt,kyori) -> baba -> [勝ちタイム]
    baba = defaultdict(lambda: defaultdict(list))

    def is_upper(cls):
        return cls in ("G1", "G2", "G3") or cls.endswith("-OP")

    for rec in races.values():
        if not rec["times"]:
            continue
        wt = min(rec["times"])           # 勝ちタイム＝最速完走
        bkey = (rec["jyo"], rec["tt"], rec["kyori"])
        if rec["baba"]:
            baba[bkey][rec["baba"]].append(wt)
        if rec["baba"] == "1":           # 基準は良馬場のみ
            key = (rec["cls"], rec["jyo"], rec["tt"], rec["kyori"])
            base[key]["win"].append(wt)
            base[key]["all"].extend(rec["times"])
            if is_upper(rec["cls"]):     # 上級はまとめてもう1本の基準を作る
                base_upper[bkey]["win"].append(wt)
                base_upper[bkey]["all"].extend(rec["times"])

    # ── TF_BASELINE 構築 ──
    baseline_rows = []
    for (cls, jyo, tt, kyori), d in base.items():
        wins = d["win"]
        alls = d["all"]
        if len(wins) < 5:                # サンプル僅少は基準にしない
            continue
        baseline_rows.append((
            cls, jyo, JYO_NAME.get(jyo, jyo), tt, kyori,
            len(wins), len(alls),
            round(statistics.median(wins), 2),          # 基準勝ちタイム
            round(q(wins, 25), 2),                       # 速い側25%（強めの勝ち馬水準）
            round(statistics.median(alls), 2),           # 標準出走馬タイム（全完走中央値）
            round(statistics.pstdev(wins), 2) if len(wins) > 1 else 0.0,
        ))

    # 上級(まとめ)バケットを class_key='上級' として追加（薄いOP/重賞のフォールバック用）
    for (jyo, tt, kyori), d in base_upper.items():
        wins = d["win"]
        alls = d["all"]
        if len(wins) < 8:
            continue
        baseline_rows.append((
            "上級", jyo, JYO_NAME.get(jyo, jyo), tt, kyori,
            len(wins), len(alls),
            round(statistics.median(wins), 2),
            round(q(wins, 25), 2),
            round(statistics.median(alls), 2),
            round(statistics.pstdev(wins), 2) if len(wins) > 1 else 0.0,
        ))

    # ── TF_BABA_ADJUST 構築 ──
    baba_rows = []
    for (jyo, tt, kyori), bb in baba.items():
        ryo = bb.get("1", [])
        if len(ryo) < 5:
            continue
        ryo_med = statistics.median(ryo)
        for bcode in ("1", "2", "3", "4"):
            arr = bb.get(bcode, [])
            if len(arr) < 3:
                continue
            delta = round(statistics.median(arr) - ryo_med, 2)  # 良馬場比(＋で遅い)
            baba_rows.append((
                jyo, JYO_NAME.get(jyo, jyo), tt, kyori, bcode, BABA_NAME[bcode],
                len(arr), delta,
            ))

    # ── DB 書き戻し ──
    cur.execute("DROP TABLE IF EXISTS TF_BASELINE")
    cur.execute("""
        CREATE TABLE TF_BASELINE (
            class_key TEXT, jyo TEXT, jyo_name TEXT, track TEXT, kyori TEXT,
            n_races INTEGER, n_horses INTEGER,
            base_win_time REAL, base_win_p25 REAL, base_all_time REAL, sd_win REAL
        )
    """)
    cur.executemany(
        "INSERT INTO TF_BASELINE VALUES (?,?,?,?,?,?,?,?,?,?,?)", baseline_rows)

    cur.execute("DROP TABLE IF EXISTS TF_BABA_ADJUST")
    cur.execute("""
        CREATE TABLE TF_BABA_ADJUST (
            jyo TEXT, jyo_name TEXT, track TEXT, kyori TEXT,
            baba TEXT, baba_name TEXT, n_races INTEGER, delta_sec REAL
        )
    """)
    cur.executemany(
        "INSERT INTO TF_BABA_ADJUST VALUES (?,?,?,?,?,?,?,?)", baba_rows)
    con.commit()

    # ── サマリ出力（検証用） ──
    def w(f, s=""):
        f.write(s + "\n")

    # 代表バケットの抜粋（実際の勝ちタイムと突き合わせやすいもの）
    picks = [
        ("古馬-OP", "05", "芝", "1600"), ("古馬-OP", "05", "芝", "2400"),
        ("古馬-1勝", "05", "芝", "1600"), ("古馬-1勝", "06", "芝", "2000"),
        ("古馬-OP", "06", "芝", "2000"), ("古馬-OP", "09", "ダ", "1800"),
        ("古馬-1勝", "09", "ダ", "1800"), ("3歳-未勝利", "05", "芝", "1600"),
        ("G1", "05", "芝", "2400"), ("古馬-OP", "08", "芝", "2000"),
    ]
    bmap = {(r[0], r[1], r[3], r[4]): r for r in baseline_rows}

    with open(OUT, "w", encoding="utf-8") as f:
        w(f, "=== baseline_time.py summary ===")
        w(f, "SE行総数(JOIN後): %d" % cnt_rows)
        w(f, "対象レース数(JRA・芝ダ・有効): %d" % len(races))
        w(f, "  うち芝レース: %d / ダレース: %d" % (cnt_track.get("芝", 0), cnt_track.get("ダ", 0)))
        w(f, "TF_BASELINE 行数: %d" % len(baseline_rows))
        w(f, "TF_BABA_ADJUST 行数: %d" % len(baba_rows))
        w(f)

        w(f, "=== クラス判定の頻度（レース単位・上位) ===")
        for cls, c in sorted(cnt_class.items(), key=lambda x: -x[1]):
            w(f, "  %-12s %d" % (cls, c))
        w(f)

        w(f, "=== 代表バケットの基準タイム（秒） ===")
        w(f, "  %-10s %-4s %-2s %-5s %6s %8s %8s %8s %6s" %
          ("class", "場", "種", "距離", "n", "基準勝T", "速25%", "標準T", "SD"))
        for key in picks:
            r = bmap.get(key)
            if r:
                w(f, "  %-10s %-4s %-2s %-5s %6d %8.1f %8.1f %8.1f %6.2f" %
                  (r[0], r[2], r[3], r[4], r[5], r[7], r[8], r[9], r[10]))
            else:
                w(f, "  %-10s %-4s %-2s %-5s  (該当バケットなし/サンプル不足)" %
                  (key[0], JYO_NAME.get(key[1], key[1]), key[2], key[3]))
        w(f)

        w(f, "=== 馬場差補正の例（東京芝1600 / 阪神ダ1800） ===")
        for (jyo, tt, kyori) in [("05", "芝", "1600"), ("09", "ダ", "1800")]:
            w(f, "  %s%s%s:" % (JYO_NAME[jyo], tt, kyori))
            for r in baba_rows:
                if r[0] == jyo and r[2] == tt and r[3] == kyori:
                    w(f, "    %-4s n=%-5d delta=%+.2f 秒" % (r[5], r[6], r[7]))
        w(f)

        w(f, "=== サンプル数が少ないバケット（n_races<20, 先頭20件） ===")
        thin = [r for r in baseline_rows if r[5] < 20]
        thin.sort(key=lambda r: r[5])
        for r in thin[:20]:
            w(f, "  %-10s %s%s%s n=%d" % (r[0], r[2], r[3], r[4], r[5]))
        w(f, "  （少数バケットは %d 件。基準の信頼度が低いので後段でフォールバック検討）" % len(thin))

    con.close()
    print("TF_BASELINE:", len(baseline_rows), "rows  /  TF_BABA_ADJUST:", len(baba_rows), "rows")
    print("Wrote:", OUT)


if __name__ == "__main__":
    main()
