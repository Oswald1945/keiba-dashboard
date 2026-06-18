# -*- coding: utf-8 -*-
"""factor-level accuracy diagnostics across all scored+resulted races"""
import pathlib, re
import pandas as pd, numpy as np
from scipy.stats import spearmanr

SD = pathlib.Path(__file__).parent
DONE = SD / 'input' / 'done'

FACTORS = ['総合スコア','最高出力pts','クラスpts','時計pts','展開pts','斤量pts','距離pts',
           'コース適性pts','臨戦pts','人気補正pts','騎手pts','馬体重pts','継続pts','着差pts',
           '枠順pts','昇級pts','馬場適性pts','SmartRC評価pts']

def load_res(rid):
    p = DONE / f'レース結果_{rid}.csv'
    if not p.exists(): return None
    try:
        df = pd.read_csv(p, encoding='cp932', header=2, on_bad_lines='skip')
        df.columns=[str(c).strip() for c in df.columns]
        df=df[pd.to_numeric(df['入線順位'],errors='coerce').notna()].copy()
        df['着順']=pd.to_numeric(df['入線順位'],errors='coerce').astype(int)
        df['人気']=pd.to_numeric(df['人気'],errors='coerce')
        df['単勝オッズ']=pd.to_numeric(df['単勝オッズ'],errors='coerce')
        df['馬名']=df['馬名'].astype(str).str.strip()
        return df[['馬名','着順','人気','単勝オッズ']].dropna(subset=['着順'])
    except Exception as e:
        return None

def load_scr(rid):
    p = SD / f'scores_{rid}.csv'
    if not p.exists(): return None
    try:
        df=pd.read_csv(p,encoding='utf-8-sig')
        df.columns=[str(c).strip() for c in df.columns]
        df['馬名']=df['馬名'].astype(str).str.strip()
        for c in FACTORS+['順位予想']:
            if c in df.columns:
                df[c]=pd.to_numeric(df[c],errors='coerce')
        return df
    except Exception:
        return None

res_races={f.stem.replace('レース結果_','') for f in DONE.glob('レース結果_*.csv') if '_dup' not in f.name}
scr_races={f.stem.replace('scores_','') for f in SD.glob('scores_*.csv')}
targets=sorted(res_races & scr_races)

all_rows=[]
per_factor_rho={c:[] for c in FACTORS}
n_ok=0
for rid in targets:
    res=load_res(rid); scr=load_scr(rid)
    if res is None or scr is None: continue
    m=scr.merge(res,on='馬名',how='inner')
    if len(m)<5: continue
    n_ok+=1
    m['race']=rid
    # within-race factor correlation to finish (negate: higher pts should -> lower 着順)
    for c in FACTORS:
        if c in m.columns and m[c].notna().sum()>=4 and m[c].std()>0:
            rho,_=spearmanr(m[c], -m['着順'])
            if not np.isnan(rho): per_factor_rho[c].append(rho)
    all_rows.append(m)

big=pd.concat(all_rows,ignore_index=True)
print(f"races={n_ok}  horses={len(big)}")
print("\n=== 因子別 within-race Spearman (因子pts vs 好走) 平均 ===")
print("(正で高いほど『得点が高い馬ほど実際に上位』= 予測に効いている)")
rows=[]
for c in FACTORS:
    v=per_factor_rho[c]
    if v: rows.append((c,np.mean(v),len(v)))
for c,mu,k in sorted(rows,key=lambda x:-x[1]):
    bar='#'*int(max(0,mu)*50)
    print(f"  {c:14s} rho={mu:+.3f} (n={k}) {bar}")

# popularity (人気) as a factor baseline
pr=[]
for rid,g in big.groupby('race'):
    if g['人気'].notna().sum()>=4 and g['人気'].std()>0:
        rho,_=spearmanr(g['人気'],-g['着順'])  # 人気1=最有力 -> negate? 人気小さいほど上位
        # 人気 small=favorite; finish small=win. correlation of 人気 vs 着順 should be positive.
        rho2,_=spearmanr(-g['人気'],-g['着順'])
        if not np.isnan(rho2): pr.append(rho2)
print(f"\n  【参考】人気        rho={np.mean(pr):+.3f} (n={len(pr)})")

# total score vs popularity head-to-head
print("\n=== 総合スコア1位 vs 人気1位 の決着 ===")
win_model=win_pop=both=0; n=0
for rid,g in big.groupby('race'):
    g=g.dropna(subset=['総合スコア','人気','着順'])
    if len(g)<5: continue
    n+=1
    mp=g.loc[g['総合スコア'].idxmax(),'馬名']
    pp=g.loc[g['人気'].idxmin(),'馬名']
    w=g[g['着順']==1]['馬名'].tolist()
    if mp in w: win_model+=1
    if pp in w: win_pop+=1
    if mp==pp: both+=1
print(f"  対象{n}R  モデル予想1位がモデル=人気1位と一致: {both}R ({both/n:.0%})")
print(f"  単勝的中: モデル1位 {win_model}/{n} ({win_model/n:.0%})  人気1位 {win_pop}/{n} ({win_pop/n:.0%})")

# when model disagrees with favorite, who is right?
print("\n=== モデル1位 ≠ 人気1位 のレースのみ ===")
mw=pw=0; nd=0
for rid,g in big.groupby('race'):
    g=g.dropna(subset=['総合スコア','人気','着順'])
    if len(g)<5: continue
    mp=g.loc[g['総合スコア'].idxmax(),'馬名']
    pp=g.loc[g['人気'].idxmin(),'馬名']
    if mp==pp: continue
    nd+=1
    w=g[g['着順']==1]['馬名'].tolist()
    t3=g[g['着順']<=3]['馬名'].tolist()
    if mp in w: mw+=1
    if pp in w: pw+=1
print(f"  不一致{nd}R中: モデル推し勝利 {mw}R ({mw/nd:.0%})  人気1位勝利 {pw}R ({pw/nd:.0%})")

# calibration: model rank1 finish distribution
print("\n=== モデル予想1位の実着順分布 ===")
fin=[]
for rid,g in big.groupby('race'):
    g=g.dropna(subset=['総合スコア','着順'])
    if len(g)<5: continue
    fin.append(int(g.loc[g['総合スコア'].idxmax(),'着順']))
fin=pd.Series(fin)
print(f"  1着{(fin==1).mean():.0%} 2着{(fin==2).mean():.0%} 3着{(fin==3).mean():.0%} 着外{(fin>3).mean():.0%}  平均着順{fin.mean():.2f}")
