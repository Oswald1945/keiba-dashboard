# -*- coding: utf-8 -*-
"""
verify_course_bias.py — コース別 内外バイアス(course_bias.json)が予測に効くかを再検証する。

input/done/ のレース結果CSVから検証用データを毎回組み直し、各馬の「コース静的バイアス
への適合度」が人気(市場)を統制しても好走を予測するか（直交性）と、人気帯別の頑健性、
単勝ROIを出力する。結果が貯まったら同じコマンドで再評価できる。

使い方:  python verify_course_bias.py
判定基準: 人気統制後ρが正で有意(p<0.05)かつ人気帯別の符号が一貫していれば「効く」候補。
         2026-06時点(123R)では ρ≈+0.02(非有意)＝市場が織込済みで未採用。
"""
import json
import pathlib
import warnings
import pandas as pd
import numpy as np
from scipy.stats import spearmanr

warnings.filterwarnings('ignore')
SD = pathlib.Path(__file__).parent
DONE = SD / 'input' / 'done'


def build_master():
    rows = []
    for f in DONE.glob('レース結果_*.csv'):
        if '_dup' in f.name:
            continue
        rid = f.stem.replace('レース結果_', '')
        try:
            m = pd.read_csv(f, encoding='cp932', header=0, nrows=1, on_bad_lines='skip').iloc[0]
            df = pd.read_csv(f, encoding='cp932', header=2, on_bad_lines='skip')
            df.columns = [str(c).strip() for c in df.columns]
            df = df[pd.to_numeric(df['入線順位'], errors='coerce').notna()].copy()
            if len(df) < 4:
                continue
            d = pd.DataFrame()
            d['着順'] = pd.to_numeric(df['入線順位'], errors='coerce')
            for c in ['人気', '馬番', '枠番', '単勝オッズ']:
                d[c] = pd.to_numeric(df.get(c), errors='coerce')
            d['race'] = rid
            d['場所'] = str(m.get('場所', '')).strip()
            d['距離'] = pd.to_numeric(m.get('距離'), errors='coerce')
            d['surface'] = str(m.get('芝・ダート', '')).strip()
            d['頭数'] = pd.to_numeric(m.get('頭数'), errors='coerce')
            rows.append(d)
        except Exception:
            pass
    return pd.concat(rows, ignore_index=True).dropna(subset=['着順', '人気'])


def main():
    cb = json.load(open(SD / 'course_bias.json', encoding='utf-8'))
    b = build_master()
    b['surf'] = b['surface'].map(lambda s: 'ダ' if 'ダ' in str(s) else '芝')

    def ckey(r):
        base = f"{r['場所']}{r['surf']}{int(r['距離'])}"
        for suf in ['', '外', '内']:
            if base + suf in cb:
                return base + suf
        return None

    b['ckey'] = b.apply(ckey, axis=1)
    m = b.dropna(subset=['着順', '人気', '馬番', '頭数', 'ckey']).copy()
    print(f"検証 {m['race'].nunique()}R / {len(m)}頭 / {m['ckey'].nunique()}コース")
    m['inner_rate'] = m['ckey'].map(lambda k: cb[k]['inner'])
    m['outer_rate'] = m['ckey'].map(lambda k: cb[k]['outer'])
    m['innerness'] = 1 - (m['馬番'] - 1) / (m['頭数'] - 1).clip(lower=1)
    m['draw_score'] = m['inner_rate'] * m['innerness'] + m['outer_rate'] * (1 - m['innerness'])
    m['bias_align'] = (m['inner_rate'] - m['outer_rate']) * (m['innerness'] - 0.5) * 2
    m['win'] = (m['着順'] == 1).astype(int)
    m['plc'] = (m['着順'] <= 3).astype(int)

    def partial(col, label):
        d = m.dropna(subset=[col, '人気', '着順'])
        if d[col].std() == 0:
            print(f"  {label}: skip")
            return

        def rs(y, x):
            x = x.values.astype(float); y = y.values.astype(float)
            bb = np.polyfit(x, y, 1); return y - np.polyval(bb, x)
        rf = rs(d[col], d['人気']); ry = rs(d['着順'].astype(float), d['人気'])
        rho, p = spearmanr(rf, -ry); raw, _ = spearmanr(d[col], -d['着順'])
        print(f"  {label:22s} n={len(d):4d} 生ρ={raw:+.3f} 人気統制後ρ={rho:+.3f} p={p:.3g}")

    print("=== コース内外バイアスの市場直交性 ===")
    partial('draw_score', 'draw_score')
    partial('bias_align', 'bias_align')
    print("  人気帯別ρ(bias_align):", end=' ')
    for lo, hi, nm in [(1, 3, '1-3'), (4, 8, '4-8'), (9, 99, '9+')]:
        s = m[(m['人気'] >= lo) & (m['人気'] <= hi)].dropna(subset=['bias_align', '着順'])
        if len(s) > 30 and s['bias_align'].std() > 0:
            rho, _ = spearmanr(s['bias_align'], -s['着順']); print(f"{nm}:{rho:+.2f}", end='  ')
    print()
    q = m['bias_align'].quantile(0.8)
    for mask, lbl in [(m['bias_align'] >= q, 'バイアス適合上位20%'),
                      (m['bias_align'] <= m['bias_align'].quantile(0.2), 'バイアス逆行下位20%')]:
        d = m[mask].dropna(subset=['単勝オッズ'])
        if len(d):
            print(f"  {lbl:22s} 賭{len(d):4d} 勝率{d['win'].mean():.1%} 単回収{(d['win']*d['単勝オッズ']).mean()*100:5.1f}%")


if __name__ == '__main__':
    main()
