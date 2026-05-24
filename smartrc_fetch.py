# -*- coding: utf-8 -*-
"""
smartrc_fetch.py  --  SmartRC API から出馬データを自動取得するスクリプト
======================================================================
使い方:
  python smartrc_fetch.py 20260222_t11          # rcode自動検索 -> データ取得
  python smartrc_fetch.py --rcode 2026022205010811  # rcode直接指定
  python smartrc_fetch.py 20260222_t11 --out    # JSON保存
  python smartrc_fetch.py --date 20260222       # その日のrcode一覧表示

注意: rcode = YYYYMMDD + 場(2桁) + 開催回(2桁) + 開催日(2桁) + レース番号(2桁)
"""

import sys, json, re, time, pathlib, argparse
import requests

BASE_URL  = "https://www.smartrc.jp/v3/"
API_BASE  = BASE_URL + "smartrc.php/"
SCRIPT_DIR = pathlib.Path(__file__).parent
OUT_DIR   = SCRIPT_DIR

VENUE_MAP = {
    "tk": "05",
    "ny": "06",
    "hs": "09",
    "kt": "08",
    "ck": "07",
    "ng": "04",
    "kk": "10",
    "fs": "03",
    "sp": "01",
    "hd": "02",
}

VENUE_CODE_TO_ABBR = {
    "01": "sp", "02": "hd", "03": "fs", "04": "ng",
    "05": "tk", "06": "ny", "07": "ck", "08": "kt",
    "09": "hs", "10": "kk",
}

def rcode_to_race_id(rcode):
    if len(rcode) < 16:
        return "rcode_" + rcode
    date_str   = rcode[0:8]
    place_code = rcode[8:10]
    race_no    = int(rcode[14:16])
    abbr       = VENUE_CODE_TO_ABBR.get(place_code, "v" + place_code)
    return date_str + "_" + abbr + str(race_no)

def parse_race_id(race_id):
    m = re.match(r'^(\d{8})_([a-zA-Z]+)(\d+)$', race_id)
    if not m:
        raise ValueError("race_id の形式が不正: " + race_id + "  (例: 20260222_t11)")
    return m.group(1), m.group(2).lower(), int(m.group(3))

def make_session():
    sess = requests.Session()
    sess.headers.update({
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"),
        "Referer":          BASE_URL,
        "Origin":           "https://www.smartrc.jp",
        "Accept":           "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
    })
    r = sess.get(BASE_URL, timeout=15)
    print("[OK] セッション取得完了" if r.status_code == 200 else "[WARN] " + str(r.status_code))
    return sess

def fetch_races(sess, date_str):
    attempts = [
        {"ymd": date_str, "page": 1, "start": 0, "limit": 200},
        {"date": date_str, "page": 1, "start": 0, "limit": 200},
        {"kaisai_date": date_str, "page": 1, "start": 0, "limit": 200},
        {"page": 1, "start": 0, "limit": 200},
    ]
    for payload in attempts:
        r = sess.post(
            API_BASE + "races/view",
            params={"_dc": int(time.time() * 1000)},
            json=payload, timeout=20
        )
        r.raise_for_status()
        data = r.json()
        if data.get("success") and int(data.get("total", 0)) > 0:
            k0 = list(payload.keys())[0]
            v0 = list(payload.values())[0]
            print("  [OK] races/view 成功 (payload=" + str(k0) + "=" + str(v0) + ")")
            return data.get("data", [])
        msg = data.get("message", "")
        k0 = list(payload.keys())[0]
        v0 = list(payload.values())[0]
        print("  [試行] " + str(k0) + "=" + str(v0) + "  -> " + (msg or "success=false"))
    raise RuntimeError(
        "races/view が全パターンで失敗しました\n"
        "-> rcode を直接指定してください: python smartrc_fetch.py --rcode XXXXXXXXXXXXXXXX\n"
        "   rcodeはSmartRCのNetworkタブ > runners/view > Payload > rcode の値です"
    )

