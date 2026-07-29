# -*- coding: utf-8 -*-
"""的中精度検証・妙味検証の集計。**既存データを読むだけ。再採点はしない。**

使うデータ（すべて既存）:
  factor_rows_p4.jsonl … 現行スコアラー(P3＋P4)で採点し直した5年データ
  factor_rows_p3.jsonl … P4を入れる前の5年データ（16,048R）
  factor_rows.jsonl    … P3を入れる前の5年データ
  racemeta_cache.jsonl … レースの会場/クラス/馬場/芝ダ/距離帯（絞り込み用）
  payouts_cache.jsonl  … 確定配当（複勝ROIの算出に使う）
  roi_rows.jsonl       … 券種フォーメーションの買い判定と払戻（2026/04〜06）

大事な前提（画面にも出すこと）:
  1. 5年データは**採点ロジックの世代ごとにファイルが分かれている**。本番の採点は
     P3＋P4 なので、それと同じ世代のファイル（factor_rows_p4.jsonl）を選んで初めて
     「現行モデルの成績」になる。どの世代を見ているかを必ず画面に出す。
  2. ここでの「軸」は **総合スコア1位**（台帳と同じ定義）。実際の買い目軸は
     勝率cap後1位で別物。券種フォーメーションの検証（roi_rows）はそちらの定義。
  3. 新馬・未勝利は精度検証外（CLAUDE.md）。既定で除外する。
"""
from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass

from .. import config

# 5年集計データは採点ロジックの世代ごとにファイルが分かれている。
# 新しい世代（現行スコアラー）のファイルがあればそちらを既定にする。
DATA_SOURCES = [
    {
        'key': 'p4',
        'file': 'factor_rows_p4.jsonl',
        'label': 'P3＋P4（現行スコアラー）',
        'desc': '本番と同じ採点ロジック（相対上がり＋成績重み付きコース適性）で採点し直したデータ。',
    },
    {
        'key': 'p3',
        'file': 'factor_rows_p3.jsonl',
        'label': 'P3のみ',
        'desc': 'P4（成績重み付きコース適性）を入れる前のデータ。コース適性ptsが現行と異なる。',
    },
    {
        'key': 'base',
        'file': 'factor_rows.jsonl',
        'label': 'ベースライン（P3前）',
        'desc': '相対上がり導入前のデータ。上がりptsとコース特徴ptsが現行と異なる。',
    },
]

RACEMETA = config.ROOT_DIR / 'racemeta_cache.jsonl'
PAYOUTS = config.ROOT_DIR / 'payouts_cache.jsonl'
ROI_ROWS = config.ROOT_DIR / 'roi_rows.jsonl'

EXCLUDE_CLASSES = ('新馬', '未勝利')

# 台帳と同じ16因子（表示順も台帳に合わせる）
FACTORS = [
    '最高出力pts', 'クラスpts', '時計pts', 'コース特徴pts', 'トラックバイアスpts',
    '斤量pts', '距離pts', 'コース適性pts', '臨戦pts', '騎手pts',
    '継続pts', '着差pts', '昇級pts', 'クラス適応pts', '上がりpts', '馬場適性pts',
]

_lock = threading.Lock()


@dataclass
class Dataset:
    races: dict          # rid -> [row, ...]
    meta: dict           # rid -> meta
    payouts: dict        # rid -> payouts
    source: str          # ファイル名
    source_key: str      # p4 / p3 / base
    source_label: str


_cache: dict = {}        # source_key -> Dataset


def _load_jsonl(path):
    if not path.exists():
        return
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def available_sources() -> list:
    """使えるデータ世代の一覧（新しい順）。"""
    out = []
    for s in DATA_SOURCES:
        p = config.ROOT_DIR / s['file']
        out.append({**s, 'exists': p.exists(),
                    'size_mb': round(p.stat().st_size / 1048576, 1) if p.exists() else None})
    return out


