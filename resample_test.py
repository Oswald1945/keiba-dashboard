# -*- coding: utf-8 -*-
"""
resample_test.py -- doneフォルダからランダムサンプリングして予想・回顧を再生成する

使い方:
  python resample_test.py                  # ランダム5レースを予想+回顧生成
  python resample_test.py --n 10           # 10レース
  python resample_test.py --n 5 --pred-only  # 予想のみ（回顧なし）
  python resample_test.py --race 20260530_kt12  # 特定レースを指定
  python resample_test.py --date 20260530  # 特定日のレースをすべて
  python resample_test.py --list           # 利用可能なレース一覧表示

動作:
  1. input/done/ からレースIDを収集
  2. ランダム（または指定）でサンプリング
  3. 必要ファイルを input/ に一時コピー
  4. run_new.py --force [--review] を実行
  5. 処理後に input/ から一時ファイルを削除
"""

import sys, os, re, shutil, subprocess, pathlib, random, argparse

SCRIPT_DIR = pathlib.Path(__file__).parent
INPUT_DIR  = SCRIPT_DIR / 'input'
DONE_DIR   = INPUT_DIR / 'done'

FILENAME_RE = re.compile(r'^(.+?)_(\d{8}_.+?)\.(csv|xlsx)$')

ALL_KINDS = ['過去走', '出馬表', '坂路', 'ウッド', 'レース結果', 'レースデータ']


def scan_done():
    """doneフォルダのレースIDと種別ファイルをスキャン"""
    races = {}
    for p in sorted(DONE_DIR.iterdir()):
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


def has_pred_data(files: dict) -> bool:
    """予想に必要なデータ（過去走+出馬表）があるか"""
    return '過去走' in files and '出馬表' in files


def has_review_data(files: dict) -> bool:
    """回顧に必要なデータ（レース結果）があるか"""
    return 'レース結果' in files


def copy_to_input(race_id: str, files: dict) -> list:
    """必要ファイルを input/ に一時コピーし、コピーしたパスのリストを返す"""
    copied = []
    for kind, src in files.items():
        dst = INPUT_DIR / src.name
        shutil.copy2(src, dst)
        copied.append(dst)
    return copied


def remove_from_input(copied: list):
    """input/ から一時コピーしたファイルを削除"""
    for p in copied:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


def clear_done_markers(race_ids: list):
    """指定レースの .done マーカーを削除して再生成を許可"""
    for race_id in race_ids:
        marker = SCRIPT_DIR / f'{race_id}_review.done'
        if marker.exists():
            marker.unlink()


