# -*- coding: utf-8 -*-
"""
fetch_baba.py -- JRA 馬場情報ページから馬場状態・降水量を取得し
                 レース当日の推定馬場状態を JSON で出力する。

使い方:
  python fetch_baba.py --venue 東京 --date 20260525 --out baba_TK.json
  python fetch_baba.py --venue 新潟 --date 20260601 --out baba_NG.json

出力 JSON 例:
  {
    "場所": "東京",
    "取得日時": "2026-05-28 10:00:00",
    "芝馬場": "良",
    "ダート馬場": "稍重",
    "クッション値": 9.2,
    "降水量_mm": 0.5,
    "推定馬場_芝": "良",
    "推定馬場_ダート": "稍重",
    "推定根拠": "現在馬場:良 + 降水量0.5mm（影響小）"
  }
"""
import argparse, json, re, sys, datetime, pathlib

BASE_URL = 'https://www.jra.go.jp/keiba/baba/'
PAGE_SUFFIXES = ['index.html', 'index2.html', 'index3.html']

# 会場コード → 正式場所名マッピング
VENUE_CODE_MAP = {
    'TK': '東京', 'TO': '東京',
    'CB': '中山', 'NA': '中山', 'NS': '中山',
    'HN': '阪神', 'HS': '阪神',
    'KT': '京都', 'KY': '京都',
    'CK': '中京', 'CC': '中京',
    'NK': '新潟', 'NG': '新潟', 'NI': '新潟',
    'HK': '函館',
    'SM': '札幌', 'SP': '札幌',
    'FK': '福島',
    'KO': '小倉', 'KK': '小倉',
}

KNOWN_VENUES = ['東京', '中山', '阪神', '京都', '中京', '新潟', '函館', '札幌', '福島', '小倉']

BABA_LEVELS = ['良', '稍重', '重', '不良']


def normalize_venue(v: str) -> str:
    """コードまたは名前を正式場所名に変換。例: 'TK' → '東京', 'ng' → '新潟'"""
    upper = v.upper()
    if upper in VENUE_CODE_MAP:
        return VENUE_CODE_MAP[upper]
    if v in KNOWN_VENUES:
        return v
    # 部分マッチ
    for vname in KNOWN_VENUES:
        if vname in v:
            return vname
    return v


def fetch_page(url: str) -> str | None:
    """requests で CP932 フェッチ。失敗時は None。"""
    try:
        import requests
        r = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        r.encoding = 'cp932'
        return r.text
    except Exception as e:
        print(f'  [fetch] {url} 取得失敗: {e}', file=sys.stderr)
        return None


def detect_venue(html: str) -> str | None:
    """
    HTML の本文コンテンツから開催会場名を検出する。
    navリンクには全会場が含まれるため、h2 見出し（例:「第2回東京競馬第11日前日」）
    や contents_header クラスのテキストから判定する。
    """
    # メイン h2 見出し内の会場名（例: 「第2回東京競馬...」→ 東京）
    for m in re.finditer(r'<h2[^>]*>([^<]{2,50})', html):
        text = m.group(1)
        for vname in KNOWN_VENUES:
            if vname in text:
                return vname
    # 次善策: contents_header クラス内テキスト
    m_hdr = re.search(r'class="[^"]*contents_header[^"]*"(.{0,400})', html, re.DOTALL)
    if m_hdr:
        for vname in KNOWN_VENUES:
            if vname in m_hdr.group(1):
                return vname
    return None


def _norm_going(g: str) -> str:
    """馬場状態文字を正規化。稍→稍重, 不→不良"""
    s = str(g).strip()
    if s in ('稍', 'やや重', '稍重'):
        return '稍重'
    if s in ('不', '不良'):
        return '不良'
    if s in ('重',):
        return '重'
    if s in ('良',):
        return '良'
    return s


