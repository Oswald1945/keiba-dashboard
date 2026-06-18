# -*- coding: utf-8 -*-
"""value test: does the model carry information BEYOND the market, and is it +EV?
   - conditional signal: within popularity strata, does model score still predict finish?
   - single-win ROI backtest on 'model overlay' horses (model rates higher than market)
"""
import pathlib
import pandas as pd, numpy as np
from scipy.stats import spearmanr

SD=pathlib.Path(__file__).parent
DONE=SD/'input'/'done'
DEAD=['SmartRC評価pts','昇級pts','斤量pts','枠順pts','臨戦pts']

def load_res(rid):
    p=DONE/f'レース結果_{rid}.csv'
    if not p.exists(): return None
    try:
        df=pd.read_csv(p,encoding='cp932',header=2,on_bad_lines='skip')
        df.columns=[str(c).strip() for c in df.columns]
        df=df[pd.to_numeric(df['入線順位'],errors='coerce').notna()].copy()
        df['着順']=pd.to_numeric(df['入線順位'],errors='coerce').astype(int)
        df['人気']=pd.to_numeric(df['人気'],errors='coerce')
        df['単勝オッズ']=pd.to_numeric(df['単勝オッズ'],errors='coerce')
        df['馬名']=df['馬名'].astype(str).str.strip()
        return df[['馬名','着順','人気','単勝オッズ']].dropna(subset=['着順','人気'])
    except: return None

def load_scr(rid):
    p=SD/f'scores_{rid}.csv'
    if not p.exists(): return None
    try:
        df=pd.read_csv(p,encoding='utf-8-sig')
        df.columns=[str(c).strip() for c in df.columns]
        df['馬名']=df['馬名'].astype(str).str.strip()
        for c in df.columns:
            if c.endswith('pts') or c=='総合スコア': df[c]=pd.to_numeric(df[c],errors='coerce')
        return df
    except: return None

res_races={f.stem.replace('レース結果_','') for f in DONE.glob('レース結果_*.csv') if '_dup' not in f.name}
scr_races={f.stem.replace('scores_','') for f in SD.glob('scores_*.csv')}
targets=sorted(res_races&scr_races)

def model_minus_dead(g):
    s=g['総合スコア'].copy()
    for c in DEAD:
        if c in g.columns: s=s-g[c].fillna(0)
    return s

rows=[]
for rid in targets:
    res=load_res(rid); scr=load_scr(rid)
    if res is None or scr is None: continue
    g=scr.merge(res,on='馬名',how='inner')
    if len(g)<5: continue
    g=g.dropna(subset=['総合スコア','人気','着順']).copy()
    if len(g)<5: continue
    g['model_rank']=g['総合スコア'].rank(ascending=False,method='first')
    g['clean']=model_minus_dead(g)
    g['clean_rank']=g['clean'].rank(ascending=False,method='first')
    g['pop_rank']=g['人気'].rank(ascending=True,method='first')
    g['race']=rid
    g['win']=(g['着順']==1).astype(int)
    g['plc']=(g['着順']<=3).astype(int)
    rows.append(g)
big=pd.concat(rows,ignore_index=True)
print(f"races={big['race'].nunique()}  horses={len(big)}\n")

# ---- 1. conditional signal: within popularity bands, does model rank predict finish? ----
print("=== 市場を超える情報の検証：人気層別の model_rank→着順 相関 ===")
print("(各レース内で人気が近い馬同士でも、モデル上位がより好走するか)")
big['pop_band']=pd.cut(big['人気'],[0,1,2,3,5,8,99],labels=['1番人気','2','3','4-5','6-8','9+'])
for band,gb in big.groupby('pop_band',observed=True):
    # within-race spearman is ideal but bands thin; use pooled rank-residual approach:
    rhos=[]
    for rid,gr in gb.groupby('race'):
        if len(gr)>=3 and gr['総合スコア'].std()>0:
            rho,_=spearmanr(gr['総合スコア'],-gr['着順'])
            if not np.isnan(rho): rhos.append(rho)
    wr=gb['win'].mean(); n=len(gb)
    print(f"  人気{band:6s} n={n:4d}  勝率{wr:.1%}  (層内ρ平均 {np.mean(rhos):+.3f} / {len(rhos)}グループ)" if rhos else f"  人気{band:6s} n={n:4d} 勝率{wr:.1%}")

# cleaner test: partial correlation of model score & finish controlling for popularity
# residualize both on 人気 (pooled), then correlate
from numpy.polynomial import polynomial as P
def resid(y,x):
    x=x.values.astype(float); y=y.values.astype(float)
    b=np.polyfit(x,y,1); return y-np.polyval(b,x)
r_score=resid(big['総合スコア'],big['人気'])
r_fin=resid(big['着順'],big['人気'])
rho,p=spearmanr(r_score,-r_fin)
print(f"\n  人気を統制した後の model総合スコア vs 好走 偏相関: ρ={rho:+.3f} (p={p:.3g})")
r_clean=resid(big['clean'],big['人気'])
rho2,p2=spearmanr(r_clean,-r_fin)
print(f"  同上（死に因子を除いたcleanスコア）          : ρ={rho2:+.3f} (p={p2:.3g})")
print("  → 正で有意なら『市場が見落とす実力』を捉えている＝妙味の源泉")

# ---- 2. single-win ROI backtest ----
print("\n=== 単勝回収率バックテスト（払戻=単勝オッズ, 損益分岐=100%）===")
def roi(mask,label):
    sub=big[mask]
    if len(sub)==0: print(f"  {label}: 該当なし"); return
    bets=len(sub); wins=sub['win'].sum()
    payout=(sub['win']*sub['単勝オッズ']).sum()
    print(f"  {label:42s} 賭{bets:4d} 勝{wins:3d} 勝率{wins/bets:.1%} 回収率{payout/bets*100:5.1f}%")

roi(big['pop_rank']==1, "全レース 1番人気を単勝")
roi(big['model_rank']==1, "モデル本命(総合1位)を単勝")
roi(big['clean_rank']==1, "cleanスコア本命を単勝")
# model overlay: model likes much more than market
roi((big['model_rank']==1)&(big['人気']>=2), "モデル本命 かつ 非1番人気（妙味狙い）")
roi((big['model_rank']==1)&(big['人気']>=4), "モデル本命 かつ 4番人気以下")
roi((big['model_rank']<=3)&(big['人気']-big['model_rank']>=3), "モデルが市場より3ランク以上高評価")
roi((big['clean_rank']<=3)&(big['人気']-big['clean_rank']>=3), "同上(cleanスコア)")
roi((big['model_rank']<=3)&(big['人気']-big['model_rank']>=5), "モデルが市場より5ランク以上高評価")
