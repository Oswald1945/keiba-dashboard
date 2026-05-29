# -*- coding: utf-8 -*-
"""
run_new.py -- 新規レース自動検出・ダッシュボード生成スクリプト
=============================================================
使い方:
  python run_new.py          # input/ の未処理レースをすべて処理
  python run_new.py --dry    # 処理対象の確認のみ（実際には実行しない）
  python run_new.py --force  # pred生成済でも強制再生成

動作:
  1. input/ フォルダのCSV/xlsxをスキャンし、レースIDごとにグループ化
  2. pred 未生成のレースは予想ダッシュボードを生成
     完了マーカー: horses_data_{race_id}.json の存在
  3. pred 済み & レース結果あり & review 未生成なら回顧ダッシュボードを生成
     完了マーカー: {race_id}_review.done ファイルの存在
  4. pred と review の両方が完了したら input/ のファイルを input/done/ へ移動

ファイル命名規則:
  {種別}_{日付}_{レースID}.csv  例: 過去走_20260222_t11.csv

処理済みフォルダ:
  input/done/  <-- pred/review ともに完了後に移動
"""

import sys, re, shutil, subprocess, pathlib, webbrowser, json, datetime

SCRIPT_DIR = pathlib.Path(__file__).parent
INPUT_DIR  = SCRIPT_DIR / 'input'
DONE_DIR   = INPUT_DIR / 'done'
OUT_DIR    = SCRIPT_DIR

SCORE_PY = SCRIPT_DIR / 'score_horse_v3.py'
DASH_PY  = SCRIPT_DIR / 'build_dashboard_v3.py'
REV_PY   = SCRIPT_DIR / 'build_review.py'

KIND_KAKO     = '過去走'
KIND_SHUTUBA  = '出馬表'
KIND_SAKURO   = '坂路'
KIND_WOOD     = 'ウッド'
KIND_RESULT   = 'レース結果'
KIND_RACEDATA = 'レースデータ'
ALL_KINDS = [KIND_KAKO, KIND_SHUTUBA, KIND_SAKURO, KIND_WOOD, KIND_RESULT, KIND_RACEDATA]

FILENAME_RE = re.compile(r'^(.+?)_(\d{8}_.+?)\.(csv|xlsx)$')
DRY_RUN     = '--dry' in sys.argv or '--dry-run' in sys.argv
FORCE_SHARE = '--share' in sys.argv  # pred生成済のHTMLも強制公開
FORCE_PRED  = '--force' in sys.argv  # pred生成済でも強制再生成

SHARE_URL_LOG = SCRIPT_DIR / 'shared_urls.txt'
GITHUB_PAGES_BASE = 'https://oswald1945.github.io/keiba-dashboard'

FETCH_BABA_PY = SCRIPT_DIR / 'fetch_baba.py'

# 会場コード → 場所名マッピング（大文字化してから参照）
_VENUE_CODE_MAP = {
    'TK': '東京', 'CB': '中山', 'HN': '阪神', 'KT': '京都', 'KY': '京都',
    'CK': '中京', 'NK': '新潟', 'NG': '新潟', 'HK': '函館', 'SM': '札幌',
    'FK': '福島', 'KO': '小倉', 'KK': '小倉',
}

def extract_venue_from_race_id(race_id: str) -> str | None:
    """race_id (例: 20260524_TK8, 20260601_ng8) から会場名を取得する"""
    m = re.match(r'^\d{8}_([A-Za-z]+)\d+', race_id)
    if not m:
        return None
    code = m.group(1).upper()
    return _VENUE_CODE_MAP.get(code)


