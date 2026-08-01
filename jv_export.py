# -*- coding: utf-8 -*-
"""
jv_export.py  ―  race.db → 既存スコアラー互換CSV（過去走 / 坂路 / ウッド）
============================================================================
案2（TARGET全廃・JV完結）の変換層。対象レース（過去のレース＝backtest用）の
出走馬を race.db から取り、score_horse_v3.py がそのまま読める形式で出力する。

出力（jv_out/ フォルダ、cp932）:
  過去走_<YYYYMMDD>_<場略><R>.csv   … 各出走馬の過去走。独自補正タイム付き（TGX/補正タイムの代替）
  坂路_<YYYYMMDD>_<場略><R>.csv     … 各馬の坂路調教（レース14日以内をスコアラーが抽出）
  ウッド_<YYYYMMDD>_<場略><R>.csv   … 各馬のウッド調教

独自補正タイム = (基準勝ちタイム − 良馬場換算タイム) × 10 + 100  （高いほど速い/100=基準）
  良馬場換算タイム = 実走タイム − 馬場差delta(TF_BABA_ADJUST)
  基準は TF_BASELINE を参照。薄いバケットは「上級(G1/G2/G3/OPまとめ)」→「同条件・近距離」の順にフォールバック。

使い方（例：2025/07/19 東京11R を出力）:
  python jv_export.py --date 20250719 --jyo 05 --r 11
  ※ --jyo は場コード（01札幌..05東京..10小倉）。run_export.bat から date/jyo/r を渡してもよい。

注意: レース結果CSV・出馬表CSV は回顧用/速報系のためフェーズ2（本v1は予測入力3種）。
"""

import sqlite3
import os
import sys
import argparse
import csv
from datetime import date, timedelta

import baseline_time as bt   # track_type / class_key / parse_time / JYO_NAME / baba_code 等を再利用

DB = r"C:\Users\r-ito\JVLinkToSQLite\race.db"
OUTDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jv_out")

SEX = {"1": "牡", "2": "牝", "3": "セ"}
KYAKU = {"1": "逃", "2": "先", "3": "差", "4": "追"}
# レース結果の決め手(脚質)用フルラベル。回顧側(build_review)は 逃げ/先行/差し/追込 を期待。
KYAKU_FULL = {"1": "逃げ", "2": "先行", "3": "差し", "4": "追込", "5": "追込"}


def kyaku_of_result(e, tosu):
    """レース内の脚質を判定。JRA脚質区分(KyakusituKubun)優先、無ければ通過順位から導出。"""
    def _g(k):
        try:
            return e[k]
        except (KeyError, IndexError, TypeError):
            return None
    lab = KYAKU_FULL.get((str(_g("KyakusituKubun") or "")).strip(), "")
    if lab:
        return lab
    ps = []
    for c in ("Jyuni1c", "Jyuni2c", "Jyuni3c", "Jyuni4c"):
        v = str(_g(c) or "").strip()
        if v.isdigit() and int(v) > 0:
            ps.append(int(v))
    try:
        tosu = int(tosu)
    except (TypeError, ValueError):
        tosu = 0
    if not ps or tosu <= 0:
        return ""
    first = ps[0]
    r = (sum(ps) / len(ps)) / tosu   # 平均通過順位の相対位置
    if first == 1:
        return "逃げ"
    if r <= 0.33:
        return "先行"
    if r <= 0.66:
        return "差し"
    return "追込"
TENKO = {"1": "晴", "2": "曇", "3": "小雨", "4": "雨", "5": "小雪", "6": "雪"}
YOUBI = ["月", "火", "水", "木", "金", "土", "日"]
TRESEN = {"0": "美浦", "1": "栗東"}
# 場コード→ローマ字略（ファイル名用。スコアラーはIDとして扱うだけ）
JYO_ROMAJI = {"01": "sp", "02": "hk", "03": "fk", "04": "ng", "05": "tk",
              "06": "nk", "07": "ck", "08": "ky", "09": "hs", "10": "ok"}

# 独自TGXで、今走の条件帯(芝ダ×短中)に実績が無いとき、同じ芝ダの隣距離帯の
# ベストで補完する際の割引(点)。距離適性のズレを控えめに反映。0で無効。
ADJ_BAND_PENALTY = 5

# 過去走CSVの列（ヘッダなし・この順で出力）
COLS = ['年', '月', '日', '回次', '場所', '日次', 'レース番号', 'レース名',
        'クラス名', '芝・ダ', 'トラックコード', '距離', 'コーナー回数',
        'コース区分', '馬場状態', '馬名', '性別', '年齢', '騎手',
        '斤量', '頭数', '枠番', '馬番', '確定着順', '着差タイム',
        '人気', '単勝オッズ', '走破タイム秒', 'タイムS', '補正タイム',
        '通過順1角', '通過順2角', '通過順3角', '通過順4角',
        '上がり3Fタイム', '馬体重', '父馬名', '母馬名', '母の父馬名', 'PCI',
        '相対上がり']   # P3(2026-07): 各過去走レースの全馬平均上がりとの差(負=速い)。末脚のペース中立指標。


# ── 小ヘルパ ─────────────────────────────────────────────

