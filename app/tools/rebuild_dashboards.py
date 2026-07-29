# -*- coding: utf-8 -*-
"""既存のダッシュボードHTMLを、いまのコードで作り直す。

配色・フォント・スマホ対応の変更は「これから生成するもの」にしか効かないため、
過去に作ったHTMLは古い見た目のまま残る。それを一括で作り直す。

やること:
  1. 既存の *_pred.html / *_review.html を控えに丸ごとコピー（先にこれをやる）
  2. horses_data_{race_id}.json から予想HTMLを作り直す
  3. 結果CSVがあるレースは回顧HTMLも作り直す

やらないこと:
  - 採点はしない（horses_data / scores.csv には触らない。数値は変わらない）
  - もともとHTMLが無かったレースには新しく作らない（--all で作れる）
  - 公開はしない

戻し方:
    python app/tools/rebuild_dashboards.py --restore <控えフォルダ名>

使い方:
    python app/tools/rebuild_dashboards.py            # 確認のみ（作り直さない）
    python app/tools/rebuild_dashboards.py --apply    # 実際に作り直す
    python app/tools/rebuild_dashboards.py --apply --limit 3   # まず3件だけ試す
"""
from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import time
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.backend import config                              # noqa: E402
from app.backend.services import catalog, paths, runner     # noqa: E402

KIND_RESULT = 'レース結果'
KIND_RACEDATA = '出馬表'


def is_current_format(race_id: str) -> bool:
    """いまの build_dashboard_v3.py が描ける形の horses_data かどうか。

    採点モデルの改訂で因子が変わっており、古いデータには
    「コース特徴pts」「トラックバイアスpts」が無い（代わりに「展開pts」がある）。
    そのまま渡すと KeyError で落ちるので、先に見分ける。
    描き直したい場合は再採点が必要＝スコアの数値が変わるため、ここでは触らない。
    """
    import json
    try:
        d = json.loads(paths.horses_json(race_id).read_text(encoding='utf-8'))
        h = (d.get('horses') or [{}])[0]
    except Exception:
        return False
    return 'コース特徴pts' in h


def backup_dir_root() -> pathlib.Path:
    return config.BACKUP_DIR / 'dashboards'


def take_backup(files: list) -> pathlib.Path:
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dest = backup_dir_root() / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(f, dest / f.name)
    return dest


def restore(name: str) -> int:
    src = backup_dir_root() / name
    if not src.is_dir():
        print(f'控えが見つかりません: {src}')
        return 1
    files = sorted(src.glob('*.html'))
    for f in files:
        shutil.copy2(f, config.OUT_DIR / f.name)
    print(f'{len(files)} 件を {name} の状態に戻しました。')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--apply', action='store_true', help='実際に作り直す（既定は確認のみ）')
    ap.add_argument('--all', action='store_true',
                    help='HTMLが無かったレースにも新しく作る（既定は既存分のみ）')
    ap.add_argument('--limit', type=int, default=0, help='先頭N件だけ処理する（試運転用）')
    ap.add_argument('--from', dest='date_from', default='', metavar='YYYYMMDD',
                    help='この日以降のレースだけ作り直す')
    ap.add_argument('--to', dest='date_to', default='', metavar='YYYYMMDD',
                    help='この日までのレースだけ作り直す')
    ap.add_argument('--pred-only', action='store_true',
                    help='予想HTMLだけ作り直す（回顧側に変更が無いときの無駄打ちを避ける）')
    ap.add_argument('--restore', metavar='フォルダ名', help='控えの状態に戻す')
    args = ap.parse_args()

    if args.restore:
        return restore(args.restore)

    rows = [r for r in catalog.list_races() if paths.horses_json(r['race_id']).exists()]
    if args.date_from:
        rows = [r for r in rows if r['date'] >= args.date_from]
    if args.date_to:
        rows = [r for r in rows if r['date'] <= args.date_to]
    rows.sort(key=lambda r: r['race_id'])

    want_pred = [r for r in rows if args.all or r['has_pred']]
    preds = [r for r in want_pred if is_current_format(r['race_id'])]
    skipped = len(want_pred) - len(preds)
    revs = [] if args.pred_only else [
        r for r in rows
        if (args.all or r['has_review']) and KIND_RESULT in paths.input_files(r['race_id'])]
    if args.limit:
        preds, revs = preds[:args.limit], revs[:args.limit]

    # 触らないものまで控えに取ると時間と容量が無駄なので、作り直す側だけ控える。
    existing = [p for p in config.OUT_DIR.glob('*_pred.html')]
    if not args.pred_only:
        existing += [p for p in config.OUT_DIR.glob('*_review.html')]

    print(f'レース数            : {len(rows)}')
    print(f'  作り直す予想HTML  : {len(preds)}')
    print(f'  見送る予想HTML    : {skipped}（採点モデルが変わる前のデータ。'
          f'描き直すには再採点が必要＝数値が変わるので触らない）')
    print(f'  作り直す回顧HTML  : {len(revs)}')
    print(f'  控えに取るファイル: {len(existing)}')
    if not args.apply:
        print()
        print('※ 確認のみです。作り直すには --apply を付けてください。')
        return 0

    dest = take_backup(existing)
    print(f'\n控えを取りました: {dest}')
    print(f'（戻すとき: python app/tools/rebuild_dashboards.py --restore {dest.name}）\n')

    t0 = time.time()
    ok_p = ng_p = ok_r = ng_r = 0
    errors = []

    for i, r in enumerate(preds, 1):
        rid = r['race_id']
        res = runner.build_pred(rid, paths.horses_json(rid), config.OUT_DIR)
        if res.ok and res.outputs.get('pred_html'):
            ok_p += 1
        else:
            ng_p += 1
            errors.append(f'予想 {rid}: {(res.stderr or "").strip().splitlines()[-1:] or res.returncode}')
        if i % 25 == 0:
            print(f'  予想 {i}/{len(preds)} 件 ({time.time() - t0:.0f}秒)')

    for i, r in enumerate(revs, 1):
        rid = r['race_id']
        files = paths.input_files(rid)
        def _build(racedata):
            return runner.build_review(
                race_id=rid,
                result_file=files[KIND_RESULT],
                horses_json=paths.horses_json(rid),
                scores_csv=paths.scores_csv(rid),
                outdir=config.OUT_DIR,
                racedata=racedata,
            )

        res = _build(files.get(KIND_RACEDATA))
        if not res.ok and files.get(KIND_RACEDATA) is not None:
            # 結果がCSVのとき、出馬表を渡すと result_loader が
            # 「1行目＝見出し」と解釈してしまい、入線順位を取れない。
            # CSV自身が先頭2行にメタを持つ形式なので、渡さずに読ませ直す。
            res = _build(None)
        if res.ok and res.outputs.get('review_html'):
            ok_r += 1
        else:
            ng_r += 1
            errors.append(f'回顧 {rid}: {(res.stderr or "").strip().splitlines()[-1:] or res.returncode}')
        if i % 25 == 0:
            print(f'  回顧 {i}/{len(revs)} 件 ({time.time() - t0:.0f}秒)')

    paths.clear_html_index_cache()
    print()
    print(f'完了: {time.time() - t0:.0f}秒')
    print(f'  予想 成功 {ok_p} / 失敗 {ng_p}')
    print(f'  回顧 成功 {ok_r} / 失敗 {ng_r}')
    if errors:
        print('\n失敗した分:')
        for e in errors[:20]:
            print('  ', e)
    print(f'\n元に戻すとき: python app/tools/rebuild_dashboards.py --restore {dest.name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
