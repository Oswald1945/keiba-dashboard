# -*- coding: utf-8 -*-
"""回帰テストの基準データ（ゴールデン）を作る。

使い方（ふつうは run_make_golden.bat をダブルクリック）:
    python app/tests/make_golden.py --limit 100

やっていること:
  1. input/done/ に入力CSVが残っていて、採点済みのレースを候補にする
  2. 端ケース（地方馬あり・馬場が良以外・SmartRCあり・坂路/ウッド欠け 等）を
     必ず含むようにレースを選ぶ
  3. 選んだレースの入力CSVを app/tests/golden/ にコピーする
  4. 「今のコード」で採点・予想HTML・回顧HTMLを作り直し、その出力を基準として保存する

注意:
  基準は「今のコードの出力」です。過去に生成された horses_data_*.json は
  当時のコード（P3/P4 採用前など）で作られているため一致しません。
  これから採点ロジックを変更したときに、変わってはいけない所が変わって
  いないかを見るための基準です。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.backend import config                       # noqa: E402
from app.backend.services import paths               # noqa: E402
from app.tests import golden_lib as gl               # noqa: E402


def _candidates() -> list:
    """採点済み＋入力CSVが揃っているレースを集める。"""
    out = []
    for p in config.OUT_DIR.glob('horses_data_*.json'):
        race_id = p.name[len('horses_data_'):-len('.json')]
        key = paths.parse_race_id(race_id)
        if key is None:
            continue
        files = paths.input_files(race_id)
        if gl.KIND_KAKO not in files or gl.KIND_SHUTUBA not in files:
            continue
        try:
            data = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            continue
        meta = data.get('meta') or {}
        horses = data.get('horses') or []
        ri = meta.get('race_info') or {}

        top = max(horses, key=lambda h: h.get('総合スコア') or -9e9, default=None)
        top_odds = (top or {}).get('単勝オッズ')

        out.append({
            'race_id': race_id,
            'date': key.date,
            'venue': key.venue,
            'files': files,
            'baba': meta.get('baba') or '良',
            'race_class': str(ri.get('クラス名', '')).strip(),
            'surface': str(ri.get('芝ダ', '')).strip(),
            'has_local_only': any(h.get('地方実績のみ') for h in horses),
            'has_smartrc': paths.smartrc_json(race_id).exists()
                           or gl.find_optional(f'smartrc_{race_id}.json') is not None,
            'has_result': gl.KIND_RESULT in files,
            'missing_training': (gl.KIND_SAKURO not in files) or (gl.KIND_WOOD not in files),
            # スコア1位が人気薄＝勝率cap で軸が動く可能性が高いレース
            'wide_top_odds': bool(top_odds and float(top_odds) >= 10.0),
        })
    out.sort(key=lambda r: r['date'], reverse=True)
    return out


# 端ケースの取りこぼしを防ぐための割当（合計が limit を超えたら新しい順で調整）
_STRATA = [
    ('地方実績のみの馬を含む', lambda r: r['has_local_only'], 12),
    ('馬場が良以外', lambda r: r['baba'] != '良', 12),
    ('スコア1位が人気薄(勝率cap)', lambda r: r['wide_top_odds'], 12),
    ('坂路orウッドが欠け', lambda r: r['missing_training'], 8),
    ('SmartRCあり', lambda r: r['has_smartrc'], 8),
    ('レース結果あり(回顧)', lambda r: r['has_result'], 20),
    ('ダート', lambda r: r['surface'] in ('ダ', 'ダート'), 10),
]


def select(cands: list, limit: int) -> tuple:
    chosen: dict = {}
    report = []
    for label, pred, quota in _STRATA:
        hit = [c for c in cands if pred(c)]
        added = 0
        for c in hit:
            if len(chosen) >= limit:
                break
            if c['race_id'] in chosen:
                continue
            chosen[c['race_id']] = c
            added += 1
            if added >= quota:
                break
        report.append((label, len(hit), added))
    # 残りは新しい順で埋める
    for c in cands:
        if len(chosen) >= limit:
            break
        chosen.setdefault(c['race_id'], c)
    return list(chosen.values()), report


def build_case(cand: dict, force: bool) -> str:
    race_id = cand['race_id']
    case_dir = gl.GOLDEN_DIR / race_id
    if case_dir.exists() and not force:
        return 'skip'
    if case_dir.exists():
        shutil.rmtree(case_dir)
    inputs = case_dir / 'inputs'
    inputs.mkdir(parents=True, exist_ok=True)

    manifest = {
        'race_id': race_id,
        'date': cand['date'],
        'venue': cand['venue'],
        'baba': cand['baba'],
        'race_class': cand['race_class'],
        'surface': cand['surface'],
        'inputs': {},
        'traits': {k: cand[k] for k in
                   ('has_local_only', 'has_smartrc', 'has_result',
                    'missing_training', 'wide_top_odds')},
    }

    for kind, src in cand['files'].items():
        shutil.copy2(src, inputs / src.name)
        manifest['inputs'][kind] = src.name

    for label, name in (('smartrc', f'smartrc_{race_id}.json'),
                        ('baba_json', f'baba_{race_id}.json'),
                        ('haraimodoshi', f'haraimodoshi_{race_id}.json')):
        src = gl.find_optional(name)
        if src is not None:
            shutil.copy2(src, inputs / name)
            manifest[label] = name

    # 時間で変わりうる外部依存を記録（テスト時に前提崩れを検出するため）
    manifest['track_bias_sources'] = gl.track_bias_sources(race_id, cand['venue'])
    manifest['effective_memo_sha256'] = gl.effective_memo_hash(cand['date'])

    (case_dir / gl.MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    with tempfile.TemporaryDirectory(prefix=f'golden_{race_id}_') as tmp:
        rep = gl.reproduce(race_id, case_dir, manifest, Path(tmp))

    exp = case_dir / 'expected'
    gl.write_gz(exp / 'horses_data.json.gz', rep.horses_data)
    gl.write_gz(exp / 'scores.csv.gz', rep.scores_csv)
    digests = {}
    if rep.pred_html:
        digests['pred_html_sha256'] = gl.sha256_bytes(rep.pred_html)
        digests['pred_html_bytes'] = len(rep.pred_html)
    if rep.review_html:
        digests['review_html_sha256'] = gl.sha256_bytes(rep.review_html)
        digests['review_html_bytes'] = len(rep.review_html)
    (exp / 'digests.json').write_text(
        json.dumps(digests, ensure_ascii=False, indent=2), encoding='utf-8')

    if rep.review_error:
        # 回顧が既存コード側の理由で作れなかった。基準には「作れない」と記録する。
        manifest['review_error'] = rep.review_error
        (case_dir / gl.MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        return 'built_no_review'
    return 'built'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=100, help='作る基準レース数')
    ap.add_argument('--force', action='store_true', help='既にある基準も作り直す')
    ap.add_argument('--only', default=None, help='特定の race_id だけ')
    args = ap.parse_args()

    print('=== 回帰テストの基準データ作成 ===')
    cands = _candidates()
    print(f'候補レース: {len(cands)} 件（採点済み＋入力CSVあり）')
    if not cands:
        print('候補がありません。input/done/ に入力CSVが残っているか確認してください。')
        return 1

    if args.only:
        picked = [c for c in cands if c['race_id'] == args.only]
        report = []
        if not picked:
            print(f'{args.only} は候補にありません。')
            return 1
    else:
        picked, report = select(cands, args.limit)
        print('\n--- 端ケースの内訳 ---')
        for label, hit, added in report:
            print(f'  {label}: 候補{hit}件 → 採用{added}件')
        print(f'--- 合計 {len(picked)} 件を基準にします ---\n')

    gl.GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    built = skipped = failed = 0
    no_review = []
    t0 = time.time()
    for i, c in enumerate(sorted(picked, key=lambda x: x['race_id']), 1):
        rid = c['race_id']
        try:
            status = build_case(c, force=args.force)
        except Exception as e:
            failed += 1
            print(f'[{i}/{len(picked)}] {rid} 失敗: {type(e).__name__}: {str(e)[:300]}')
            continue
        if status == 'skip':
            skipped += 1
            print(f'[{i}/{len(picked)}] {rid} 既存のためスキップ')
        else:
            built += 1
            if status == 'built_no_review':
                no_review.append(rid)
            el = time.time() - t0
            mark = '（回顧は生成できず）' if status == 'built_no_review' else ''
            print(f'[{i}/{len(picked)}] {rid} 作成{mark} （経過 {el/60:.1f}分）')

    print(f'\n作成 {built} / スキップ {skipped} / 失敗 {failed}'
          f' （所要 {(time.time()-t0)/60:.1f}分）')
    if no_review:
        print(f'\n【要確認】回顧HTMLを生成できなかったレース {len(no_review)} 件:')
        for rid in no_review:
            err = json.loads((gl.GOLDEN_DIR / rid / gl.MANIFEST_NAME)
                             .read_text(encoding='utf-8')).get('review_error', '')
            print(f'  {rid}: {err[:160]}')
        print('  → これは既存 build_review.py 側の失敗です（アプリの問題ではありません）。')
    print(f'保存先: {gl.GOLDEN_DIR}')
    return 0 if failed == 0 else 2


if __name__ == '__main__':
    raise SystemExit(main())