def update_memo_from_review(html_path: pathlib.Path) -> int:
    """回顧HTMLから次走注目馬を抽出して memo_horses.json に追記する。戻り値は追加頭数。"""
    MEMO_JSON = SCRIPT_DIR / 'memo_horses.json'
    PLACE_MAP = {
        'CK': '中京', 'TK': '東京', 'HN': '阪神', 'NK': '新潟',
        'KT': '京都', 'KY': '京都', 'CB': '中山', 'HK': '函館',
        'SM': '札幌', 'FK': '福島', 'OI': '大井', 'KW': '川崎',
        'HS': '浦和', 'SK': '船橋',
    }
    try:
        html = html_path.read_text(encoding='utf-8', errors='ignore')
        names = re.findall(r'<div class="pickup-name"><b>([^<]+)</b></div>', html)
        if not names:
            return 0
        # レース情報をtitleタグから抽出
        m_title = re.search(
            r'<title>レース回顧\s+(.+?)(\d+)R\s+([^<]*?)\s+(\d{4}/\d{2}/\d{2})</title>', html
        )
        if m_title:
            place    = m_title.group(1).strip()
            rnum     = int(m_title.group(2))
            rname    = m_title.group(3).strip()
            date_str = m_title.group(4)
        else:
            stem = html_path.stem
            m_fn = re.match(r'(\d{4})(\d{2})(\d{2})_([A-Z]+)(\d+)R_(.+?)(?:_review)?$', stem)
            if not m_fn:
                return 0
            y, mo, d = m_fn.group(1), m_fn.group(2), m_fn.group(3)
            place    = PLACE_MAP.get(m_fn.group(4), m_fn.group(4))
            rnum     = int(m_fn.group(5))
            rname    = m_fn.group(6)
            date_str = f'{y}/{mo}/{d}'
        # 既存データ読み込み
        existing = []
        if MEMO_JSON.exists():
            try:
                existing = json.loads(MEMO_JSON.read_text(encoding='utf-8'))
            except Exception:
                pass
        existing_keys = {
            f"{e.get('馬名','')}|{e.get('元レース',{}).get('日付','')}|{e.get('元レース',{}).get('R','')}"
            for e in existing
        }
        today = datetime.date.today().isoformat()
        added = 0
        for name in names:
            key = f'{name}|{date_str}|{rnum}'
            if key not in existing_keys:
                existing.append({
                    '馬名': name,
                    '登録日': today,
                    '追加者': '',
                    '元レース': {'日付': date_str, '場所': place, 'R': rnum, 'レース名': rname, 'クラス': ''},
                    'メモ': '',
                })
                existing_keys.add(key)
                added += 1
        if added > 0:
            MEMO_JSON.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2), encoding='utf-8'
            )
            print(f'  [memo] {added}頭を memo_horses.json に追加しました')
        return added
    except Exception as e:
        print(f'  [memo] 更新エラー: {e}')
        return 0


def publish_batch_to_github(html_paths: list) -> list:
    """複数HTMLを一括 git add / commit / push して GitHub Pages URL リストを返す"""
    if not html_paths:
        return []
    try:
        lock_file = SCRIPT_DIR / '.git' / 'index.lock'
        if lock_file.exists():
            lock_file.unlink()
            print('[share] index.lock を削除しました')
        git = ['git', '-C', str(SCRIPT_DIR)]
        memo_json = SCRIPT_DIR / 'memo_horses.json'
        files_to_add = [str(p) for p in html_paths]
        if memo_json.exists():
            files_to_add.append(str(memo_json))
        subprocess.run(git + ['add'] + files_to_add, check=True)
        date_tag = html_paths[0].stem.split('_')[1] if '_' in html_paths[0].stem else 'batch'
        msg = f'pred: {date_tag} {len(html_paths)}レース'
        result = subprocess.run(
            git + ['commit', '-m', msg],
            capture_output=True, text=True
        )
        if result.returncode not in (0, 1):
            print(f'[share] git commit 失敗: {result.stderr.strip()}')
            return []
        push = subprocess.run(
            git + ['push', 'origin', 'main'],
            capture_output=True, text=True
        )
        if push.returncode != 0:
            print(f'[share] git push 失敗: {push.stderr.strip()}')
            return []
        return [f'{GITHUB_PAGES_BASE}/{p.name}' for p in html_paths]
    except Exception as e:
        print(f'[share] GitHub Pages 公開エラー: {e}')
        return []


def publish_to_github(html_path: pathlib.Path) -> str | None:
    """後方互換用: 単一HTML を publish_batch_to_github に委譲"""
    urls = publish_batch_to_github([html_path])
    return urls[0] if urls else None



