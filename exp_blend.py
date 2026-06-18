# -*- coding: utf-8 -*-
"""experiment: does blending market odds + dropping dead factors beat current model?"""
import pathlib
import pandas as pd, numpy as np
from scipy.stats import spearmanr

SD=pathlib.Path(__file__).parent
DONE=SD/'input'/'done'
DEAD=['SmartRC評価pts','昇級pts','斤量pts','枠順pts','臨戦pts']  # rho≈0 candidates

def load_res(rid):
    p=DONE/f'レース結果_{rid}.csv'
    if not p.exists(): return None
    try:
        df=pd.read_csv(p,encoding='cp932',header=2,on_bad_lines='skip')
        df.columns=[str(c).strip() for c in df.columns]
        df=df[pd.to_numeric(df['入線順位'],errors='coerce').notna()].copy()
        df['着順']=pd.to_numeric(df['入線順位'],errors='coerce').astype(int)
        df['人気']=pd.to_numeric(df['人気'],errors='coerce')
        df['馬名']=df['馬名'].astype(str).str.strip()
        return df[['馬名','着順','人気']].dropna()
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

def evaluate(score_fn, name):
    """score_fn(g)->Series higher=better. returns win,place,rho,mean_finish_of_top"""
    win=place=0; rhos=[]; n=0; tops=[]
    for rid in targets:
        res=load_res(rid); scr=load_scr(rid)
        if res is None or scr is None: continue
        g=scr.merge(res,on='馬名',how='inner')
        if len(g)<5: continue
        s=score_fn(g)
        if s is None or s.std()==0: continue
        n+=1
        g=g.assign(_s=s)
        top=g.loc[g['_s'].idxmax()]
        tops.append(int(top['着順']))
        w=set(g[g['着順']==1]['馬名']); t3=set(g[g['着順']<=3]['馬名'])
        if top['馬名'] in w: win+=1
        if top['馬名'] in t3: place+=1
        rho,_=spearmanr(g['_s'],-g['着順'])
        if not np.isnan(rho): rhos.append(rho)
    print(f"  {name:32s} 単勝{win/n:.0%} 複勝{place/n:.0%} ρ={np.mean(rhos):+.3f} 推し平均着{np.mean(tops):.2f}  (n={n})")
    return win/n,place/n,np.mean(rhos)

def z(x):
    x=pd.to_numeric(x,errors='coerce');
    return (x-x.mean())/x.std() if x.std()>0 else x*0

print("=== ランキング手法の比較 (全123R) ===\n")
evaluate(lambda g: g['総合スコア'], "現行 総合スコア")
evaluate(lambda g: -g['人気'], "人気のみ (市場)")
# drop dead factors
def model_minus_dead(g):
    s=g['総合スコア'].copy()
    for c in DEAD:
        if c in g.columns: s=s-g[c].fillna(0)
    return s
evaluate(model_minus_dead, "総合-死に因子(SmartRC他)")
# blends of model z + popularity z
for w in [0.3,0.5,0.7]:
    evaluate(lambda g,w=w: w*z(g['総合スコア'])+(1-w)*z(-g['人気']), f"ブレンド model{w:.0%}+人気{1-w:.0%}")
# dead-dropped model blended with popularity
for w in [0.5,0.6]:
    evaluate(lambda g,w=w: w*z(model_minus_dead(g))+(1-w)*z(-g['人気']), f"(モデル-死因子){w:.0%}+人気{1-w:.0%}")