def i(s):
    s = (s or "").strip()
    return str(int(s)) if s.isdigit() else ""


def dec10(s, nd=1):
    """'354'→'35.4' のように 1/10 単位の整数文字列を小数へ。'000'/空→''"""
    s = (s or "").strip()
    if not s.isdigit() or int(s) == 0:
        return ""
    return ("%.*f" % (nd, int(s) / 10.0))


def fmt_time_s(sec):
    """秒(float) → 'M.SS.F'（例 109.7 → '1.49.7'）"""
    if sec is None:
        return ""
    t = int(round(sec * 10))
    m = t // 600
    rem = t - m * 600
    s = rem // 10
    f = rem % 10
    return "%d.%02d.%d" % (m, s, f)


def hhmm(s):
    """'0742' → '7:42'"""
    s = (s or "").strip()
    if len(s) == 4 and s.isdigit():
        return "%d:%s" % (int(s[:2]), s[2:])
    return s


def timediff_sec(s):
    """SE.TimeDiff '+007'/'-004' → +0.7/-0.4（着差タイム, 秒）"""
    s = (s or "").strip()
    if not s:
        return ""
    sign = -1 if s[0] == "-" else 1
    num = s.lstrip("+-")
    if not num.isdigit():
        return ""
    return "%.1f" % (sign * int(num) / 10.0)


def track_code_out(trackcd):
    """芝の内/外を過去走.トラックコードへ: 内=0 / 外=8 / それ以外(ダ等)=1"""
    try:
        cd = int(trackcd)
    except (TypeError, ValueError):
        return "1"
    if cd in (11, 13, 15, 17, 19, 21):
        return "0"   # 内
    if cd in (12, 14, 16, 18, 20, 22):
        return "8"   # 外
    return "1"


def corner_count(row):
    n = 0
    for k in ("CornerInfo0Corner", "CornerInfo1Corner", "CornerInfo2Corner", "CornerInfo3Corner"):
        v = (row[k] or "").strip()
        if v and v != "0":
            n += 1
    return str(n) if n else ""


def class_display(ck):
    """class_key → 過去走.クラス名（normalize_class互換の表記）"""
    if ck in ("G1", "G2", "G3"):
        return ck
    part = ck.split("-")[-1]
    return part if part in ("OP", "1勝", "2勝", "3勝", "未勝利", "新馬") else "OP"


def kg_fmt(futan):
    """斤量 '580'→'58' / '555'→'55.5'"""
    s = (futan or "").strip()
    if not s.isdigit() or int(s) == 0:
        return ""
    v = int(s) / 10.0
    return ("%d" % v) if v == int(v) else ("%.1f" % v)


def zogen(fugo, sa):
    """馬体重増減 ('+','004')→'+4' / 空→''"""
    s = (sa or "").strip()
    if not s.isdigit():
        return ""
    f = (fugo or "").strip()
    return "%s%d" % (f if f in ("+", "-") else "+", int(s))


def tgx_short(dist):
    """短距離帯(<=1700m)判定。TGX芝短/中・ダ短/中の振り分け用（スコアラー get_tgx_col と一致）"""
    try:
        return int(dist) <= 1700
    except (TypeError, ValueError):
        return True


# ── 基準タイムのロード＆ルックアップ ─────────────────────────

def load_baseline(cur):
    base = {}     # (class, jyo, track, kyori) -> (base_win, n)
    for r in cur.execute(
            "SELECT class_key,jyo,track,kyori,n_races,base_win_time FROM TF_BASELINE"):
        base[(r[0], r[1], r[2], r[3])] = (r[5], r[4])
    baba = {}     # (jyo, track, kyori, baba) -> delta
    for r in cur.execute(
            "SELECT jyo,track,kyori,baba,delta_sec FROM TF_BABA_ADJUST"):
        baba[(r[0], r[1], r[2], r[3])] = r[4]
    return base, baba


def is_upper_class(ck):
    return ck in ("G1", "G2", "G3") or ck.endswith("-OP")


def lookup_base(base, cls, jyo, track, kyori):
    """基準勝ちタイムを返す。無ければ None。
    ※タイムは距離が違うと比較不能なので、距離をまたぐ借用は一切しない。
       1) 完全一致(同場・同距離・同芝ダ・同クラス) を最優先
       2) 上級(G1/G2/G3/OPまとめ)…ただし同一距離のみ
       3) いずれも無ければ None（→補正タイム空欄・スコアラーは偏差50中立扱い）"""
    hit = base.get((cls, jyo, track, kyori))
    if hit:
        return hit[0]
    if is_upper_class(cls):
        up = base.get(("上級", jyo, track, kyori))
        if up:
            return up[0]
    return None


