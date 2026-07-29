# -*- coding: utf-8 -*-
"""配分比率の再検討: 現行コードで再スコアした因子(/tmp/audit_rows.jsonl)と実結果を突合し、
各因子の『実好走への予測力』を人気統制の有無で測る。
  raw_rho    : within-race Spearman(因子pts, 好走=-着順) の平均（市場込みの生予測力）
  partial_rho: 人気(市場)を統制した偏Spearman の平均（市場超過情報＝本当の上乗せ価値）
  rho_pop    : 因子pts と 人気 の相関（市場をどれだけ写しているか）
出力: analyze_weights_report.md
"""
import json, pathlib
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

SD = pathlib.Path(__file__).parent
DONE = SD / 'input' / 'done'
ROWS = '/tmp/audit_rows.jsonl'

FACTORS = ['最高出力pts','クラスpts','時計pts','コース適性pts','上がりpts','SmartRC評価pts',
           'コース特徴pts','着差pts','馬場適性pts','クラス適応pts','臨戦pts','騎手pts',
           '継続pts','昇級pts','斤量pts','距離pts','枠順pts','馬体重pts','人気補正pts','総合スコア']


import result_loader as _rl

def load_res(rid):
    for ext in ('.csv', '.html'):
        p = DONE / f'レース結果_{rid}{ext}'
        if not p.exists(): continue
        try:
            df, _, _ = _rl.load_result(str(p))
            df.columns = [str(c).strip() for c in df.columns]
            oc = '入線順位' if '入線順位' in df.columns else ('着順' if '着順' in df.columns else None)
            if oc is None or '馬名' not in df.columns: continue
            df = df[pd.to_numeric(df[oc], errors='coerce').notna()].copy()
            df['着順'] = pd.to_numeric(df[oc], errors='coerce').astype(int)
            df['人気'] = pd.to_numeric(df.get('人気'), errors='coerce')
            df['単勝'] = pd.to_numeric(df.get('単勝オッズ'), errors='coerce')
            df['馬名'] = df['馬名'].astype(str).str.strip()
            out = df[['馬名','着順','人気','単勝']].dropna(subset=['着順'])
            if len(out) >= 5: return out
        except Exception:
            continue
    return None


def partial_spearman(x, y, z):
    """z を統制した x,y の偏Spearman。"""
    rxy = spearmanr(x, y).correlation
    rxz = spearmanr(x, z).correlation
    ryz = spearmanr(y, z).correlation
    for r in (rxy, rxz, ryz):
        if r is None or np.isnan(r): return np.nan
    den = np.sqrt((1 - rxz**2) * (1 - ryz**2))
    if den == 0: return np.nan
    return (rxy - rxz * ryz) / den


def main():
    races = {}
    for l in open(ROWS, encoding='utf-8'):
        r = json.loads(l); races.setdefault(r['rid'], []).append(r)

    raw = {f: [] for f in FACTORS}
    part = {f: [] for f in FACTORS}
    rpop = {f: [] for f in FACTORS}
    pop_raw = []
    n_ok = 0
    for rid, rows in races.items():
        res = load_res(rid)
        if res is None: continue
        sdf = pd.DataFrame(rows)
        m = sdf.merge(res, on='馬名', how='inner')
        if len(m) < 5: continue
        n_ok += 1
        good = -m['着順'].values            # 好走(大きいほど上位)
        mkt  = -m['人気'].values            # 市場評価(大きいほど人気=有力)
        if pd.Series(mkt).notna().sum() >= 4 and pd.Series(mkt).std() > 0:
            rr = spearmanr(mkt, good).correlation
            if rr is not None and not np.isnan(rr): pop_raw.append(rr)
        for f in FACTORS:
            v = pd.to_numeric(m[f], errors='coerce').values
            if pd.Series(v).notna().sum() < 4 or pd.Series(v).std() == 0: continue
            rr = spearmanr(v, good).correlation
            if rr is not None and not np.isnan(rr): raw[f].append(rr)
            rp = spearmanr(v, mkt).correlation
            if rp is not None and not np.isnan(rp): rpop[f].append(rp)
            if pd.Series(mkt).std() > 0:
                pr = partial_spearman(v, good, mkt)
                if not np.isnan(pr): part[f].append(pr)

    def mean(a): return float(np.mean(a)) if a else float('nan')

    lines = [f'# 配分比率の再検討: 因子の予測力（{n_ok}レース）\n']
    lines.append('| 因子 | raw_rho(生) | partial_rho(人気統制後) | rho_pop(市場相似) | n |')
    lines.append('|---|--:|--:|--:|--:|')
    order = sorted(FACTORS, key=lambda f: -(mean(part[f]) if part[f] else -9))
    for f in order:
        lines.append(f'| {f} | {mean(raw[f]):+.3f} | **{mean(part[f]):+.3f}** | {mean(rpop[f]):+.3f} | {len(part[f])} |')
    lines.append(f'\n【参考】人気(市場) の生予測力 raw_rho = {mean(pop_raw):+.3f}')
    lines.append('\n**読み方**: partial_rho が正で大きい因子＝市場が知らない好走情報を持つ（増幅候補）。0付近〜負＝市場をなぞるだけ/逆張りで重み低下の候補。rho_pop が高いほど市場と重複。')
    rep = SD / 'analyze_weights_report.md'
    rep.write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))
    print('\nwrote', rep)


if __name__ == '__main__':
    main()
