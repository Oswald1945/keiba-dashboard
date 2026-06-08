# -*- coding: utf-8 -*-
"""
validate_accuracy.py -- 過去レースのスコアと実着順を照合して精度を検証する

使い方:
  python validate_accuracy.py           # 全対象レースを検証
  python validate_accuracy.py --detail  # 各レースの詳細も表示
"""

import pathlib, argparse, re
import pandas as pd
import numpy as np
from scipy.stats import spearmanr

SCRIPT_DIR = pathlib.Path(__file__).parent
DONE_DIR   = SCRIPT_DIR / 'input' / 'done'
SCORES_DIR = SCRIPT_DIR

# ────────────────────────────────────────────
def load_result_file(race_id: str) -> pd.DataFrame | None:
    """レース結果CSVを読み込み、馬名・着順・人気を返す"""
    path = DONE_DIR / f'レース結果_{race_id}.csv'
    if not path.exists():
        return None
    try:
        # Row0=レースメタ列名, Row1=値, Row2=馬データ列名, Row3+=馬データ
        df = pd.read_csv(path, encoding='cp932', header=2,
                         on_bad_lines='skip')
        df.columns = [str(c).strip() for c in df.columns]
        # 着順が数値の行だけ残す
        df = df[pd.to_numeric(df['入線順位'], errors='coerce').notna()].copy()
        df['着順'] = pd.to_numeric(df['入線順位'], errors='coerce').astype(int)
        df['人気'] = pd.to_numeric(df['人気'], errors='coerce')
        df['馬名'] = df['馬名'].astype(str).str.strip()
        return df[['馬名', '着順', '人気']].dropna(subset=['着順'])
    except Exception as e:
        print(f"  [WARN] {race_id} 結果読込エラー: {e}")
        return None


def load_score_file(race_id: str) -> pd.DataFrame | None:
    """scores_*.csv を読み込み、馬名・順位予想・総合スコアを返す"""
    path = SCORES_DIR / f'scores_{race_id}.csv'
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, encoding='utf-8-sig')
        df.columns = [str(c).strip() for c in df.columns]
        df['馬名'] = df['馬名'].astype(str).str.strip()
        df['順位予想'] = pd.to_numeric(df['順位予想'], errors='coerce').astype(int)
        df['総合スコア'] = pd.to_numeric(df['総合スコア'], errors='coerce')
        return df[['馬名', '順位予想', '総合スコア']].dropna()
    except Exception as e:
        print(f"  [WARN] {race_id} スコア読込エラー: {e}")
        return None


