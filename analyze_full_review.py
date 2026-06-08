# -*- coding: utf-8 -*-
"""包括的な精度・期待値判別の振り返り分析（取消馬修正版）"""
import re, json, glob, pathlib, math

BASE = pathlib.Path('/sessions/adoring-focused-galileo/mnt/keiba-dashboard')

def parse_review(fp):
    txt = pathlib.Path(fp).read_text(encoding='utf-8', errors='ignore')
    m = re.search(r'const DATA = (\[.*?\]);', txt)
    if not m: return None
    try: return json.loads(m.group(1))
    except: return None

json_files = sorted(glob.glob(str(BASE / 'horses_data_*.json')))
records = []
for jp in json_files:
    jname = pathlib.Path(jp).stem
    parts = jname.replace('horses_data_','').split('_')
    if len(parts) < 2: continue
    date_str, venue_r = parts[0], parts[1]
    vc = re.match(r'[a-z]+', venue_r); rn = re.search(r'\d+', venue_r)
    if not vc or not rn: continue
    vc2, rn2 = vc.group().upper(), rn.group()
    matches = []
    for alt in [vc2, {'KT':'KY','KY':'KT'}.get(vc2,vc2)]:
        matches += glob.glob(str(BASE/f'{date_str}_{alt}{rn2}R_*_review.html'))
    if not matches: continue
    rev = parse_review(matches[0])
    if not rev: continue
    with open(jp) as f: jdata = json.load(f)
    horses = jdata.get('horses',[])
    if not horses: continue
    act_map = {h['馬名']: h.get('入線順位',99) for h in rev}
    records.append({'horses':horses,'act_map':act_map,'rev':rev,'race':jname})

print(f'分析対象: {len(records)}レース / {sum(len(r["horses"]) for r in records)}頭')

# 取消馬の件数を報告
scratched_total = 0
for r in records:
    rev_names = {h['馬名'] for h in r['rev']}
    for h in r['horses']:
        if isinstance(h, dict) and h.get('馬名') not in rev_names:
            scratched_total += 1
print(f'取消馬（JSON在・review不在）: {scratched_total}頭 ※分析から除外\n')

# ── 2. 偏差値の精度（修正版：取消馬除外）──────────────────────
print('='*65)
print('【スコア1位の偏差値 vs 実際着順（取消馬除外）】')
dev_data=[]
for r in records:
    valid=[h for h in r['horses'] if not h.get('過去走なし')]
    if not valid: continue
    pred1=min(valid, key=lambda h: h.get('順位予想',99))
    scores=[h.get('総合スコア',0) for h in valid]
    mu=sum(scores)/len(scores)
    sig=(sum((s-mu)**2 for s in scores)/len(scores))**0.5 or 1
    dev=round((pred1.get('総合スコア',0)-mu)/sig*10+50)
    act=r['act_map'].get(pred1['馬名'], 99)
    if act == 99:
        print(f'  [取消除外] {r["race"]}  {pred1["馬名"]}  偏差値={dev}')
        continue
    dev_data.append({'dev':dev,'act':act,'name':pred1['馬名'],'race':r['race']})

print()
for lo,hi,label in [(70,99,'偏差70以上'),(65,69,'偏差65-69'),(60,64,'偏差60-64'),(0,59,'偏差59以下')]:
    sub=[x for x in dev_data if lo<=x['dev']<=hi]
    if not sub: continue
    n=len(sub); w=sum(1 for x in sub if x['act']==1)
    t3=sum(1 for x in sub if x['act']<=3)
    avg=sum(x['act'] for x in sub)/n
    print(f'  {label}: n={n:2d}R  勝率={w/n*100:.0f}%  複勝率={t3/n*100:.0f}%  平均着順={avg:.1f}')
    if lo==60 and hi==64:
        for x in sorted(sub, key=lambda x: x['act']):
            print(f'    {x["race"]:<42}  {x["name"]:<15}  偏差値={x["dev"]}  →{x["act"]}着')

print()

# ── 乖離度の有効性検証 ────────────────────────────────────────
print('='*65)
print('【乖離度別 注目馬の実際成績（延べ頭数、取消馬除外）】')
kairido_data=[]
for r in records:
    for h in r['horses']:
        src=h.get('SmartRC推定人気順')
        if src is None: continue
        try: k=int(src)-h.get('順位予想',99)
        except: continue
        act=r['act_map'].get(h['馬名'],99)
        if act == 99: continue   # 取消馬除外
        odds=h.get('単勝オッズ',0)
        kairido_data.append({'k':k,'act':act,'odds':odds,'name':h['馬名']})

for lo,hi,label in [(6,99,'+6以上（大穴）'),(4,5,'+4〜+5'),(2,3,'+2〜+3'),(0,1,'0〜+1（一致）'),(-99,-1,'マイナス（割高）')]:
    sub=[x for x in kairido_data if lo<=x['k']<=hi]
    if not sub: continue
    n=len(sub); w=sum(1 for x in sub if x['act']==1)
    t3=sum(1 for x in sub if x['act']<=3)
    avg_odds=sum(x['odds'] for x in sub if x['odds'])/max(1,sum(1 for x in sub if x['odds']))
    print(f'  {label:16s}: n={n:3d}頭  勝率={w/n*100:.1f}%  複勝率={t3/n*100:.1f}%  平均オッズ={avg_odds:.1f}倍')