def scan_input():
    races = {}
    for p in sorted(INPUT_DIR.iterdir()):
        if p.is_dir():
            continue
        m = FILENAME_RE.match(p.name)
        if not m:
            continue
        kind, race_id, _ = m.groups()
        if kind not in ALL_KINDS:
            continue
        if race_id not in races:
            races[race_id] = {}
        existing = races[race_id].get(kind)
        if existing is None or p.suffix.lower() == '.csv':
            races[race_id][kind] = p
    return races


def pred_done(race_id):
    return (OUT_DIR / f'horses_data_{race_id}.json').exists()


def review_done(race_id):
    return (OUT_DIR / f'{race_id}_review.done').exists()


def mark_review_done(race_id):
    if not DRY_RUN:
        (OUT_DIR / f'{race_id}_review.done').touch()


def move_to_done(files):
    DONE_DIR.mkdir(exist_ok=True)
    for p in files:
        if p is None or not p.exists():
            continue
        dest = DONE_DIR / p.name
        if dest.exists():
            dest = DONE_DIR / f'{p.stem}_dup{p.suffix}'
        if not DRY_RUN:
            shutil.move(str(p), str(dest))
        print(f'    -> done/ へ移動: {p.name}')


def run_cmd(cmd, label):
    print(f'  [{label}] 実行中...')
    if DRY_RUN:
        print(f'    (--dry モード: スキップ)')
        return
    r = subprocess.run([str(c) for c in cmd])
    if r.returncode != 0:
        raise RuntimeError(f'{label} が失敗 (code={r.returncode})')


