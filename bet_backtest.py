# -*- coding: utf-8 -*-
"""買い判定バックテスト（現行 bet_recon 準拠）: 全レースを現行コードで再スコア→
bet_recon.reconstruct で判定を再現し、実結果で判定別の軸単勝/複勝ROI・的中率を集計。
usage:
  python bet_backtest.py collect <rid> [...]   # /tmp/bet_rows.jsonl に追記(resumable)
  python bet_backtest.py report
"""
import sys, os, json, subprocess, tempfile
SD = os.path.dirname(os.path.abspath(__file__))
DONE = os.path.join(SD, 'input', 'done')
ROWS = '/tmp/bet_rows.jsonl'


def find(rid, pre, ext='csv'):
    p = os.path.join(DONE, f'{pre}_{rid}.{ext}')
    return p if os.path.exists(p) else None


def collect(rids):
    done = set()
    if os.path.exists(ROWS):
        for l in open(ROWS, encoding='utf-8'):
            try: done.add(json.loads(l)['rid'])
            except Exception: pass
    out = open(ROWS, 'a', encoding='utf-8')
    for rid in rids:
        if rid in done:
            print('skip', rid); continue
        kako = find(rid, '過去走'); shu = find(rid, '出馬表')
        if not (kako and shu):
            print('missing', rid); continue
        sak = find(rid, '坂路'); wood = find(rid, 'ウッド')
        sm = os.path.join(SD, f'smartrc_{rid}.json'); sm = sm if os.path.exists(sm) else None
        bj = os.path.join(SD, f'baba_{rid}.json');     bj = bj if os.path.exists(bj) else None
        with tempfile.TemporaryDirectory() as td:
            cmd = [sys.executable, os.path.join(SD, 'score_horse_v3.py'),
                   '--excel', kako, '--shutuba', shu, '--outdir', td, '--baba', '良']
            if sak: cmd += ['--sakuro', sak]
            if wood: cmd += ['--wood', wood]
            if sm: cmd += ['--smartrc', sm]
            if bj: cmd += ['--baba-json', bj]
            r = subprocess.run(cmd, capture_output=True, text=True)
            jp = os.path.join(td, 'horses_data.json')
            if r.returncode != 0 or not os.path.exists(jp):
                print('FAIL', rid); continue
            d = json.load(open(jp, encoding='utf-8'))
            hs = []
            for h in d['horses']:
                if h.get('馬番') is None:
                    continue
                hs.append({'馬名': h.get('馬名'), '馬番': h.get('馬番'),
                           'スコア': h.get('総合スコア'), '順位予想': h.get('順位予想'),
                           'SmartRC推定人気順': h.get('SmartRC推定人気順'),
                           '枠番': h.get('枠番'), 'オッズ': h.get('単勝オッズ')})
            out.write(json.dumps({'rid': rid, 'ev': hs}, ensure_ascii=False) + '\n')
            print('ok', rid, len(hs))
    out.close()


def load_result(rid):
    import result_loader as rl
    import pandas as pd
    for ext in ('.csv', '.html'):
        p = os.path.join(DONE, f'レース結果_{rid}{ext}')
        if not os.path.exists(p): continue
        try:
            df, _, _ = rl.load_result(p)
            df.columns = [str(c).strip() for c in df.columns]
            oc = '入線順位' if '入線順位' in df.columns else ('着順' if '着順' in df.columns else None)
            if oc is None or '馬番' not in df.columns: continue
            df = df[pd.to_numeric(df[oc], errors='coerce').notna()].copy()
            out = {}
            for _, r in df.iterrows():
                try: u = int(pd.to_numeric(r['馬番'], errors='coerce'))
                except Exception: continue
                fin = int(pd.to_numeric(r[oc], errors='coerce'))
                tan = pd.to_numeric(r.get('単勝オッズ'), errors='coerce')
                fuk = None
                for fc in ('複勝下限', '複勝', '複勝オッズ'):
                    if fc in df.columns:
                        fuk = pd.to_numeric(r.get(fc), errors='coerce'); break
                out[u] = (fin, float(tan) if tan == tan else None,
                          float(fuk) if (fuk is not None and fuk == fuk) else None)
            if out: return out
        except Exception:
            continue
    return None


