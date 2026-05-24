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

import sys, re, shutil, subprocess, pathlib, webbrowser

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


def publish_to_github(html_path: pathlib.Path) -> str | None:
    """git add / commit / push して GitHub Pages URL を返す"""
    try:
        # stale な index.lock を事前に除去
        lock_file = SCRIPT_DIR / '.git' / 'index.lock'
        if lock_file.exists():
            lock_file.unlink()
            print('  [share] index.lock を削除しました')
        git = ['git', '-C', str(SCRIPT_DIR)]
        subprocess.run(git + ['add', str(html_path)], check=True)
        msg = f'pred: {html_path.stem}'
        result = subprocess.run(
            git + ['commit', '-m', msg],
            capture_output=True, text=True
        )
        if result.returncode not in (0, 1):
            print(f'  [share] git commit 失敗: {result.stderr.strip()}')
            return None
        push = subprocess.run(
            git + ['push', 'origin', 'main'],
            capture_output=True, text=True
        )
        if push.returncode != 0:
            print(f'  [share] git push 失敗: {push.stderr.strip()}')
            return None
        url = f'{GITHUB_PAGES_BASE}/{html_path.name}'
        return url
    except Exception as e:
        print(f'  [share] GitHub Pages 公開エラー: {e}')
        return None



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


def process_race(race_id, files):
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
        # --share 指定時は生成済の HTML も強制公開
        if FORCE_SHARE and not DRY_RUN:
            html_p = OUT_DIR / f'pred_{race_id}.html'
            if html_p.exists():
                print(f'  [share] {html_p.name} を GitHub に公開中...')
                share_url = publish_to_github(html_p)
                if share_url:
                    print(f'  ╔══════════════════════════════════════════╗')
                    print(f'  ║  共有URL: {share_url}')
                    print(f'  ╚══════════════════════════════════════════╝')
                    with open(SHARE_URL_LOG, 'a', encoding='utf-8') as _lg:
                        _lg.write(f'{race_id}\t{share_url}\n')
                    webbrowser.open(share_url)
    elif kako is None or shutuba is None:
        print(f'  [pred] 過去走 or 出馬表がない -> スキップ')
        if FORCE_PRED:
            print(f'  [force] --force 指定でも過去走/出馬表が不足しているためスキップ')
    else:
        cmd = [sys.executable, SCORE_PY,
               '--excel', kako, '--shutuba', shutuba, '--outdir', OUT_DIR]
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
        run_cmd([sys.executable, DASH_PY,
                 '--json', json_p, '--outdir', OUT_DIR], 'pred')
        generated_pred = True
        # 生成した HTML を共有URLに変換してブラウザで自動表示
        if not DRY_RUN:
            html_p = OUT_DIR / f'pred_{race_id}.html'
            if html_p.exists():
                print(f'  [share] {html_p.name} を GitHub に公開中...')
                share_url = publish_to_github(html_p)
                if share_url:
                    print(f'  ╔════════════════════════════════════════════╗')
                    print(f'  ║  共有URL: {share_url:<38}║')
                    print(f'  ╚════════════════════════════════════════════╝')
                    # URLをログファイルに記録
                    with open(SHARE_URL_LOG, 'a', encoding='utf-8') as _lg:
                        _lg.write(f'{race_id}\t{share_url}\n')
                    webbrowser.open(share_url)
                else:
                    # upload失敗時はローカルをブラウザで開く
                    webbrowser.open(html_p.as_uri())
                    print(f'  [browser] {html_p.name} をローカルで開きました')

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
        # 実行前の review HTML 一覧を記録
        _before = set(OUT_DIR.glob('*_review.html'))
        run_cmd(cmd, 'review')
        mark_review_done(race_id)
        generated_review = True
        # 新しく生成された review HTML を GitHub に公開
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
                    with open(SHARE_URL_LOG, 'a', encoding='utf-8') as _lg:
                        _lg.write(f'{race_id}_review\t{share_url}\n')
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
    for race_id, files in sorted(races.items()):
        try:
            process_race(race_id, files)
        except Exception as e:
            errors.append((race_id, str(e)))
            print(f'  [ERROR] {race_id}: {e}')

    print('\n=== 完了 ===')
    if errors:
        for rid, msg in errors:
            print(f'  {rid}: {msg}')


if __name__ == '__main__':
    main()