def default_source() -> str:
    for s in DATA_SOURCES:
        if (config.ROOT_DIR / s['file']).exists():
            return s['key']
    return DATA_SOURCES[-1]['key']


def _source_def(key: str | None) -> dict:
    key = key or default_source()
    for s in DATA_SOURCES:
        if s['key'] == key:
            return s
    raise ValueError(f'知らないデータ世代です: {key}')


def dataset(source: str | None = None) -> Dataset:
    """一度だけ読み込んでプロセス内に置く（122MB・約2秒）。世代ごとに保持する。"""
    s = _source_def(source)
    with _lock:
        if s['key'] in _cache:
            return _cache[s['key']]
        path = config.ROOT_DIR / s['file']
        if not path.exists():
            raise FileNotFoundError(
                f'{s["label"]} のデータ（{s["file"]}）がまだありません。'
                '管理タブの「5年分を採点し直す」で作成できます。')
        races: dict = {}
        for d in _load_jsonl(path):
            races.setdefault(d['rid'], []).append(d)
        meta = {d['rid']: d for d in _load_jsonl(RACEMETA)}
        payouts = {d['rid']: d.get('payouts') or {} for d in _load_jsonl(PAYOUTS)}
        _cache[s['key']] = Dataset(races=races, meta=meta, payouts=payouts,
                                   source=s['file'], source_key=s['key'],
                                   source_label=s['label'])
        return _cache[s['key']]


def reset_cache() -> None:
    with _lock:
        _cache.clear()
        _result_cache.clear()


# 同じ絞り込みでの再計算を避ける（因子診断は5年フルで約4秒かかる）
_result_cache: dict = {}


def _memo(kind: str, f: dict, fn):
    key = (kind, json.dumps(f, sort_keys=True, ensure_ascii=False))
    if key in _result_cache:
        return _result_cache[key]
    value = fn()
    if len(_result_cache) > 40:
        _result_cache.clear()
    _result_cache[key] = value
    return value


# ── 絞り込み ─────────────────────────────────────────────────────
def data_range(source: str | None = None) -> dict:
    ds = dataset(source)
    dates = sorted(rid[:8] for rid in ds.races)
    roi_dates = sorted({r['rid'][:8] for r in _load_jsonl(ROI_ROWS)})
    return {
        'source': ds.source,
        'source_key': ds.source_key,
        'source_label': ds.source_label,
        'sources': available_sources(),
        'accuracy': {'from': dates[0], 'to': dates[-1], 'races': len(ds.races)} if dates else None,
        'value_formation': ({'from': roi_dates[0], 'to': roi_dates[-1],
                             'races': len(roi_dates)} if roi_dates else None),
        'note': _source_note(ds.source_key),
    }


def _match(rid: str, meta: dict, f: dict) -> bool:
    date = rid[:8]
    if f.get('date_from') and date < f['date_from']:
        return False
    if f.get('date_to') and date > f['date_to']:
        return False
    m = meta.get(rid) or {}
    # 障害戦は採点の対象外。racemeta では芝ダも馬場も '?' になる。
    # 混ざっていると集計に「?」の行が出るうえ、当たらない分だけ成績も下がる。
    if m.get('surface') == '?':
        return False
    if f.get('venues') and m.get('jyo_name') not in f['venues']:
        return False
    if f.get('classes') and m.get('cls') not in f['classes']:
        return False
    if f.get('babas') and m.get('baba') not in f['babas']:
        return False
    if f.get('surfaces') and m.get('surface') not in f['surfaces']:
        return False
    if not f.get('include_maiden') and m.get('cls') in EXCLUDE_CLASSES:
        return False
    return True


def _target_rids(f: dict) -> list:
    ds = dataset(f.get('source'))
    return [rid for rid in ds.races if _match(rid, ds.meta, f)]