# ── 本体 ─────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="対象レース日 YYYYMMDD")
    ap.add_argument("--jyo", required=True, help="場コード 01..10")
    ap.add_argument("--r", required=True, help="レース番号")
    ap.add_argument("--window", type=int, default=40, help="調教の遡り日数(既定40)")
    ap.add_argument("--outdir", default=None,
                    help="出力先。省略時 jv_out/。ライブ予想は input/ を指定すると run_new.py が拾う")
    args = ap.parse_args()
    outdir = args.outdir if args.outdir else OUTDIR

    ymd = args.date
    yy, mmdd = ymd[:4], ymd[4:]
    jyo = args.jyo.zfill(2)
    rno = args.r.zfill(2)

    if not os.path.exists(DB):
        print("DB not found:", DB); sys.exit(1)
    os.makedirs(outdir, exist_ok=True)

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    base, baba = load_baseline(cur)

    # ── 対象レースの条件（出馬表ヘッダ用） ──
    ra = cur.execute(
        """SELECT * FROM NL_RA_RACE
            WHERE idYear=? AND idMonthDay=? AND idJyoCD=? AND idRaceNum=? LIMIT 1""",
        (yy, mmdd, jyo, rno)).fetchone()
    if ra is None:
        print("対象レースが race.db に見つかりません:", ymd, jyo, "R"+args.r)
        sys.exit(1)
    tgt_tt = bt.track_type(ra["TrackCD"])
    if tgt_tt is None:
        # 障害戦(TrackCD 51〜59)。芝・ダートの基準タイムが無いので採点できない。
        # 以前はここで "芝" とみなしていたが、それでは静かに誤った採点結果が出る。
        print("障害戦は採点の対象外です (TrackCD=%s):" % ((ra["TrackCD"] or "").strip()),
              ymd, jyo, "R" + args.r)
        sys.exit(1)
    tgt_class = class_display(bt.class_key(ra))
    tgt_kyori = (ra["Kyori"] or "").strip()
    tgt_rname = (ra["RaceInfoHondai"] or ra["RaceInfoRyakusyo10"] or "").strip()
    tgt_corner = corner_count(ra)

    # ── 対象レースの出走馬（当日の枠/騎手/斤量/馬体重＋結果列も取得） ──
    ent = list(cur.execute(
        """SELECT KettoNum, Bamei, Umaban, Wakuban, SexCD, Barei,
                  KisyuRyakusyo, Futan, BaTaijyu, ZogenFugo, ZogenSa, Ninki, Odds,
                  KakuteiJyuni, IJyoCD, Time, TimeDiff,
                  Jyuni1c, Jyuni2c, Jyuni3c, Jyuni4c, HaronTimeL3, KyakusituKubun
             FROM NL_SE_RACE_UMA
            WHERE idYear=? AND idMonthDay=? AND idJyoCD=? AND idRaceNum=?
            ORDER BY CAST(Umaban AS INTEGER)""",
        (yy, mmdd, jyo, rno)))

    # 枠順確定時に除外された馬を落とす。
    # JV-Data は木曜の出走馬名表(DataKubun=1)の時点で馬番"00"のレコードを作る。
    # 金曜の出馬表(DataKubun=2)で馬番が振られるが、除外された馬は更新されず
    # 馬番"00"のまま残る。これを出馬表に混ぜると出走しない馬を採点してしまい、
    # 頭数も1頭多く数えてしまう（2026/08/02 中京7R 名鉄杯で発覚）。
    # ただし全馬が"00"のレースは枠順そのものが無いデータ（2014〜2016年の
    # 海外レース）なので、そのときは何も落とさない。
    def _has_umaban(e):
        return (e["Umaban"] or "").strip() not in ("", "00")

    _numbered = [e for e in ent if _has_umaban(e)]
    if _numbered and len(_numbered) < len(ent):
        _dropped = [e["Bamei"] for e in ent if not _has_umaban(e)]
        print("  [出馬表] 馬番なし（枠順確定時に除外）の %d頭を除きます: %s"
              % (len(_dropped), ", ".join(_dropped)))
        ent = _numbered

    kettos = [e["KettoNum"] for e in ent]
    name_of = {e["KettoNum"]: e["Bamei"] for e in ent}
    age_of = {e["KettoNum"]: e["Barei"] for e in ent}
    sex_of = {e["KettoNum"]: e["SexCD"] for e in ent}
    # 馬名→独自TGX（条件別ベスト補正）と直前情報の受け皿
    tgx = {e["Bamei"]: {"芝短": [], "芝中": [], "ダ短": [], "ダ中": [],
                        "直前": "", "脚": ""} for e in ent}

    # ── 血統(父/母/母父) ──
    sire = {}
    ph = ",".join("?" * len(kettos))
    for r in cur.execute(
            "SELECT KettoNum,Ketto3Info0Bamei,Ketto3Info1Bamei,Ketto3Info4Bamei "
            "FROM NL_UM_UMA WHERE KettoNum IN (%s)" % ph, kettos):
        sire[r["KettoNum"]] = (r[1] or "", r[2] or "", r[3] or "")

    race_int = int(ymd)

    # ── 過去走 ──
    past_sql = """
        SELECT se.KettoNum, se.Bamei, se.idYear, se.idMonthDay, se.idJyoCD,
               se.idKaiji, se.idNichiji, se.idRaceNum,
               se.Wakuban, se.Umaban, se.SexCD, se.Barei, se.KisyuRyakusyo, se.Futan,
               se.KakuteiJyuni, se.IJyoCD, se.Time, se.TimeDiff, se.Ninki, se.Odds,
               se.Jyuni1c, se.Jyuni2c, se.Jyuni3c, se.Jyuni4c, se.HaronTimeL3, se.BaTaijyu,
               se.KyakusituKubun,
               ra.Kyori, ra.TrackCD, ra.CourseKubunCD, ra.GradeCD, ra.JyokenInfoSyubetuCD,
               ra.JyokenInfoJyokenCD0, ra.JyokenInfoJyokenCD1, ra.JyokenInfoJyokenCD2,
               ra.JyokenInfoJyokenCD3, ra.JyokenInfoJyokenCD4,
               ra.TenkoBabaSibaBabaCD, ra.TenkoBabaDirtBabaCD,
               ra.RaceInfoHondai, ra.RaceInfoRyakusyo10, ra.SyussoTosu,
               ra.CornerInfo0Corner, ra.CornerInfo1Corner, ra.CornerInfo2Corner, ra.CornerInfo3Corner
        FROM NL_SE_RACE_UMA se
        JOIN NL_RA_RACE ra
          ON ra.idYear=se.idYear AND ra.idMonthDay=se.idMonthDay AND ra.idJyoCD=se.idJyoCD
         AND ra.idKaiji=se.idKaiji AND ra.idNichiji=se.idNichiji AND ra.idRaceNum=se.idRaceNum
        WHERE se.KettoNum IN (%s)
          AND CAST(se.idYear||se.idMonthDay AS INTEGER) < ?
        ORDER BY se.KettoNum, CAST(se.idYear||se.idMonthDay AS INTEGER) DESC
    """ % ph

    past_rows = []
    past_dicts = []   # P3: (row, race_key, horse_agari) を貯めて後段で相対上がりを付与
    n_hosei = 0
    n_past = 0
    for r in cur.execute(past_sql, kettos + [race_int]):
        tt = bt.track_type(r["TrackCD"])
        if tt is None:
            continue  # 障害は過去走から除外（コース処理を壊さない）
        # 地方(NAR)は過去走に残すが、採点はscore_horse側でJRA走のみに限定（参考表示のため保持）。
        n_past += 1
        cls = bt.class_key(r)
        kyori = (r["Kyori"] or "").strip()
        babac = bt.baba_code(r)
        babaname = bt.BABA_NAME.get(babac, "")
        sec = bt.parse_time(r["Time"])

        # 独自補正タイム
        hosei = ""
        if sec is not None and (r["IJyoCD"] or "").strip() in ("0", ""):
            b = lookup_base(base, cls, r["idJyoCD"], tt, kyori)
            if b is not None:
                delta = baba.get((r["idJyoCD"], tt, kyori, babac), 0.0) if babac else 0.0
                ryo = sec - delta                     # 良馬場換算
                hv = int(round((b - ryo) * 10 + 100))
                hosei = str(hv)
                n_hosei += 1
                # 独自TGX（条件別ベスト補正）を集約。芝ダ×短中(<=1700m)で振り分け。
                bmei = r["Bamei"]
                if bmei in tgx and hv > 0:
                    cond = ("芝" if tt == "芝" else "ダ") + ("短" if tgx_short(kyori) else "中")
                    tgx[bmei][cond].append(hv)
                    if tgx[bmei]["直前"] == "":       # 最新走（date降順の先頭）＝TGX直前・脚質
                        tgx[bmei]["直前"] = str(hv)
                        tgx[bmei]["脚"] = KYAKU.get((r["KyakusituKubun"] or "").strip(), "")

        father, mother, bms = sire.get(r["KettoNum"], ("", "", ""))
        rname = (r["RaceInfoHondai"] or r["RaceInfoRyakusyo10"] or "").strip()

        row = {
            '年': (r["idYear"] or "")[2:], '月': (r["idMonthDay"] or "")[:2], '日': (r["idMonthDay"] or "")[2:],
            '回次': i(r["idKaiji"]), '場所': bt.JYO_NAME.get(r["idJyoCD"], r["idJyoCD"]),
            '日次': i(r["idNichiji"]), 'レース番号': i(r["idRaceNum"]), 'レース名': rname,
            'クラス名': class_display(cls), '芝・ダ': tt, 'トラックコード': track_code_out(r["TrackCD"]),
            '距離': i(r["Kyori"]), 'コーナー回数': corner_count(r),
            'コース区分': (r["CourseKubunCD"] or "").strip(), '馬場状態': babaname,
            '馬名': r["Bamei"], '性別': SEX.get((r["SexCD"] or "").strip(), ""), '年齢': i(r["Barei"]),
            '騎手': (r["KisyuRyakusyo"] or "").strip(), '斤量': dec10(r["Futan"]),
            '頭数': i(r["SyussoTosu"]), '枠番': i(r["Wakuban"]), '馬番': i(r["Umaban"]),
            '確定着順': i(r["KakuteiJyuni"]), '着差タイム': timediff_sec(r["TimeDiff"]),
            '人気': i(r["Ninki"]), '単勝オッズ': dec10(r["Odds"]),
            '走破タイム秒': ("%.1f" % sec) if sec is not None else "", 'タイムS': fmt_time_s(sec),
            '補正タイム': hosei,
            '通過順1角': i(r["Jyuni1c"]), '通過順2角': i(r["Jyuni2c"]),
            '通過順3角': i(r["Jyuni3c"]), '通過順4角': i(r["Jyuni4c"]),
            '上がり3Fタイム': dec10(r["HaronTimeL3"]), '馬体重': i(r["BaTaijyu"]),
            '父馬名': father, '母馬名': mother, '母の父馬名': bms, 'PCI': "",  # PCIは廃止(空欄)
            '相対上がり': "",   # 後段でフィールド平均との差を算出
        }
        _rk = "".join([(r["idYear"] or ""), (r["idMonthDay"] or ""), (r["idJyoCD"] or ""),
                       (r["idKaiji"] or ""), (r["idNichiji"] or ""), (r["idRaceNum"] or "")])
        _agf = None
        try:
            _h = int((r["HaronTimeL3"] or "").strip())
            if _h > 0:
                _agf = _h / 10.0
        except Exception:
            pass
        past_dicts.append((row, _rk, _agf))

    # ── 相対上がり: 各過去走レースの全馬平均上がりとの差を付与（P3） ──
    _rks = sorted({rk for _, rk, _ in past_dicts if rk})
    _avg = {}
    for _i in range(0, len(_rks), 800):   # SQLite変数上限対策でチャンク
        _chunk = _rks[_i:_i + 800]
        _q = ("SELECT (idYear||idMonthDay||idJyoCD||idKaiji||idNichiji||idRaceNum) rk, HaronTimeL3 "
              "FROM NL_SE_RACE_UMA WHERE (idYear||idMonthDay||idJyoCD||idKaiji||idNichiji||idRaceNum) IN (%s)"
              % ",".join(["?"] * len(_chunk)))
        _acc = {}
        for _row in cur.execute(_q, _chunk):
            try:
                _h = int((_row["HaronTimeL3"] or "").strip())
            except Exception:
                _h = 0
            if _h > 0:
                _acc.setdefault(_row["rk"], []).append(_h / 10.0)
        for _rk, _arr in _acc.items():
            if _arr:
                _avg[_rk] = sum(_arr) / len(_arr)
    for (row, rk, agf) in past_dicts:
        if agf is not None and rk in _avg:
            row['相対上がり'] = "%.1f" % (agf - _avg[rk])   # 負=フィールドより速い末脚
        past_rows.append([row[c] for c in COLS])

    # ── 坂路 ──
    cutoff = (date(int(yy), int(mmdd[:2]), int(mmdd[2:])) - timedelta(days=args.window))
    cutoff_int = int(cutoff.strftime("%Y%m%d"))
    hanro_rows = []
    for r in cur.execute(
            "SELECT KettoNum,TresenKubun,ChokyoDate,ChokyoTime,"
            "HaronTime4,HaronTime3,HaronTime2,LapTime4,LapTime3,LapTime2,LapTime1 "
            "FROM NL_HC_HANRO WHERE KettoNum IN (%s) "
            "AND CAST(ChokyoDate AS INTEGER) BETWEEN ? AND ?" % ph,
            kettos + [cutoff_int, race_int - 1]):
        d = (r["ChokyoDate"] or "").strip()
        try:
            dt = date(int(d[:4]), int(d[4:6]), int(d[6:8]))
            wd = YOUBI[dt.weekday()]
        except Exception:
            wd = ""
        k = r["KettoNum"]
        hanro_rows.append([
            TRESEN.get((r["TresenKubun"] or "").strip(), ""), d, wd, hhmm(r["ChokyoTime"]),
            name_of.get(k, ""), SEX.get((sex_of.get(k) or "").strip(), ""), i(age_of.get(k)),
            dec10(r["HaronTime4"]), dec10(r["HaronTime3"]), dec10(r["HaronTime2"]), dec10(r["LapTime1"]),
            dec10(r["LapTime4"]), dec10(r["LapTime3"]), dec10(r["LapTime2"]), dec10(r["LapTime1"]),
        ])

    # ── ウッド ──
    wood_rows = []
    for r in cur.execute(
            "SELECT KettoNum,TresenKubun,Course,BabaAround,ChokyoDate,ChokyoTime,"
            "HaronTime10,HaronTime9,HaronTime8,HaronTime7,HaronTime6,HaronTime5,"
            "HaronTime4,HaronTime3,HaronTime2,LapTime1,"
            "LapTime9,LapTime8,LapTime7,LapTime6,LapTime5,LapTime4,LapTime3,LapTime2 "
            "FROM NL_WC_WOOD WHERE KettoNum IN (%s) "
            "AND CAST(ChokyoDate AS INTEGER) BETWEEN ? AND ?" % ph,
            kettos + [cutoff_int, race_int - 1]):
        d = (r["ChokyoDate"] or "").strip()
        try:
            dt = date(int(d[:4]), int(d[4:6]), int(d[6:8]))
            wd = YOUBI[dt.weekday()]
        except Exception:
            wd = ""
        k = r["KettoNum"]
        wood_rows.append([
            TRESEN.get((r["TresenKubun"] or "").strip(), ""), (r["Course"] or "").strip(),
            (r["BabaAround"] or "").strip(), d, wd, hhmm(r["ChokyoTime"]),
            name_of.get(k, ""), SEX.get((sex_of.get(k) or "").strip(), ""), i(age_of.get(k)),
            dec10(r["HaronTime10"]), dec10(r["HaronTime9"]), dec10(r["HaronTime8"]), dec10(r["HaronTime7"]),
            dec10(r["HaronTime6"]), dec10(r["HaronTime5"]), dec10(r["HaronTime4"]), dec10(r["HaronTime3"]),
            dec10(r["HaronTime2"]), dec10(r["LapTime1"]),   # 10F..1F
            dec10(r["LapTime9"]), dec10(r["LapTime8"]), dec10(r["LapTime7"]), dec10(r["LapTime6"]),
            dec10(r["LapTime5"]), dec10(r["LapTime4"]), dec10(r["LapTime3"]), dec10(r["LapTime2"]),
            dec10(r["LapTime1"]),                           # Lap9..Lap1
        ])

    # ── 出馬表（3行ヘッダ＋各馬行。独自TGXを埋める） ──
    def tgx_val(primary, secondary):
        """今走条件帯のベスト。無ければ同芝ダの隣距離帯ベストを割引(ADJ_BAND_PENALTY)して補完。"""
        if primary:
            return str(max(primary))
        if secondary:
            v = max(secondary) - ADJ_BAND_PENALTY
            return str(v) if v > 0 else ""
        return ""

    shutuba_rows = []
    # row0: レース情報の項目名（15列）
    shutuba_rows.append(["年", "月", "日", "場所", "R", "レース名", "クラス名",
                         "性別限定", "重量種別", "年齢限定", "条件表記",
                         "芝・ダート", "距離", "コーナー回数", "頭数"])
    # row1: レース情報の値（index 11=芝ダ,12=距離,13=コーナー,14=頭数）
    shutuba_rows.append([yy, mmdd[:2], mmdd[2:], bt.JYO_NAME.get(jyo, jyo), args.r,
                         tgt_rname, tgt_class, "", "", "", "",
                         tgt_tt, tgt_kyori, tgt_corner, str(len(ent))])
    # row2: 各馬の項目名（29列）
    shutuba_rows.append(["枠番", "B", "番", "馬名S", "性別", "年齢", "替", "騎手", "斤量",
                         "減M", "人気", "単勝", "複勝人気", "複勝下限", "複勝上限",
                         "馬体重", "増減", "馬体重増減", "間隔",
                         "TGX直前", "TGX芝短", "TGX芝中", "TGXダ短", "TGXダ中", "TGX脚",
                         "父", "母", "母父", "母の母"])
    # row3+: 各馬（レース当日値＋独自TGX）
    for e in ent:
        nm = e["Bamei"]
        t = tgx.get(nm, {})
        father, mother, bms = sire.get(e["KettoNum"], ("", "", ""))
        shutuba_rows.append([
            i(e["Wakuban"]), "", i(e["Umaban"]), nm, SEX.get((e["SexCD"] or "").strip(), ""),
            i(e["Barei"]), "", (e["KisyuRyakusyo"] or "").strip(), kg_fmt(e["Futan"]),
            "", i(e["Ninki"]), dec10(e["Odds"]), "", "", "",
            i(e["BaTaijyu"]), zogen(e["ZogenFugo"], e["ZogenSa"]), "", "",
            t.get("直前", ""),
            tgx_val(t.get("芝短", []), t.get("芝中", [])),   # 芝短(無ければ芝中を割引流用)
            tgx_val(t.get("芝中", []), t.get("芝短", [])),   # 芝中(無ければ芝短を割引流用)
            tgx_val(t.get("ダ短", []), t.get("ダ中", [])),   # ダ短(無ければダ中を割引流用)
            tgx_val(t.get("ダ中", []), t.get("ダ短", [])),   # ダ中(無ければダ短を割引流用)
            t.get("脚", ""),
            father, mother, bms,
        ])

    # ── レース結果（結果が確定している場合のみ。回顧/レビュー用） ──
    def kj(e):
        try:
            return int((e["KakuteiJyuni"] or "").strip())
        except (TypeError, ValueError):
            return 0
    has_result = any(kj(e) > 0 for e in ent)

    # 速報系フォールバック: 蓄積系(NL)にまだ確定着順が無い当日は、速報系(RT_SE_RACE_UMA)
    # から結果列を取り込む。蓄積系は翌日以降に配信されるため、当日回顧を可能にする。
    result_source = "NL(蓄積)" if has_result else None
    def _table_exists(name):
        return cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None
    if not has_result and _table_exists("RT_SE_RACE_UMA"):
        _rt = {}
        for r in cur.execute(
                """SELECT Umaban, KakuteiJyuni, IJyoCD, Time, TimeDiff,
                          Jyuni1c, Jyuni2c, Jyuni3c, Jyuni4c, HaronTimeL3,
                          Ninki, Odds, BaTaijyu, ZogenFugo, ZogenSa, KyakusituKubun
                     FROM RT_SE_RACE_UMA
                    WHERE idYear=? AND idMonthDay=? AND idJyoCD=? AND idRaceNum=?""",
                (yy, mmdd, jyo, rno)):
            _rt[(r["Umaban"] or "").strip()] = r
        if _rt:
            _RES_COLS = ("KakuteiJyuni", "IJyoCD", "Time", "TimeDiff",
                         "Jyuni1c", "Jyuni2c", "Jyuni3c", "Jyuni4c", "HaronTimeL3",
                         "Ninki", "Odds", "BaTaijyu", "ZogenFugo", "ZogenSa", "KyakusituKubun")
            _merged = []
            for e in ent:
                d = dict(e)
                rr = _rt.get((e["Umaban"] or "").strip())
                if rr is not None:
                    for col in _RES_COLS:
                        d[col] = rr[col]
                _merged.append(d)
            ent = _merged
            has_result = any(kj(e) > 0 for e in ent)
            if has_result:
                result_source = "RT(速報)"

    # ── 払戻（配当）: 回顧の期待値/回収計算用。NL_HR_PAY優先、無ければRT_HR_PAY（速報）──
    def _pay_from(table):
        row = cur.execute("SELECT * FROM %s WHERE idYear=? AND idMonthDay=? "
                          "AND idJyoCD=? AND idRaceNum=? LIMIT 1" % table,
                          (yy, mmdd, jyo, rno)).fetchone()
        po = {'tansho': [], 'fukusho': [], 'umaren': [], 'wide': [],
              'umatan': [], 'sanrenpuku': [], 'sanrentan': []}
        if not row:
            return po
        keys = row.keys()
        def g(name):
            return ((row[name] or "").strip() if name in keys else "")
        def combo(kumi, k):
            kumi = kumi.strip()
            if len(kumi) == 2 * k and kumi.isdigit():
                return "-".join(str(int(kumi[i*2:i*2+2])) for i in range(k))
            return None
        def add_uma(dst, cnt, pre):
            for n in range(cnt):
                ub = g("%s%dUmaban" % (pre, n)); pay = g("%s%dPay" % (pre, n))
                if ub.isdigit() and pay.isdigit() and int(pay) > 0:
                    po[dst].append((str(int(ub)), int(pay)))
        def add_kumi(dst, cnt, pre, k):
            for n in range(cnt):
                c = combo(g("%s%dKumi" % (pre, n)), k); pay = g("%s%dPay" % (pre, n))
                if c and pay.isdigit() and int(pay) > 0:
                    po[dst].append((c, int(pay)))
        add_uma('tansho', 3, 'PayTansyo'); add_uma('fukusho', 5, 'PayFukusyo')
        add_kumi('umaren', 3, 'PayUmaren', 2); add_kumi('wide', 7, 'PayWide', 2)
        add_kumi('umatan', 6, 'PayUmatan', 2); add_kumi('sanrenpuku', 3, 'PaySanrenpuku', 3)
        add_kumi('sanrentan', 6, 'PaySanrentan', 3)
        return po
    payouts = {}
    if has_result:
        payouts = _pay_from("NL_HR_PAY")
        if not any(payouts.values()) and _table_exists("RT_HR_PAY"):
            payouts = _pay_from("RT_HR_PAY")

    result_rows = []
    if has_result:
        # 天候/馬場: NL_RA_RACEの確定前レコードは天候・馬場が空のことがある当日は、
        # 速報RA(RT_RA_RACE)の確定値で補完する（NLに値があればそちらを優先）。
        _ra_eff = dict(ra)
        _tenko_flds = ("TenkoBabaTenkoCD", "TenkoBabaSibaBabaCD", "TenkoBabaDirtBabaCD")
        if any(not str(_ra_eff.get(k) or "").strip() for k in _tenko_flds) and _table_exists("RT_RA_RACE"):
            _rt_ra = cur.execute(
                "SELECT * FROM RT_RA_RACE WHERE idYear=? AND idMonthDay=? "
                "AND idJyoCD=? AND idRaceNum=? LIMIT 1",
                (yy, mmdd, jyo, rno)).fetchone()
            if _rt_ra is not None:
                _rk = _rt_ra.keys()
                for k in _tenko_flds:
                    if not str(_ra_eff.get(k) or "").strip() and k in _rk:
                        _ra_eff[k] = _rt_ra[k]
        tgt_tenko = TENKO.get((str(_ra_eff.get("TenkoBabaTenkoCD") or "")).strip(), "")
        tgt_baba = bt.BABA_NAME.get(bt.baba_code(_ra_eff), "")
        # レースラップ/前後3ハロン（確定成績で設定。速報で未配信なら空→回顧側で「取得不可」表示）
        def _dec1(v):
            v = str(v or "").strip()
            return (int(v) / 10.0) if v.isdigit() and int(v) > 0 else None
        _s3 = _dec1(_ra_eff.get("HaronTimeS3"))   # 前3ハロン(前半3F)
        _l3 = _dec1(_ra_eff.get("HaronTimeL3"))   # 後3ハロン(後半3F)
        try:
            _nh = int(round(int(str(tgt_kyori or "0").strip() or "0") / 200.0))
        except Exception:
            _nh = 0
        _laps = []
        for _li in range(min(_nh, 25)):
            _lv = _dec1(_ra_eff.get("LapTime%d" % _li))
            if _lv is None:
                break
            _laps.append("%.1f" % _lv)
        _lap_all = "-".join(_laps)
        _lap_up3 = "-".join(_laps[-3:]) if len(_laps) >= 3 else ""
        tgt_zen3 = ("%.1f" % _s3) if _s3 is not None else ""
        tgt_ago3 = ("%.1f" % _l3) if _l3 is not None else ""
        pace_src = "速報" if (result_source or "").startswith("RT") else "確定"
        # メタ2行（row0=キー, row1=値）
        result_rows.append(["年", "月", "日", "場所", "R", "レース名", "クラス名",
                            "芝・ダート", "距離", "天候", "馬場状態", "コーナー回数", "頭数",
                            "通過3F", "上り3F", "通過ラップ表記", "上りラップ表記", "結果ソース"])
        result_rows.append([yy, mmdd[:2], mmdd[2:], bt.JYO_NAME.get(jyo, jyo), args.r,
                            tgt_rname, tgt_class, ("芝" if tgt_tt == "芝" else "ダート"),
                            tgt_kyori, tgt_tenko, tgt_baba, tgt_corner, str(len(ent)),
                            tgt_zen3, tgt_ago3, _lap_all, _lap_up3, pace_src])
        # 馬表（row2=ヘッダ, row3+=各馬。着順昇順）
        result_rows.append(["入線順位", "異常コード", "馬番", "枠番", "馬名", "性別", "年齢",
                            "斤量", "騎手", "タイム", "着差", "通過1", "通過2", "通過3", "通過4",
                            "決め手", "上り3F", "人気", "単勝オッズ", "体重", "増減",
                            "種牡馬", "母馬名", "母の父馬名"])
        for e in sorted(ent, key=lambda x: (kj(x) if kj(x) > 0 else 99)):
            sec = bt.parse_time(e["Time"])
            father, mother, bms = sire.get(e["KettoNum"], ("", "", ""))
            result_rows.append([
                (str(kj(e)) if kj(e) > 0 else ""), (e["IJyoCD"] or "").strip(),
                i(e["Umaban"]), i(e["Wakuban"]), e["Bamei"], SEX.get((e["SexCD"] or "").strip(), ""),
                i(e["Barei"]), kg_fmt(e["Futan"]), (e["KisyuRyakusyo"] or "").strip(),
                fmt_time_s(sec), timediff_sec(e["TimeDiff"]),
                i(e["Jyuni1c"]), i(e["Jyuni2c"]), i(e["Jyuni3c"]), i(e["Jyuni4c"]),
                kyaku_of_result(e, len(ent)), dec10(e["HaronTimeL3"]), i(e["Ninki"]), dec10(e["Odds"]),
                i(e["BaTaijyu"]), zogen(e["ZogenFugo"], e["ZogenSa"]),
                father, mother, bms,
            ])

    # ── 書き出し（cp932）──
    tag = "%s_%s%s" % (ymd, JYO_ROMAJI.get(jyo, "xx"), args.r)

    def write_csv(name, header, rows):
        p = os.path.join(outdir, name)
        with open(p, "w", encoding="cp932", errors="replace", newline="") as f:
            w = csv.writer(f)
            if header is not None:
                w.writerow(header)
            w.writerows(rows)
        return p

    p0 = write_csv("出馬表_%s.csv" % tag, None, shutuba_rows)   # 3行ヘッダ内包
    p1 = write_csv("過去走_%s.csv" % tag, None, past_rows)   # ヘッダなし
    p2 = write_csv("坂路_%s.csv" % tag,
                   ["場所", "年月日", "曜日", "時刻", "馬名", "性別", "年齢",
                    "Time1", "Time2", "Time3", "Time4", "Lap4", "Lap3", "Lap2", "Lap1"],
                   hanro_rows)
    p3 = write_csv("ウッド_%s.csv" % tag,
                   ["場所", "コース", "回り", "年月日", "曜日", "時刻", "馬名", "性別", "年齢",
                    "10F", "9F", "8F", "7F", "6F", "5F", "4F", "3F", "2F", "1F",
                    "Lap9", "Lap8", "Lap7", "Lap6", "Lap5", "Lap4", "Lap3", "Lap2", "Lap1"],
                   wood_rows)
    outs = [p0, p1, p2, p3]
    if result_rows:
        outs.append(write_csv("レース結果_%s.csv" % tag, None, result_rows))  # 2段ヘッダ内包
    # 払戻JSON（回顧の期待値/回収計算用）。build_review が payouts 空時に読み込む。
    if result_rows and any(payouts.values()):
        import json as _jsonp
        _hpath = os.path.join(outdir, "haraimodoshi_%s.json" % tag)
        with open(_hpath, "w", encoding="utf-8") as _hf:
            _jsonp.dump(payouts, _hf, ensure_ascii=False)
        outs.append(_hpath)

    con.close()
    print("出走馬 %d 頭 / 過去走 %d 行(うち独自補正付与 %d) / 坂路 %d 行 / ウッド %d 行 / レース結果 %s / 払戻 %s"
          % (len(ent), len(past_rows), n_hosei, len(hanro_rows), len(wood_rows),
             ("あり[%s]" % result_source) if result_rows else "なし(未確定)",
             "あり" if (result_rows and any(payouts.values())) else "なし"))
    print("出力:")
    for p in outs:
        print("  ", p)


if __name__ == "__main__":
    main()