def report():
    import bet_recon as BR
    from collections import defaultdict
    buckets = defaultdict(list)
    n_races = 0
    for l in open(ROWS, encoding='utf-8'):
        rec = json.loads(l); rid = rec['rid']; ev = rec['ev']
        if len(ev) < 5: continue
        rc = BR.reconstruct(ev)
        if not rc: continue
        res = load_result(rid)
        if not res: continue
        umA = rc['umA']
        if umA not in res: continue
        n_races += 1
        fin, tan, fuk = res[umA]
        buckets[rc['verdict']].append(dict(rid=rid, fin=fin, tan=tan, fuk=fuk))

    def roi(b):
        n = len(b)
        if not n: return None
        win = sum(1 for x in b if x['fin'] == 1)
        plc = sum(1 for x in b if x['fin'] <= 3)
        tr = sum((x['tan'] if x['fin'] == 1 and x['tan'] else 0) for x in b)
        fr = sum((x['fuk'] / 100 if x['fin'] <= 3 and x['fuk'] else 0) for x in b)
        # 単勝配当: 結果CSVの単勝オッズは倍率。100円賭け→ odds*100 円。ROI=Σ(odds*100)/(100n)
        return dict(n=n, win=win / n * 100, plc=plc / n * 100,
                    tanROI=tr / n * 100, fukROI=fr / n * 100)

    order = ['買い妙味', '中穴軸', '混戦BOX', '穴妙味', '見送り']
    lines = [f'# 買い判定バックテスト（現行ロジック / {n_races}R）\n']
    lines.append('| 判定 | R数 | 軸勝率 | 軸複勝率 | 軸単勝ROI | 軸複勝ROI |')
    lines.append('|---|--:|--:|--:|--:|--:|')
    for v in order:
        m = roi(buckets.get(v, []))
        if m:
            lines.append(f'| {v} | {m["n"]} | {m["win"]:.0f}% | {m["plc"]:.0f}% | {m["tanROI"]:.0f}% | {m["fukROI"]:.0f}% |')
        else:
            lines.append(f'| {v} | 0 | — | — | — | — |')
    buy = [x for v in ('買い妙味', '中穴軸', '混戦BOX', '穴妙味') for x in buckets.get(v, [])]
    sk = buckets.get('見送り', [])
    mb, ms = roi(buy), roi(sk)
    lines.append('\n| 集約 | R数 | 軸勝率 | 軸複勝率 | 軸単勝ROI | 軸複勝ROI |')
    lines.append('|---|--:|--:|--:|--:|--:|')
    if mb: lines.append(f'| 買い側計 | {mb["n"]} | {mb["win"]:.0f}% | {mb["plc"]:.0f}% | {mb["tanROI"]:.0f}% | {mb["fukROI"]:.0f}% |')
    if ms: lines.append(f'| 見送り | {ms["n"]} | {ms["win"]:.0f}% | {ms["plc"]:.0f}% | {ms["tanROI"]:.0f}% | {ms["fukROI"]:.0f}% |')
    lines.append('\n※軸=モデル勝率1位。単勝ROI100%超=控除率を越える妙味。複勝ROIは複勝配当が取れた分のみ。')
    rep = os.path.join(SD, 'bet_backtest_report.md')
    open(rep, 'w', encoding='utf-8').write('\n'.join(lines))
    print('\n'.join(lines)); print('\nwrote', rep)


def formation():
    """払戻(haraimodoshi_*.json)がある全レースで、判定別×券種別のフォーメーションROIを集計。"""
    import bet_recon as BR
    import result_loader as rl
    import pandas as pd
    from collections import defaultdict
    agg = defaultdict(lambda: defaultdict(lambda: [0, 0.0, 0]))  # verdict->券種->[点数,払戻,R数]
    nrace = defaultdict(int)
    for l in open(ROWS, encoding='utf-8'):
        rec0 = json.loads(l); rid = rec0['rid']; ev = rec0['ev']
        if len(ev) < 5: continue
        hp = os.path.join(SD, f'haraimodoshi_{rid}.json')
        if not os.path.exists(hp): continue
        rc = BR.reconstruct(ev)
        if not rc: continue
        # 結果df
        rdf = None
        for ext in ('.csv', '.html'):
            fp = os.path.join(DONE, f'レース結果_{rid}{ext}')
            if os.path.exists(fp):
                try:
                    rdf, _, _ = rl.load_result(fp); break
                except Exception: pass
        if rdf is None: continue
        rdf.columns = [str(c).strip() for c in rdf.columns]
        if '入線順位' not in rdf.columns or '馬番' not in rdf.columns: continue
        payouts = json.load(open(hp, encoding='utf-8'))
        try:
            er = BR.eval_race(rc, rdf, payouts)
        except Exception:
            continue
        if not er: continue
        nrace[rc['verdict']] += 1
        for bt, (pts, ret, _hits) in er['bets'].items():
            a = agg[rc['verdict']][bt]
            a[0] += pts; a[1] += ret; a[2] += 1

    order = ['買い妙味', '中穴軸', '混戦BOX', '穴妙味', '見送り']
    lines = ['# 買い判定 フォーメーション別ROI（払戻あり {}R）\n'.format(sum(nrace.values()))]
    lines.append('| 判定 | R数 | 券種 | 総点数 | 総払戻 | ROI |')
    lines.append('|---|--:|---|--:|--:|--:|')
    for v in order:
        if v not in agg: continue
        first = True
        for bt, (pts, ret, rr) in sorted(agg[v].items(), key=lambda kv: -kv[1][1] / max(1, kv[1][0])):
            if pts == 0: continue
            roi = ret / (pts * 100) * 100
            lines.append(f'| {v if first else ""} | {nrace[v] if first else ""} | {bt} | {pts} | {int(ret)} | {roi:.0f}% |')
            first = False
    lines.append('\n※ROI=総払戻÷(総点数×100)。各判定が推奨する券種の実フォーメーションを1点ずつ購入した場合。100%超=控除率を越える妙味。')
    rep = os.path.join(SD, 'bet_formation_report.md')
    open(rep, 'w', encoding='utf-8').write('\n'.join(lines))
    print('\n'.join(lines)); print('\nwrote', rep)


if __name__ == '__main__':
    if len(sys.argv) < 2: print(__doc__); sys.exit(1)
    if sys.argv[1] == 'collect': collect(sys.argv[2:])
    elif sys.argv[1] == 'report': report()
    elif sys.argv[1] == 'formation': formation()
