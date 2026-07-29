# -*- coding: utf-8 -*-
"""総点検ハーネス: 実レースを現行コードで再スコアし、因子別の実効分布を集計する。
usage:
  python audit_factors.py collect <race_id> [<race_id> ...]   # /tmp/audit_rows.jsonl に追記(resumable)
  python audit_factors.py report                              # 集計して audit_factors_report.md 出力
"""
import sys, os, json, subprocess, tempfile, glob, math
SD = os.path.dirname(os.path.abspath(__file__))
DONE = os.path.join(SD, 'input', 'done')
ROWS = '/tmp/audit_rows.jsonl'

# 因子 → (公称clip下限, 上限)。clip到達率/幅ズレ判定に使用
FACTOR_CLIP = {
    '最高出力pts': (0, 30), 'クラスpts': (0, 25), '時計pts': (0, 25),
    'コース特徴pts': (-5, 5), '斤量pts': (-1, 0), '距離pts': (-2, 2),
    'コース適性pts': (-10, 10), '臨戦pts': (-4, 1), '騎手pts': (-2, 2),
    '馬体重pts': (-1, 0), '継続pts': (0, 1), '着差pts': (-2, 3),
    '枠順pts': (-2, 2), '昇級pts': (-3, 0), 'クラス適応pts': (-3, 3),
    '上がりpts': (-3, 3), '馬場適性pts': (-2, 3), 'SmartRC評価pts': (-4.5, 4.5),
    '人気補正pts': (0, 3),
}
FACTORS = list(FACTOR_CLIP)


def find(rid, prefix, ext='csv'):
    p = os.path.join(DONE, f'{prefix}_{rid}.{ext}')
    return p if os.path.exists(p) else None


def collect(rids):
    import score_horse_v3  # noqa (ensure importable / same env)
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
                print('FAIL', rid, (r.stderr or '')[-200:]); continue
            d = json.load(open(jp, encoding='utf-8'))
            for h in d['horses']:
                row = {'rid': rid, '馬名': h.get('馬名'), '過去走なし': bool(h.get('過去走なし')),
                       '総合スコア': h.get('総合スコア')}
                for f in FACTORS:
                    row[f] = h.get(f)
                out.write(json.dumps(row, ensure_ascii=False) + '\n')
            print('ok', rid, len(d['horses']), 'horses')
    out.close()


def _rank(vals):
    # 大きいほど上位。降順順位(1..n)
    order = sorted(range(len(vals)), key=lambda i: -vals[i])
    rk = [0] * len(vals)
    for pos, i in enumerate(order):
        rk[i] = pos + 1
    return rk


def _kendall_tau(a, b):
    n = len(a); c = d = 0
    for i in range(n):
        for j in range(i + 1, n):
            s = (a[i] - a[j]) * (b[i] - b[j])
            if s > 0: c += 1
            elif s < 0: d += 1
    return (c - d) / (c + d) if (c + d) else 1.0


def report():
    import score_horse_v3 as S
    W = {f: S.FACTOR_WEIGHTS.get(f, 1.0) for f in FACTORS}
    races = {}
    for l in open(ROWS, encoding='utf-8'):
        r = json.loads(l); races.setdefault(r['rid'], []).append(r)

    # 因子別の全馬値
    allv = {f: [] for f in FACTORS}
    missv = {f: [] for f in FACTORS}
    for rows in races.values():
        for r in rows:
            for f in FACTORS:
                v = r.get(f)
                if v is None: continue
                allv[f].append(float(v))
                if r.get('過去走なし'): missv[f].append(float(v))

    # leave-one-out τ（線形合算ベース: Σ W*pts）
    tau_drop = {f: [] for f in FACTORS}
    for rows in races.values():
        if len(rows) < 3: continue
        base = []
        for r in rows:
            s = sum(W[f] * float(r.get(f) or 0) for f in FACTORS)
            base.append(s)
        base_rank = _rank(base)
        for f in FACTORS:
            if W[f] == 0:
                tau_drop[f].append(1.0); continue
            alt = [base[i] - W[f] * float(rows[i].get(f) or 0) for i in range(len(rows))]
            tau_drop[f].append(_kendall_tau(base_rank, _rank(alt)))

    def stats(xs):
        if not xs: return None
        n = len(xs); mn = min(xs); mx = max(xs); me = sum(xs) / n
        sd = math.sqrt(sum((x - me) ** 2 for x in xs) / n)
        return n, mn, mx, me, sd

    lines = []
    lines.append(f'# 総点検: 因子別 経験的分布レポート\n')
    lines.append(f'対象: {len(races)}レース / 延べ {sum(len(v) for v in races.values())}頭（現行コードで再スコア）\n')
    lines.append('| 因子 | 重み | nonzero% | min | max | mean | std | clip到達% | 欠損馬mean | drop後τ(平均) |')
    lines.append('|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|')
    for f in FACTORS:
        st = stats(allv[f])
        if not st:
            lines.append(f'| {f} | {W[f]} | (データ無) |||||||'); continue
        n, mn, mx, me, sd = st
        nz = sum(1 for x in allv[f] if abs(x) > 1e-9) / n * 100
        lo, hi = FACTOR_CLIP[f]
        clip = sum(1 for x in allv[f] if x <= lo + 1e-9 or x >= hi - 1e-9) / n * 100
        mm = stats(missv[f]); mmean = f'{mm[3]:+.2f}' if mm else '—'
        tau = tau_drop[f]; tavg = sum(tau) / len(tau) if tau else 1.0
        lines.append(f'| {f} | {W[f]} | {nz:.0f}% | {mn:+.2f} | {mx:+.2f} | {me:+.2f} | {sd:.2f} | {clip:.0f}% | {mmean} | {tavg:.3f} |')

    lines.append('\n**読み方**: nonzero%≈0→死因子疑い / clip到達%高→飽和 / drop後τが1.00に近い→順位にほぼ効いていない / 欠損馬mean が0から離れる→過去走なし馬への暗黙バイアス。')
    rep = os.path.join(SD, 'audit_factors_report.md')
    open(rep, 'w', encoding='utf-8').write('\n'.join(lines))
    print('wrote', rep)
    print('\n'.join(lines))


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    if sys.argv[1] == 'collect':
        collect(sys.argv[2:])
    elif sys.argv[1] == 'report':
        report()