def parse_baba_jotai(html: str) -> tuple[str | None, str | None]:
    """
    HTML から馬場状態（芝・ダート）を解析。
    戻り値: (芝馬場, ダート馬場)
    """
    baba_pat = '良|稍重|重|不良'

    shiba = None
    dart = None

    # パターン1: <h4>芝</h4> または <dt>芝</dt> の後に来る馬場状態テキスト
    m_shiba = re.search(
        r'<(?:h4|dt)[^>]*>\s*芝\s*</(?:h4|dt)>(.{0,300}?)(' + baba_pat + r')',
        html, re.DOTALL
    )
    if m_shiba:
        shiba = m_shiba.group(2)

    m_dart = re.search(
        r'<(?:h4|dt)[^>]*>\s*ダート\s*</(?:h4|dt)>(.{0,300}?)(' + baba_pat + r')',
        html, re.DOTALL
    )
    if m_dart:
        dart = m_dart.group(2)

    # パターン2: 芝/ダートの近くにある馬場状態（より緩いマッチ）
    if not shiba:
        m = re.search(r'>芝<.{0,200}?(' + baba_pat + r')', html, re.DOTALL)
        if m:
            shiba = m.group(1)

    if not dart:
        m = re.search(r'>ダート<.{0,200}?(' + baba_pat + r')', html, re.DOTALL)
        if m:
            dart = m.group(1)

    # パターン3: テキスト検索（最終手段）
    if not shiba or not dart:
        # 馬場状態セクションを切り出す
        m_sec = re.search(r'馬場状態.{0,3000}?週間', html, re.DOTALL)
        if m_sec:
            sec = m_sec.group(0)
            if not shiba:
                m = re.search(r'芝.{0,100}?(' + baba_pat + r')', sec, re.DOTALL)
                if m:
                    shiba = m.group(1)
            if not dart:
                m = re.search(r'ダート.{0,100}?(' + baba_pat + r')', sec, re.DOTALL)
                if m:
                    dart = m.group(1)

    return shiba, dart


def parse_course(html: str) -> tuple[str | None, bool]:
    """
    HTML から使用コース（A/B/C/D）とコース替わり初週フラグを解析。
    戻り値: (course_letter, is_course_change_week)
      course_letter: 'A'/'B'/'C'/'D' or None
      is_course_change_week: True = 今週がコース替わり初週
    """
    course = None
    is_change = False

    # 使用コースのパース
    # パターン1: <strong>C</strong>コース（HTMLタグ内に文字が入る形式）
    m = re.search(r'使用コース.{0,300}?<strong>\s*([A-D])\s*</strong>\s*コース', html, re.DOTALL)
    if m:
        course = m.group(1)
    # パターン2: プレーンテキスト形式「使用コース C コース」
    if not course:
        m = re.search(r'使用コース\s*([A-D])\s*コース', html)
        if m:
            course = m.group(1)

    # コース替わり初週の検出: 「今週から[X]コースを使用」
    if re.search(r'今週から[A-D]コースを使用', html):
        is_change = True

    return course, is_change


def parse_cushion_value(html: str) -> float | None:
    """クッション値（数値）を解析。動的ロードの場合は None。"""
    # クッション値の近くにある数値（X.X 形式）を探す
    m = re.search(r'クッション値.{0,500}?(\d{1,2}\.\d)', html, re.DOTALL)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    # 別パターン: 数値が先に来る場合
    m2 = re.search(r'(\d{1,2}\.\d).{0,200}?クッション', html, re.DOTALL)
    if m2:
        try:
            val = float(m2.group(1))
            if 3.0 <= val <= 20.0:  # 妥当な範囲チェック
                return val
        except ValueError:
            pass
    return None