def process_race(race_id, files) -> pathlib.Path | None:
    """レースを処理し、新規生成した pred HTML のパスを返す（なければ None）"""
    print(f'\n[Race] {race_id}')
    detected = ', '.join(k for k in ALL_KINDS if k in files)
    print(f'  検出: {detected}')

    kako     = files.get(KIND_KAKO)
    shutuba  = files.get(KIND_SHUTUBA)
    sakuro   = files.get(KIND_SAKURO)
    wood     = files.get(KIND_WOOD)
    result   = files.get(KIND_RESULT)
    racedata = files.get(KIND_RACEDATA)

    json_p   = OUT_DIR / f'horses_data_{race_id}.json'
    scores_p = OUT_DIR / f'scores_{race_id}.csv'

    already_pred   = pred_done(race_id)
    already_review = review_done(race_id)
    generated_pred   = False
    generated_review = False
    new_pred_html    = None

    # SmartRC JSON 自動検出 & 自動取得
    smartrc_json = OUT_DIR / f'smartrc_{race_id}.json'
    if not smartrc_json.exists() and not DRY_RUN:
        # JSON がなければ smartrc_fetch.py で自動取得を試みる
        _fetch_py = SCRIPT_DIR / 'smartrc_fetch.py'
        if _fetch_py.exists():
            print(f'  [SmartRC] JSONなし → races/view で自動取得を試みます...')
            try:
                _env = {**__import__('os').environ, 'PYTHONIOENCODING': 'utf-8'}
                _proc = subprocess.run(
                    [sys.executable, str(_fetch_py), race_id, '--out'],
                    capture_output=True, timeout=45, env=_env
                )
                _out = (_proc.stdout or b'').decode('utf-8', errors='replace')
                _err_txt = (_proc.stderr or b'').decode('utf-8', errors='replace')
                if smartrc_json.exists():
                    print(f'  [SmartRC] ✓ 自動取得成功: {smartrc_json.name}')
                else:
                    # 失敗ログを1行だけ表示
                    _lines = (_out + _err_txt).splitlines()
                    _err = next((l for l in _lines if any(
                        k in l for k in ['失敗', 'Error', 'エラー', 'races/view'])), '')
                    if _err:
                        print(f'  [SmartRC] 自動取得失敗: {_err.strip()[:80]}')
                    print(f'  [SmartRC] → 手動取得: python smartrc_fetch.py --rcode XXXX --out')
            except subprocess.TimeoutExpired:
                print(f'  [SmartRC] 自動取得タイムアウト → 手動取得してください')
            except Exception as _e:
                print(f'  [SmartRC] 自動取得スキップ: {_e}')
    if not smartrc_json.exists():
        smartrc_json = None

    if already_pred and not FORCE_PRED:
        print(f'  [pred] 生成済 -> スキップ (--force で強制再生成可能)')
        # --share 指定時は生成済の HTML も一括push対象に追加
        if FORCE_SHARE and not DRY_RUN:
            html_p = OUT_DIR / f'pred_{race_id}.html'
            if html_p.exists():
                new_pred_html = html_p
    elif kako is None or shutuba is None:
        print(f'  [pred] 過去走 or 出馬表がない -> スキップ')
        if FORCE_PRED:
            print(f'  [force] --force 指定でも過去走/出馬表が不足しているためスキップ')
    else:
        # ── 馬場情報取得 (fetch_baba.py) ────────────────────────────
        baba_json = None
        estimated_baba = '良'
        if FETCH_BABA_PY.exists() and not DRY_RUN:
            _venue = extract_venue_from_race_id(race_id)
            _date  = race_id[:8]  # YYYYMMDD 部分
            if _venue:
                baba_json = OUT_DIR / f'baba_{race_id}.json'
                print(f'  [baba] {_venue} の馬場情報を取得中...')
                try:
                    _env = {**__import__('os').environ, 'PYTHONIOENCODING': 'utf-8'}
                    _proc = subprocess.run(
                        [sys.executable, str(FETCH_BABA_PY),
                         '--venue', _venue, '--date', _date, '--out', str(baba_json)],
                        capture_output=True, timeout=30, env=_env
                    )
                    if baba_json.exists():
                        import json as _j
                        _bi = _j.loads(baba_json.read_text(encoding='utf-8'))
                        # 芝/ダートを判定して適切な推定馬場を選択
                        # shutuba から芝ダの情報を取得（簡易判定: race_id に 'ダ' がなければ芝）
                        _surface = 'dart' if 'ダ' in race_id else 'turf'
                        if _surface == 'dart':
                            estimated_baba = _bi.get('推定馬場_ダート') or '良'
                        else:
                            estimated_baba = _bi.get('推定馬場_芝') or '良'
                        print(f'  [baba] 推定馬場: {estimated_baba}（{_bi.get("推定根拠","")}）')
                    else:
                        _out = (_proc.stdout or b'').decode('utf-8', errors='replace')
                        _err = (_proc.stderr or b'').decode('utf-8', errors='replace')
                        print(f'  [baba] 取得失敗: {(_out + _err).strip()[:80]}')
                        baba_json = None
                except subprocess.TimeoutExpired:
                    print(f'  [baba] タイムアウト → デフォルト(良)で継続')
                    baba_json = None
                except Exception as _e:
                    print(f'  [baba] スキップ: {_e}')
                    baba_json = None
            else:
                print(f'  [baba] race_id から会場を特定できず → デフォルト(良)で継続')

        cmd = [sys.executable, SCORE_PY,
               '--excel', kako, '--shutuba', shutuba, '--outdir', OUT_DIR,
               '--baba', estimated_baba]
        if sakuro:      cmd += ['--sakuro',  sakuro]
        if wood:        cmd += ['--wood',    wood]
        if smartrc_json:
            cmd += ['--smartrc', smartrc_json]
            print(f'  [SmartRC] 評価証正を適用: {smartrc_json.name}')
        run_cmd(cmd, 'score')
        if not DRY_RUN:
            src_json   = OUT_DIR / 'horses_data.json'
            src_scores = OUT_DIR / 'scores.csv'
            if src_json.exists():
                shutil.copy2(src_json,   json_p);   src_json.unlink()
            if src_scores.exists():
                shutil.copy2(src_scores, scores_p); src_scores.unlink()
        dash_cmd = [sys.executable, DASH_PY,
                    '--json', json_p, '--outdir', OUT_DIR]
        if baba_json and baba_json.exists():
            dash_cmd += ['--baba-json', str(baba_json)]
        run_cmd(dash_cmd, 'pred')
        generated_pred = True
        if not DRY_RUN:
            html_p = OUT_DIR / f'pred_{race_id}.html'
            if html_p.exists():
                new_pred_html = html_p  # 一括push用に記録（main側で処理）

    if already_review:
        print(f'  [review] 生成済 -> スキップ')
    elif result is None:
        print(f'  [review] 結果ファイルなし -> 結果待ち')
    elif not json_p.exists() and not DRY_RUN:
        print(f'  [review] JSONがない -> スキップ')
    else:
        cmd = [sys.executable, REV_PY,
               '--result', result, '--horses', json_p,
               '--scores', scores_p, '--outdir', OUT_DIR]
        if racedata:
            cmd += ['--racedata', racedata]
        _before = set(OUT_DIR.glob('*_review.html'))
        run_cmd(cmd, 'review')
        mark_review_done(race_id)
        generated_review = True
        if not DRY_RUN:
            _new = set(OUT_DIR.glob('*_review.html')) - _before
            if _new:
                review_html_p = next(iter(_new))
                print(f'  [share] {review_html_p.name} を GitHub に公開中...')
                share_url = publish_to_github(review_html_p)
                if share_url:
                    print(f'  ╔════════════════════════════════════════════╗')
                    print(f'  ║  共有URL: {share_url:<38}║')
                    print(f'  ╚════════════════════════════════════════════╝')
                    # 重複排除してURL記録
                    _ex: dict[str, str] = {}
                    if SHARE_URL_LOG.exists():
                        for _l in SHARE_URL_LOG.read_text(encoding='utf-8').splitlines():
                            _p = _l.split('\t')
                            if len(_p) == 2:
                                _ex[_p[0]] = _p[1]
                    _ex[f'{race_id}_review'] = share_url
                    with open(SHARE_URL_LOG, 'w', encoding='utf-8') as _lg:
                        for _k, _v in sorted(_ex.items()):
                            _lg.write(f'{_k}\t{_v}\n')
                    webbrowser.open(share_url)
                else:
                    webbrowser.open(review_html_p.as_uri())
                    print(f'  [browser] {review_html_p.name} をローカルで開きました')

    pred_ok   = already_pred   or generated_pred
    review_ok = already_review or generated_review or result is None

    if pred_ok and review_ok:
        move_to_done(list(files.values()))
        print(f'  [OK] {race_id} 完了 -> done/ へ移動')
    elif pred_ok:
        print(f'  [wait] {race_id} 予想のみ完了 -> 結果を input/ に追加して再実行')
    else:
        print(f'  [NG] {race_id} 未完了')

    return new_pred_html if generated_pred and not DRY_RUN else None


