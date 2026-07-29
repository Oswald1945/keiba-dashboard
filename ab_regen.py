import pathlib, subprocess, sys, shutil
SD = pathlib.Path('/sessions/sleepy-eloquent-gates/mnt/keiba-dashboard')
DONE = SD/'input'/'done'
OUT = pathlib.Path('/tmp/ab'); OUT.mkdir(parents=True, exist_ok=True)
COURSE = str(SD/'course_times_full_new.json')
res={f.stem.replace('レース結果_','') for f in DONE.glob('レース結果_*.csv') if '_dup' not in f.name}
scr={f.stem.replace('scores_','') for f in SD.glob('scores_*.csv')}
def has(rid): return all((DONE/(k+'_'+rid+'.csv')).exists() for k in ['過去走','出馬表','坂路','ウッド'])
rids=sorted(r for r in (res&scr) if has(r))
LIMIT=int(sys.argv[1]) if len(sys.argv)>1 else 999
rids=[r for r in rids if not (OUT/('scores_clean_'+r+'.csv')).exists()][:LIMIT]
print('to-process:',len(rids),flush=True)
ok=fail=0
for rid in rids:
    od=OUT/rid; od.mkdir(exist_ok=True)
    cmd=[sys.executable,str(SD/'score_horse_v3.py'),
         '--excel',str(DONE/('過去走_'+rid+'.csv')),'--shutuba',str(DONE/('出馬表_'+rid+'.csv')),
         '--sakuro',str(DONE/('坂路_'+rid+'.csv')),'--wood',str(DONE/('ウッド_'+rid+'.csv')),
         '--course',COURSE,'--outdir',str(od)]
    sm=SD/('smartrc_'+rid+'.json');  bj=SD/('baba_'+rid+'.json')
    if sm.exists(): cmd+=['--smartrc',str(sm)]
    if bj.exists(): cmd+=['--baba-json',str(bj)]
    r=subprocess.run(cmd,capture_output=True,text=True)
    sc=od/'scores.csv'
    if sc.exists(): shutil.copy2(sc,OUT/('scores_clean_'+rid+'.csv')); ok+=1
    else:
        fail+=1; err=(r.stderr.strip().splitlines() or ['?'])[-1]; print('FAIL',rid,err,flush=True)
print('RUN DONE ok=',ok,'fail=',fail,flush=True)