def fetch_runners(sess, rcode):
    r = sess.post(
        API_BASE + "runners/view",
        params={"_dc": int(time.time() * 1000)},
        json={"rcode": rcode, "toku": "0", "page": 1, "start": 0, "limit": 30},
        timeout=20
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        raise RuntimeError("runners/view エラー: " + str(data.get("message")))
    return data.get("data", [])

def find_rcode(races, place_code, race_no):
    target_race = "%02d" % race_no
    for rec in races:
        rc = str(rec.get("rcode", ""))
        if len(rc) >= 16 and rc[8:10] == place_code and rc[14:16] == target_race:
            return rc
    return None

KEY_FIELDS = [
    "hname", "uno",
    "f_name", "f_slcode", "f_clcode",
    "mf_name", "mf_slcode", "mf_clcode",
    "fmf_name", "fmf_slcode",
    "mmf_name", "mmf_slcode",
    "diff_type", "diff_exp",
    "ten1f_best", "ten1f_best_rank",
    "h1_ten1f", "h1_ten1f_rank",
    "ten_pat", "ten_has", "ten_has_rank",
    "agari_pat", "agari_has", "agari_has_rank",
    "cr_value",
    "rota_type", "rota_eval",
    "old_pr", "cl_eval_ja",
    "f_dirt_share", "f_1400_share",
    "h1_fr_baba", "h2_fr_baba", "h3_fr_baba", "h4_fr_baba", "h5_fr_baba",
    "h1_tb_baba", "h2_tb_baba", "h3_tb_baba", "h4_tb_baba", "h5_tb_baba",
    "h1_tb_io", "h1_tb_diff",
    "h2_tb_io", "h2_tb_diff",
    "h3_tb_io", "h3_tb_diff",
    "h4_tb_io", "h4_tb_diff",
    "h5_tb_io", "h5_tb_diff",
    "h1_grade", "h2_grade", "h3_grade", "h4_grade", "h5_grade",
    "h1_rank",  "h2_rank",  "h3_rank",  "h4_rank",  "h5_rank",
    "h1_range", "h2_range", "h3_range", "h4_range", "h5_range",
    "h1_interval", "h2_interval", "h3_interval", "h4_interval", "h5_interval",
    "h1_soma_memo1", "h1_soma_memo2",
    "h2_soma_memo1", "h2_soma_memo2",
    "est_pop", "odds_tan", "pop_tan",
]

def extract(rec):
    return {k: rec.get(k) for k in KEY_FIELDS}

def main():
    parser = argparse.ArgumentParser(description="SmartRC データ取得")
    parser.add_argument("race_id", nargs="?", help="レースID (例: 20260222_t11)")
    parser.add_argument("--date", help="日付指定でrcode一覧表示 (YYYYMMDD)")
    parser.add_argument("--out", action="store_true", help="JSONを保存する")
    parser.add_argument("--rcode", help="rcode を直接指定 (races/viewをスキップ)")
    args = parser.parse_args()

    sess = make_session()

    if args.date and not args.race_id and not args.rcode:
        print("\n" + args.date + " のレース一覧を取得中...")
        races = fetch_races(sess, args.date)
        print("\n" + args.date + " のレース一覧 (" + str(len(races)) + "件):")
        for rec in races:
            rc = rec.get("rcode", "")
            place = rc[8:10] if len(rc) >= 16 else "?"
            race  = rc[14:16] if len(rc) >= 16 else "?"
            print("  rcode=" + rc + "  trackkind=" + str(rec.get("trackkind")) +
                  "  range=" + str(rec.get("range")) +
                  "  place=" + place + "  race=" + race)
        return

    if not args.race_id and not args.rcode:
        parser.print_help()
        sys.exit(1)

    if args.rcode:
        rcode   = args.rcode
        race_id = args.race_id or rcode_to_race_id(rcode)
        print("[INFO] rcode=" + rcode + "  ->  race_id=" + race_id)
    else:
        race_id = args.race_id
        date_str, venue, race_no = parse_race_id(race_id)
        place_code = VENUE_MAP.get(venue)
        if not place_code:
            print("[ERROR] 未知の場コード: '" + venue + "'")
            sys.exit(1)
        print("[INFO] " + race_id + " -> 場コード=" + place_code +
              "  レース=" + ("%02d" % race_no) + "  日付=" + date_str)
        print("[INFO] races/view で " + date_str + " のレース一覧を取得中...")
        races = fetch_races(sess, date_str)
        print("  -> " + str(len(races)) + " レース取得")
        rcode = find_rcode(races, place_code, race_no)
        if not rcode:
            print("[ERROR] " + race_id + " に対応する rcode が見つかりません")
            for rec in races:
                rc = rec.get("rcode", "")
                place = rc[8:10] if len(rc) >= 16 else "?"
                race  = rc[14:16] if len(rc) >= 16 else "?"
                print("  " + rc + "  place=" + place + "  race=" + race)
            sys.exit(1)
        print("[OK] rcode = " + rcode)

    print("[INFO] runners/view 取得中 (rcode=" + rcode + ")...")
    runners = fetch_runners(sess, rcode)
    print("  -> " + str(len(runners)) + " 頭取得")

    if not runners:
        print("[ERROR] データが空です")
        sys.exit(1)

    print("\n[利用可能なフィールド一覧 (1頭目)]:")
    for k, v in sorted(runners[0].items()):
        print("  " + k + ": " + repr(v)[:70])

    result = {
        "race_id": race_id,
        "rcode":   rcode,
        "horses":  {r.get("hname", "horse_" + str(i)): extract(r)
                    for i, r in enumerate(runners)}
    }

    if args.out:
        out_path = OUT_DIR / ("smartrc_" + race_id + ".json")
        out_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("\n[保存完了] " + str(out_path))
    else:
        print("\n[結果プレビュー] (--out で保存):")
        preview = json.dumps(result, ensure_ascii=False, indent=2)
        print(preview[:3000])
        if len(preview) > 3000:
            print("... (省略) ...")

if __name__ == "__main__":
    main()