def parse_weekly_rain(html: str, target_date_str: str) -> float | None:
    """
    週間降水量テーブルから対象日の降水量 (mm) を返す。
    target_date_str: 'YYYYMMDD' 形式
    """
    if not target_date_str or len(target_date_str) != 8:
        return None
    target_month = int(target_date_str[4:6])
    target_day   = int(target_date_str[6:8])

    # 週間天気セクションを切り出す
    week_section = html
    m_sec = re.search(r'週間(?:天気|降水量|予報)', html)
    if m_sec:
        week_section = html[m_sec.start():]

    # テーブルタグを見つけてパース
    table_pat = re.compile(r'<table[^>]*>(.*?)</table>', re.DOTALL)
    row_pat    = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL)
    cell_pat   = re.compile(r'<t[dh][^>]*>(.*?)</t[dh]>', re.DOTALL)
    tag_pat    = re.compile(r'<[^>]+>')

    def strip_tags(s):
        return tag_pat.sub('', s).strip()

    for table_m in table_pat.finditer(week_section[:20000]):
        table_html = table_m.group(1)
        rows = row_pat.findall(table_html)
        if len(rows) < 2:
            continue

        # ヘッダ行から日付列インデックスを特定
        header_cells = [strip_tags(c) for c in cell_pat.findall(rows[0])]
        date_col_idx = None
        for i, cell_text in enumerate(header_cells):
            # "24日（日）" や "5月24日（日）" などのパターン
            m_day = re.search(r'(\d+)月(\d+)日|(\d+)日', cell_text)
            if m_day:
                if m_day.group(3):
                    d = int(m_day.group(3))
                    m = None
                else:
                    d = int(m_day.group(2))
                    m = int(m_day.group(1))
                if d == target_day and (m is None or m == target_month):
                    date_col_idx = i
                    break

        if date_col_idx is None:
            continue

        # 降水量行を探す
        for row_html in rows[1:]:
            cells = [strip_tags(c) for c in cell_pat.findall(row_html)]
            if not cells:
                continue
            header = cells[0]
            if '降水量' in header or 'ミリ' in header or '雨量' in header:
                if date_col_idx < len(cells):
                    val_text = cells[date_col_idx]
                    m_val = re.search(r'(\d+\.?\d*)', val_text)
                    if m_val:
                        try:
                            return float(m_val.group(1))
                        except ValueError:
                            pass

    # フォールバック: 対象日付近のミリ値を正規表現で直接探す
    patterns = [
        rf'{target_day}日[^\n]{{0,500}}?(\d+\.\d+)\s*(?:mm|ミリ)',
        rf'降水量[^\n]{{0,200}}?' + str(target_day) + r'[^\n]{0,100}?(\d+\.\d+)',
    ]
    for pat in patterns:
        m = re.search(pat, week_section, re.DOTALL)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass

    return None


def estimate_race_baba(current_baba: str | None, rain_mm: float | None) -> tuple[str, str]:
    """
    現在馬場 + 降水量 → (推定馬場, 根拠文字列)

    降水量別の悪化目安:
      0mm     : 変化なし
      0-3mm   : 変化なし（少量）
      3-15mm  : 1ランク悪化（稍重化の可能性）
      15-30mm : 1ランク悪化（ほぼ確実）
      30mm以上 : 2ランク悪化
    """
    if not current_baba or current_baba not in BABA_LEVELS:
        return '良', '馬場情報なし（デフォルト:良）'

    idx = BABA_LEVELS.index(current_baba)
    rain = rain_mm if rain_mm is not None else 0.0

    if rain <= 0:
        degrade, reason = 0, f'降水なし'
    elif rain < 3:
        degrade, reason = 0, f'降水量{rain}mm（少量・影響小）'
    elif rain < 15:
        degrade, reason = 1, f'降水量{rain}mm → 1ランク悪化見込み'
    elif rain < 30:
        degrade, reason = 1, f'降水量{rain}mm → 稍重〜重相当'
    else:
        degrade, reason = 2, f'降水量{rain}mm → 重〜不良相当'

    new_idx = min(3, idx + degrade)
    estimated = BABA_LEVELS[new_idx]
    return estimated, f'現在馬場:{current_baba} + {reason}'