print()

# ── 馬券収支シミュレーション ─────────────────────────────────
print('='*65)
print('【馬券収支シミュレーション（全25レース・各100円想定）】')

def softmax_prob(horses, temp=20):
    scores = [h.get('総合スコア',0) for h in horses if not h.get('過去走なし')]
    if not scores: return {}
    maxs = max(scores)
    exps = [math.exp((s-maxs)/temp) for s in scores]
    sumexp = sum(exps)
    valid = [h for h in horses if not h.get('過去走なし')]
    return {h['馬名']: e/sumexp for h,e in zip(valid,exps)}

def sim(records, pick_fn):
    invest=0; ret=0; hits=0
    for r in records:
        valid=sorted([h for h in r['horses'] if not h.get('過去走なし')],
                     key=lambda h:h.get('順位予想',99))
        if not valid: continue
        picks=pick_fn(valid, r['act_map'])
        for h,t in picks:
            if h is None: continue
            act=r['act_map'].get(h['馬名'],99)
            if act == 99: continue   # 取消馬除外
            invest+=100
            if t=='tansho' and act==1:
                odds=h.get('単勝オッズ',0)
                ret+=int(odds*100); hits+=1
            elif t=='fukusho' and act<=3:
                odds=h.get('複勝下限',0) or 0
                ret+=int(odds*100); hits+=1
    return invest,ret,hits

i,r2,h2=sim(records,lambda v,a:[(v[0],'tansho')])
print(f'  スコア1位 単勝  : 投資{i}円 回収{r2}円 回収率={r2/i*100:.1f}%  的中{h2}/{len(records)}R')

i,r2,h2=sim(records,lambda v,a:[(v[0],'fukusho')])
print(f'  スコア1位 複勝  : 投資{i}円 回収{r2}円 回収率={r2/i*100:.1f}%  的中{h2}/{len(records)}R')

probs_all={}
for r in records:
    probs_all[r['race']]=softmax_prob(r['horses'])

invest=0; ret=0; hits=0; races_bet=0
for r in records:
    valid=sorted([h for h in r['horses'] if not h.get('過去走なし')],key=lambda h:h.get('順位予想',99))
    rp=probs_all.get(r['race'],{})
    picks=[(h,'tansho') for h in valid if rp.get(h['馬名'],0)*h.get('単勝オッズ',0)-1>0.05]
    if picks: races_bet+=1
    for h,t in picks:
        act=r['act_map'].get(h['馬名'],99)
        if act == 99: continue
        invest+=100
        if act==1:
            odds=h.get('単勝オッズ',0)
            ret+=int(odds*100); hits+=1
print(f'  EV◎買い 単勝   : 投資{invest}円 回収{ret}円 回収率={ret/invest*100 if invest else 0:.1f}%  的中{hits}頭({races_bet}R参加)')

def classify_rec(horses):
    rc_top3=sorted([h for h in horses if not h.get('過去走なし')],key=lambda h:h.get('順位予想',99))[:3]
    ks=[]
    for h in rc_top3:
        src=h.get('SmartRC推定人気順')
        if src:
            try: ks.append(int(src)-h.get('順位予想',99))
            except: pass
    mk=max(ks,default=0)
    n=len(horses)
    fav_rank=next((h.get('順位予想',99) for h in horses if h.get('人気')==1),99)
    thr=n//2 if n<=12 else 7
    if mk>=4: return '妙味有'
    elif mk>=2: return '妙味有' if fav_rank>thr else '要検討'
    return '妙味薄'

invest=0; ret=0; hits=0; races_bet=0
for r in records:
    rec=classify_rec(r['horses'])
    if rec!='妙味有': continue
    valid=sorted([h for h in r['horses'] if not h.get('過去走なし')],key=lambda h:h.get('順位予想',99))
    if not valid: continue
    h=valid[0]; act=r['act_map'].get(h['馬名'],99)
    if act == 99: continue  # 取消馬除外
    races_bet+=1; invest+=100
    if act==1:
        odds=h.get('単勝オッズ',0)
        ret+=int(odds*100); hits+=1
print(f'  妙味有のみ 単勝 : 投資{invest}円 回収{ret}円 回収率={ret/invest*100 if invest else 0:.1f}%  的中{hits}/{races_bet}R')

invest=0; ret=0; hits=0; races_bet=0
for r in records:
    rec=classify_rec(r['horses'])
    if rec!='妙味有': continue
    valid=sorted([h for h in r['horses'] if not h.get('過去走なし')],key=lambda h:h.get('順位予想',99))
    if not valid: continue
    h=valid[0]; act=r['act_map'].get(h['馬名'],99)
    if act == 99: continue  # 取消馬除外
    races_bet+=1; invest+=100
    if act<=3:
        odds=h.get('複勝下限',0) or 0
        ret+=int(odds*100); hits+=1
print(f'  妙味有のみ 複勝 : 投資{invest}円 回収{ret}円 回収率={ret/invest*100 if invest else 0:.1f}%  的中{hits}/{races_bet}R')