def main():
    ap = argparse.ArgumentParser(description='doneフォルダからランダムサンプリング再生成')
    ap.add_argument('--n',        type=int, default=5,
                    help='サンプリングするレース数（デフォルト: 5）')
    ap.add_argument('--pred-only', action='store_true',
                    help='予想のみ生成（回顧スキップ）')
    ap.add_argument('--race',     default=None,
                    help='特定レースIDを指定（例: 20260530_kt12）')
    ap.add_argument('--date',     default=None,
                    help='特定日のレースをすべて指定（例: 20260530）')
    ap.add_argument('--list',     action='store_true',
                    help='利用可能なレース一覧を表示')
    ap.add_argument('--seed',     type=int, default=None,
                    help='乱数シード（再現性のため）')
    ap.add_argument('--all',      action='store_true',
                    help='doneフォルダの全レースを再生成')
    args = ap.parse_args()

    if not DONE_DIR.exists():
        print(f'[ERROR] {DONE_DIR} が見つかりません')
        sys.exit(1)

    all_races = scan_done()
    print(f'[resample] doneフォルダ: {len(all_races)}レース検出')

    # ── レース一覧表示 ─────────────────────────────────────────
    if args.list:
        pred_ok  = [(rid, f) for rid, f in sorted(all_races.items()) if has_pred_data(f)]
        rev_ok   = [(rid, f) for rid, f in sorted(all_races.items()) if has_review_data(f)]
        both_ok  = [(rid, f) for rid, f in sorted(all_races.items()) if has_pred_data(f) and has_review_data(f)]
        print(f'\n予想可能: {len(pred_ok)}R  回顧可能: {len(rev_ok)}R  両方可能: {len(both_ok)}R\n')
        for rid, files in sorted(all_races.items()):
            kinds = list(files.keys())
            can_pred = '✓予' if has_pred_data(files) else '  '
            can_rev  = '✓回' if has_review_data(files) else '  '
            print(f'  {rid}  {can_pred} {can_rev}  {kinds}')
        return

    # ── サンプリング対象を決定 ────────────────────────────────────
    if args.race:
        if args.race not in all_races:
            print(f'[ERROR] レース {args.race} がdoneフォルダに見つかりません')
            sys.exit(1)
        targets = [(args.race, all_races[args.race])]

    elif args.date:
        targets = [(rid, f) for rid, f in sorted(all_races.items())
                   if rid.startswith(args.date)]
        if not targets:
            print(f'[ERROR] {args.date} のレースがdoneフォルダに見つかりません')
            sys.exit(1)
        print(f'[resample] {args.date}: {len(targets)}レース')

    elif args.all:
        # doneフォルダの全レースを対象（予想データあり）
        targets = [(rid, f) for rid, f in sorted(all_races.items()) if has_pred_data(f)]
        print(f'[resample] 全レース: {len(targets)}R を再生成します')

    else:
        # 予想データがあるレースからランダム選択
        candidates = [(rid, f) for rid, f in all_races.items() if has_pred_data(f)]
        if args.seed is not None:
            random.seed(args.seed)
        n = min(args.n, len(candidates))
        targets = random.sample(candidates, n)
        targets.sort(key=lambda x: x[0])

    # ── 処理 ───────────────────────────────────────────────────
    print(f'\n[resample] 対象レース ({len(targets)}R):')
    for rid, _ in targets:
        print(f'  {rid}')

    # doneマーカーを削除して再生成を許可
    clear_done_markers([rid for rid, _ in targets])

    copied_files = []
    try:
        for rid, files in targets:
            copied = copy_to_input(rid, files)
            copied_files.extend(copied)
            print(f'  [copy] {rid}: {len(copied)}ファイルをinput/にコピー')

        # 予想生成
        print(f'\n[resample] 予想ダッシュボード生成中...')
        cmd_pred = [sys.executable, str(SCRIPT_DIR / 'run_new.py'), '--force']
        result = subprocess.run(cmd_pred, cwd=str(SCRIPT_DIR))

        # 回顧生成
        if not args.pred_only:
            # 回顧には結果ファイルが必要
            rev_targets = [(rid, f) for rid, f in targets if has_review_data(f)]
            if rev_targets:
                print(f'\n[resample] 回顧ダッシュボード生成中 ({len(rev_targets)}R)...')
                # 回顧用に結果ファイルを再コピー（pred処理でdoneに移動した場合に備え）
                for rid, files in rev_targets:
                    result_file = files.get('レース結果')
                    if result_file and result_file.exists():
                        dst = INPUT_DIR / result_file.name
                        if not dst.exists():
                            shutil.copy2(result_file, dst)
                            copied_files.append(dst)
                clear_done_markers([rid for rid, _ in rev_targets])
                cmd_rev = [sys.executable, str(SCRIPT_DIR / 'run_new.py'), '--review', '--force']
                subprocess.run(cmd_rev, cwd=str(SCRIPT_DIR))
            else:
                print('\n[resample] 回顧対象（結果ファイルあり）なし → スキップ')

    finally:
        # 一時ファイルを削除
        remove_from_input(copied_files)
        print(f'\n[resample] 一時ファイル {len(copied_files)}件を削除しました')

    print('\n[resample] 完了')


if __name__ == '__main__':
    main()