def fetch_baba_info(venue_name: str, date_str: str, debug: bool = False) -> dict:
    """
    指定会場のページを順番に検索してパース。
    どのページでも取得できない場合はデフォルト値を返す。
    debug=True のとき parse_html を baba_debug_<venue>.html に保存。
    """
    for suffix in PAGE_SUFFIXES:
        url = BASE_URL + suffix
        html = fetch_page(url)
        if html is None:
            continue

        # JRA馬場ページは 1ページ = 1会場。
        # ただし全ページのnavに全会場リンクが含まれるため、
        # 本文の h2 見出しや contents_header から会場を判定する。
        content_venue = detect_venue(html)
        if content_venue != venue_name:
            label = content_venue if content_venue else '不明'
            print(f'  [parse] {suffix}: コンテンツ会場={label}（対象: {venue_name}）→ スキップ')
            continue

        # 正しいページなので全体をパース（会場セクション分割不要）
        parse_html = html

        # デバッグ: parse_html をファイルに保存（--debug 時のみ）
        if debug:
            debug_path = pathlib.Path(f'baba_debug_{venue_name}.html')
            debug_path.write_text(parse_html, encoding='utf-8')
            print(f'  [debug] parse_html を {debug_path} に保存しました（{len(parse_html)} chars）')
            for kw in ['芝', 'ダート', '良', '稍重', '重', '不良', 'クッション']:
                status = 'あり' if kw in parse_html else 'なし'
                print(f'  [debug]   キーワード確認: "{kw}" → {status}')

        print(f'  [parse] {suffix}: {venue_name} を確認 → パース中...')

        shiba_baba, dart_baba  = parse_baba_jotai(parse_html)
        cushion                = parse_cushion_value(parse_html)
        rain_mm                = parse_weekly_rain(html, date_str)  # 降水量は全体から
        course, is_course_change = parse_course(parse_html)

        print(f'  [parse]   芝:{shiba_baba}  ダート:{dart_baba}  クッション:{cushion}  降水量:{rain_mm}mm  使用コース:{course}  コース替わり初週:{is_course_change}')

        est_shiba, shiba_reason = estimate_race_baba(shiba_baba, rain_mm)
        est_dart,  _            = estimate_race_baba(dart_baba,  rain_mm)

        return {
            '場所':              venue_name,
            '取得日時':          datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            '芝馬場':            shiba_baba,
            'ダート馬場':        dart_baba,
            'クッション値':      cushion,
            '降水量_mm':         rain_mm,
            '使用コース':        course,           # 'A'/'B'/'C'/'D' or None
            'コース替わり初週':  is_course_change,  # True = 今週がコース替わり初週
            '推定馬場_芝':       est_shiba,
            '推定馬場_ダート':   est_dart,
            '推定根拠':          shiba_reason,
        }

    # どのページでも該当会場が見つからなかった場合
    print(f'  [fetch_baba] {venue_name} の馬場情報ページが見つかりませんでした', file=sys.stderr)
    return {
        '場所':          venue_name,
        '取得日時':      datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '芝馬場':        None,
        'ダート馬場':    None,
        'クッション値':  None,
        '降水量_mm':     None,
        '推定馬場_芝':      '良',
        '推定馬場_ダート':  '良',
        '使用コース':       None,
        'コース替わり初週': False,
        '推定馬場_芝':      '良',
        '推定馬場_ダート':  '良',
        '使用コース':       None,
        'コース替わり初週': False,
        '推定根拠':         '情報取得失敗のためデフォルト(良)',
    }


def main():
    ap = argparse.ArgumentParser(description='JRA 馬場情報取得')
    ap.add_argument('--venue', required=True,
                    help='会場名またはコード (例: 東京, TK, ng, 阪神, HN)')
    ap.add_argument('--date',  required=True,
                    help='レース日 YYYYMMDD (例: 20260601)')
    ap.add_argument('--out',   default=None,
                    help='出力 JSON ファイルパス (省略時は stdout のみ)')
    ap.add_argument('--debug', action='store_true',
                    help='パース対象 HTML を baba_debug_<venue>.html に保存してデバッグ')
    args = ap.parse_args()

    venue = normalize_venue(args.venue)
    print(f'[fetch_baba] 会場={venue}  日付={args.date}')

    result = fetch_baba_info(venue, args.date, debug=args.debug)

    json_str = json.dumps(result, ensure_ascii=False, indent=2)
    print(json_str)

    if args.out:
        out_path = pathlib.Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_str, encoding='utf-8')
        print(f'[fetch_baba] → {out_path} に保存しました')


if __name__ == '__main__':
    main()