def analyze_race(race_id: str, detail: bool = False):
    """1レースの精度指標を返す dict。失敗時は None。"""
    res = load_result_file(race_id)
    scr = load_score_file(race_id)
    if res is None or scr is None:
        return None

    merged = scr.merge(res, on='馬名', how='inner')
    if len(merged) < 3:
        return None  # マッチ馬数少なすぎ

    # 順位でソートして予想1位～3位を取得
    pred_top3 = merged.nsmallest(3, '順位予想')['馬名'].tolist()
    pred_1st  = pred_top3[0] if pred_top3 else None

    # 実着1位・3着以内
    actual_1st   = merged[merged['着順'] == 1]['馬名'].tolist()
    actual_top3  = merged[merged['着順'] <= 3]['馬名'].tolist()

    win_hit      = int(pred_1st in actual_1st) if pred_1st else 0
    place_hit    = int(pred_1st in actual_top3) if pred_1st else 0
    top3_overlap = len(set(pred_top3) & set(actual_top3))  # 0–3

    # スピアマン相関 (予想順位 vs 実着順)
    corr_df = merged.dropna(subset=['順位予想','着順'])
    if len(corr_df) >= 4:
        rho, pval = spearmanr(corr_df['順位予想'], corr_df['着順'])
    else:
        rho, pval = float('nan'), float('nan')

    # 人気1位 vs 予想1位 一致チェック（ベースライン比較用）
    pop1_horse = res[res['人気'] == 1]['馬名'].tolist()
    pop1_win   = int(any(h in actual_1st for h in pop1_horse)) if pop1_horse else 0
    pop1_place = int(any(h in actual_top3 for h in pop1_horse)) if pop1_horse else 0

    if detail:
        print(f"\n  {race_id}  頭数={len(merged)}")
        print(f"    予想1位: {pred_1st}  実着1位: {actual_1st}")
        print(f"    予想top3: {pred_top3}  実着top3: {actual_top3}")
        print(f"    単勝的中={win_hit}  複勝的中={place_hit}  top3重複={top3_overlap}  ρ={rho:.3f}")

    return {
        'race_id'      : race_id,
        'n_horses'     : len(merged),
        'win_hit'      : win_hit,
        'place_hit'    : place_hit,
        'top3_overlap' : top3_overlap,
        'spearman_rho' : rho,
        'pop1_win'     : pop1_win,
        'pop1_place'   : pop1_place,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--detail', action='store_true')
    args = ap.parse_args()

    # 両方存在するレースを収集（_dup除外）
    result_races = {
        f.stem.replace('レース結果_', '')
        for f in DONE_DIR.glob('レース結果_*.csv')
        if '_dup' not in f.name
    }
    score_races = {
        f.stem.replace('scores_', '')
        for f in SCORES_DIR.glob('scores_*.csv')
    }
    targets = sorted(result_races & score_races)
    print(f"対象: {len(targets)} レース\n")

    records = []
    for race_id in targets:
        r = analyze_race(race_id, detail=args.detail)
        if r:
            records.append(r)

    if not records:
        print("有効レースなし")
        return

    df = pd.DataFrame(records)
    n  = len(df)

    # ── 集計 ──────────────────────────────────────────────────
    win_rate    = df['win_hit'].mean()
    place_rate  = df['place_hit'].mean()
    top3_rate   = df['top3_overlap'].mean()
    mean_rho    = df['spearman_rho'].mean(skipna=True)
    pop1_win    = df['pop1_win'].mean()
    pop1_place  = df['pop1_place'].mean()

    # top3_overlap別分布
    ov_dist = df['top3_overlap'].value_counts().sort_index().to_dict()

    print("=" * 55)
    print(f"  検証レース数          : {n}R")
    print(f"  平均頭数              : {df['n_horses'].mean():.1f}頭")
    print()
    print("  【予想スコア】")
    print(f"  予想1位 単勝的中率    : {win_rate:.1%}  ({df['win_hit'].sum()}/{n}R)")
    print(f"  予想1位 複勝的中率    : {place_rate:.1%}  ({df['place_hit'].sum()}/{n}R)")
    print(f"  予想top3 着3内重複数  : {top3_rate:.2f}/3  (3={ov_dist.get(3,0)}R 2={ov_dist.get(2,0)}R 1={ov_dist.get(1,0)}R 0={ov_dist.get(0,0)}R)")
    print(f"  スピアマン相関 (平均) : {mean_rho:.3f}")
    print()
    print("  【ベースライン: 単純1番人気】")
    print(f"  1番人気 単勝的中率    : {pop1_win:.1%}")
    print(f"  1番人気 複勝的中率    : {pop1_place:.1%}")
    print()
    print("  ※ 単勝的中率の一般的な1番人気ベースライン: ~33%前後")
    print("=" * 55)

    # ── 日付グループ別集計 ──────────────────────────────────────
    df['date'] = df['race_id'].str[:8]
    print("\n  【開催日別集計】")
    for date, grp in df.groupby('date'):
        yr, mo, dy = date[:4], date[4:6], date[6:]
        wr = grp['win_hit'].mean()
        pr = grp['place_hit'].mean()
        print(f"  {yr}/{mo}/{dy}  {len(grp):2d}R   単勝{wr:.0%}  複勝{pr:.0%}")

    # CSV保存
    out = SCRIPT_DIR / 'validation_result.csv'
    df.to_csv(out, index=False, encoding='utf-8-sig')
    print(f"\n  詳細: {out}")


if __name__ == '__main__':
    main()