def _source_note(key: str) -> str:
    if key == 'p4':
        return ('本番の採点ロジック（P3＋P4）で採点し直したデータです。'
                '現行モデルの成績としてそのまま読めます。')
    if key == 'p3':
        return ('このデータは P3 までで採点されており、P4（成績重み付きコース適性）は'
                '含まれていません。本番の採点は P3＋P4 なので、コース適性pts と'
                'それを含む総合スコアが現行と異なります。'
                '管理タブの「5年分を採点し直す」で現行ロジックのデータを作れます。')
    return ('このデータは P3（相対上がり）導入前のものです。'
            '上がりpts・コース特徴pts・コース適性pts が現行と異なります。')


def _finished(rows: list) -> list:
    return [r for r in rows
            if isinstance(r.get('着順'), int) and r['着順'] > 0]


# ── 順位相関（scipy を使わずに計算する） ─────────────────────────
def _spearman(a: list, b: list) -> float:
    """スピアマン相関＝順位に直したピアソン相関。同順位は平均順位で扱う。"""
    n = len(a)
    if n < 4:
        return float('nan')

    def ranks(xs):
        order = sorted(range(n), key=lambda i: xs[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    ra, rb = ranks(a), ranks(b)
    ma = sum(ra) / n
    mb = sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    da = math.sqrt(sum((x - ma) ** 2 for x in ra))
    db = math.sqrt(sum((y - mb) ** 2 for y in rb))
    if da == 0 or db == 0:
        return float('nan')
    return num / (da * db)


# ── A. 的中精度 ──────────────────────────────────────────────────
def accuracy(f: dict) -> dict:
    return _memo('accuracy', f, lambda: _accuracy(f))


def _accuracy(f: dict) -> dict:
    ds = dataset(f.get('source'))
    rids = _target_rids(f)

    n = 0
    axis_win = axis_place = 0
    pop1_win = pop1_place = 0
    pop1_races = 0
    top3_sum = 0
    rho_sum = 0.0
    rho_n = 0
    horses = 0
    by_year: dict = {}
    by_key: dict = {k: {} for k in ('jyo_name', 'cls', 'baba', 'surface')}

    for rid in rids:
        rows = _finished(ds.races[rid])
        if len(rows) < 5:
            continue
        n += 1
        horses += len(rows)
        srt = sorted(rows, key=lambda r: -(r.get('総合スコア') or -9e9))
        axis = srt[0]
        w = int(axis['着順'] == 1)
        p = int(axis['着順'] <= 3)
        axis_win += w
        axis_place += p

        pops = [r for r in rows if r.get('人気') == 1]
        if pops:
            pop1_races += 1
            pop1_win += int(pops[0]['着順'] == 1)
            pop1_place += int(pops[0]['着順'] <= 3)

        pred3 = {r['umaban'] for r in srt[:3]}
        act3 = {r['umaban'] for r in rows if r['着順'] <= 3}
        top3_sum += len(pred3 & act3)

        rho = _spearman([-(r.get('総合スコア') or 0) for r in rows],
                        [r['着順'] for r in rows])
        if not math.isnan(rho):
            rho_sum += rho
            rho_n += 1

        m = ds.meta.get(rid) or {}
        year = rid[:4]
        for bucket, key in ((by_year, year), *[(by_key[k], m.get(k)) for k in by_key]):
            slot = bucket.setdefault(key, {'races': 0, 'win': 0, 'place': 0,
                                           'pop1_place': 0, 'pop1_races': 0})
            slot['races'] += 1
            slot['win'] += w
            slot['place'] += p
            if pops:
                slot['pop1_races'] += 1
                slot['pop1_place'] += int(pops[0]['着順'] <= 3)

    def rate(a, b):
        return (a / b) if b else None

    def pack(bucket):
        out = []
        for k, v in bucket.items():
            if k is None:
                continue
            out.append({
                'key': k, 'races': v['races'],
                'axis_win_rate': rate(v['win'], v['races']),
                'axis_place_rate': rate(v['place'], v['races']),
                'pop1_place_rate': rate(v['pop1_place'], v['pop1_races']),
            })
        out.sort(key=lambda x: -x['races'])
        return out

    return {
        'races': n,
        'horses': horses,
        'avg_field': rate(horses, n),
        'axis_win_rate': rate(axis_win, n),
        'axis_place_rate': rate(axis_place, n),
        'top3_overlap': rate(top3_sum, n),
        'spearman': rate(rho_sum, rho_n),
        'pop1_win_rate': rate(pop1_win, pop1_races),
        'pop1_place_rate': rate(pop1_place, pop1_races),
        'by_year': sorted(pack(by_year), key=lambda x: x['key']),
        'by_venue': pack(by_key['jyo_name']),
        'by_class': pack(by_key['cls']),
        'by_baba': pack(by_key['baba']),
        'by_surface': pack(by_key['surface']),
        'axis_definition': '総合スコア1位（台帳と同じ定義。実際の買い目軸＝勝率cap後1位とは別）',
    }


# ── B. 因子別の診断（台帳の表の自動再現） ────────────────────────
def factor_diagnostics(f: dict) -> dict:
    return _memo('factors', f, lambda: _factor_diagnostics(f))


def _factor_diagnostics(f: dict) -> dict:
    ds = dataset(f.get('source'))
    rids = _target_rids(f)

    stat = {name: {'races': 0, 'varied': 0, 'calib': [[0, 0], [0, 0], [0, 0], [0, 0]],
                   'rho_sum': 0.0, 'rho_n': 0} for name in FACTORS}
    total = 0

    for rid in rids:
        rows = _finished(ds.races[rid])
        if len(rows) < 5:
            continue
        total += 1
        place = [int(r['着順'] <= 3) for r in rows]
        fin = [r['着順'] for r in rows]
        for name in FACTORS:
            vals = [r.get(name) for r in rows]
            if any(v is None for v in vals):
                continue
            s = stat[name]
            s['races'] += 1
            if max(vals) != min(vals):
                s['varied'] += 1
            order = sorted(range(len(rows)), key=lambda i: -vals[i])
            for rank, idx in enumerate(order):
                bucket = rank if rank < 3 else 3
                s['calib'][bucket][0] += place[idx]
                s['calib'][bucket][1] += 1
            rho = _spearman([-v for v in vals], fin)
            if not math.isnan(rho):
                s['rho_sum'] += rho
                s['rho_n'] += 1

    def rate(a, b):
        return (a / b) if b else None

    out = []
    for name in FACTORS:
        s = stat[name]
        if not s['races']:
            continue
        calib = [rate(a, b) for a, b in s['calib']]
        out.append({
            'factor': name,
            'races': s['races'],
            'top1_place_rate': calib[0],
            'calibration': {'top1': calib[0], 'top2': calib[1],
                            'top3': calib[2], 'rest': calib[3]},
            'spearman': rate(s['rho_sum'], s['rho_n']),
            'variation_rate': rate(s['varied'], s['races']),
        })
    out.sort(key=lambda x: -(x['top1_place_rate'] or 0))
    return {'races': total, 'factors': out}


# ── C. 妙味（軸の単勝・複勝。5年分を再計算なしで出せる） ─────────
def value_axis(f: dict) -> dict:
    """軸（総合スコア1位）を1点買いしたときの回収率。

    **母数は「軸が出走した全レース」に固定する。**
    当たったレースだけを母数にすると、複勝回収率が143%といった
    ありえない数字になる（結果を見てから買う計算になるため）。
    """
    ds = dataset(f.get('source'))
    rids = _target_rids(f)

    n = 0
    win_hit = place_hit = 0
    tan_ret = 0.0
    fuk_ret = 0.0
    fuk_missing = 0

    for rid in rids:
        rows = _finished(ds.races[rid])
        if len(rows) < 5:
            continue
        axis = max(rows, key=lambda r: r.get('総合スコア') or -9e9)
        odds = axis.get('単勝')
        if not odds or odds <= 0:
            continue
        n += 1
        if axis['着順'] == 1:
            win_hit += 1
            tan_ret += float(odds) * 100
        if axis['着順'] <= 3:
            place_hit += 1
            pay = _fukusho_payout(ds.payouts.get(rid) or {}, axis['umaban'])
            if pay is None:
                fuk_missing += 1
            else:
                fuk_ret += pay

    inv = n * 100
    return {
        'races': n,
        'stake_per_race': 100,
        'investment': inv,
        'win': {
            'hit': win_hit,
            'hit_rate': (win_hit / n) if n else None,
            'payout': round(tan_ret),
            'roi': (tan_ret / inv) if inv else None,
        },
        'place': {
            'hit': place_hit,
            'hit_rate': (place_hit / n) if n else None,
            'payout': round(fuk_ret),
            'roi': (fuk_ret / inv) if inv else None,
            'missing_payout_races': fuk_missing,
        },
        'axis_definition': '総合スコア1位',
        'note': ('回収率は「軸が出走した全レースを買った場合」です。'
                 '的中したレースだけを母数にすると実態とかけ離れた数字になります。'),
    }


def _fukusho_payout(payouts: dict, umaban) -> float | None:
    for key, amount in (payouts.get('fukusho') or []):
        try:
            if int(str(key).strip()) == int(umaban):
                return float(amount)
        except (TypeError, ValueError):
            continue
    return None


# ── D. 妙味（券種フォーメーション。roi_rows ベース） ─────────────
def value_formation(f: dict) -> dict:
    """券種ごとの的中率・回収率。買い判定（購入推奨/非推奨）別にも出す。"""
    rows = [r for r in _load_jsonl(ROI_ROWS)]
    date_from, date_to = f.get('date_from'), f.get('date_to')
    rows = [r for r in rows
            if (not date_from or r['rid'][:8] >= date_from)
            and (not date_to or r['rid'][:8] <= date_to)]

    def agg(subset):
        per: dict = {}
        for r in subset:
            for bt, v in (r.get('bets') or {}).items():
                if not isinstance(v, list) or len(v) != 2:
                    continue
                pts, ret = v
                a = per.setdefault(bt, {'races': 0, 'points': 0, 'payout': 0, 'hit': 0})
                a['races'] += 1
                a['points'] += pts or 0
                a['payout'] += ret or 0
                a['hit'] += 1 if (ret or 0) > 0 else 0
        out = []
        for bt, a in per.items():
            inv = a['points'] * 100
            out.append({
                'bet_type': bt, 'races': a['races'], 'points': a['points'],
                'hit_races': a['hit'],
                'hit_rate': (a['hit'] / a['races']) if a['races'] else None,
                'investment': inv, 'payout': a['payout'],
                'roi': (a['payout'] / inv) if inv else None,
            })
        out.sort(key=lambda x: -(x['roi'] or 0))

        ran = [r for r in subset if isinstance(r.get('fin'), int) and r['fin'] > 0]
        axis = None
        if ran:
            inv = len(ran) * 100
            tan = sum(float(r['tan']) * 100 for r in ran
                      if r['fin'] == 1 and r.get('tan'))
            fuk = sum(float(r['fuk']) * 100 for r in ran
                      if r['fin'] <= 3 and r.get('fuk'))
            axis = {
                'races': len(ran), 'investment': inv,
                'win_rate': sum(1 for r in ran if r['fin'] == 1) / len(ran),
                'place_rate': sum(1 for r in ran if r['fin'] <= 3) / len(ran),
                'win_roi': tan / inv, 'place_roi': fuk / inv,
            }
        return {'races': len(subset), 'bet_types': out, 'axis': axis}

    verdicts = sorted({r.get('verdict') for r in rows if r.get('verdict')})
    return {
        'total': agg(rows),
        'by_verdict': [{'verdict': v, **agg([r for r in rows if r.get('verdict') == v])}
                       for v in verdicts],
        'axis_definition': '勝率cap後1位（実際の買い目軸）',
        'note': ('複勝配当は3着以内のときだけ記録されているため、母数は'
                 '「軸が出走した全レース」に固定しています。'),
    }