def main():
    print('=== run_new.py ===')
    if DRY_RUN:
        print('  (--dry mode)')

    if not INPUT_DIR.exists():
        print(f'input/ が見つかりません')
        return

    races = scan_input()
    if not races:
        print('input/ に処理対象ファイルなし')
        return

    print(f'検出: {len(races)} レース')
    errors = []
    new_htmls = []
    for race_id, files in sorted(races.items()):
        try:
            html = process_race(race_id, files)
            if html:
                new_htmls.append(html)
        except Exception as e:
            errors.append((race_id, str(e)))
            print(f'  [ERROR] {race_id}: {e}')

    # 新規生成HTMLを一括push
    if new_htmls and not DRY_RUN:
        print(f'\n[share] {len(new_htmls)}件のHTMLを GitHub に一括公開中...')
        urls = publish_batch_to_github(new_htmls)
        if urls:
            # 既存ログを読み込み、重複排除してから上書き保存
            existing_entries: dict[str, str] = {}
            if SHARE_URL_LOG.exists():
                for line in SHARE_URL_LOG.read_text(encoding='utf-8').splitlines():
                    parts = line.split('\t')
                    if len(parts) == 2:
                        existing_entries[parts[0]] = parts[1]
            for html, url in zip(new_htmls, urls):
                race_id = html.stem.replace('pred_', '')
                existing_entries[race_id] = url
            with open(SHARE_URL_LOG, 'w', encoding='utf-8') as lg:
                for rid, url in sorted(existing_entries.items()):
                    lg.write(f'{rid}\t{url}\n')
            print(f'[share] 公開完了: {len(urls)}件')
            print(f'[share] 共有URL一覧 ({SHARE_URL_LOG.name}):')
            for url in urls:
                print(f'  {url}')
        else:
            print('[share] push 失敗 → ローカルHTMLで確認してください')

    print('\n=== 完了 ===')
    if errors:
        for rid, msg in errors:
            print(f'  {rid}: {msg}')


if __name__ == '__main__':
    main()
