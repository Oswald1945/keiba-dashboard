# -*- coding: utf-8 -*-
"""
既存の回顧HTMLから新ロジック(_find_pickup_horses B案)を直接適用して
次走注目馬を再算出し、memo_horses.json に一括登録するスクリプト。

使い方:
  cd keiba-dashboard フォルダ
  python register_memo_from_reviews.py

実行後に memo_horses.json が更新される。
その後 git add memo_horses.json && git commit && git push で反映。
"""

import re, json, pathlib, datetime

BASE = pathlib.Path(__file__).parent
MEMO_JSON = BASE / 'memo_horses.json'

PLACE_MAP = {
    'CK': '中京', 'TK': '東京', 'HN': '阪神', 'NK': '新潟',
    'KT': '京都', 'KY': '京都', 'CB': '中山', 'HK': '函館',
    'SM': '札幌', 'FK': '福島', 'OI': '大井', 'KW': '川崎',
    'HS': '浦和', 'SK': '船橋',
}


def _find_pickup_horses(rows, race):
    pci = race['PCI']
    n   = race['頭数']
    front_styles = {'逃げ', '先行'}
    rear_styles  = {'差し', '追込', '後方', '中団'}

    top3 = [r for r in rows if r['入線順位'] <= 3]
    top3_front = sum(1 for r in top3 if r['決め手'] in front_styles)
    top3_rear  = sum(1 for r in top3 if r['決め手'] in rear_styles)

    is_front_race = (
        (top3_front >= 2) or
        (pci > 57 and top3_front >= 1) or
        (top3_front == 3)
    )
    is_rear_race = (
        (top3_rear >= 2) or
        (pci < 43 and top3_rear >= 1) or
        (top3_rear == 3)
    )

    agari_list = sorted([r['上り3F'] for r in rows if r.get('上り3F') is not None])
    top25_threshold = agari_list[max(0, len(agari_list) // 4 - 1)] if agari_list else 99
    top33_threshold = agari_list[max(0, len(agari_list) // 3 - 1)] if agari_list else 99
    agari_best = agari_list[0] if agari_list else 99

    candidates = []
    for r in rows:
        pos  = r['入線順位']
        if pos <= 3:
            continue
        if pos > min(9, n // 2):
            continue
        if r.get('過去走なし'):
            continue

        style   = r['決め手']
        agari   = r.get('上り3F')
        c4      = r.get('通過4')
        pred_rank = r.get('予想順位') or pos
        gap_sec = r.get('着差_sec', 99.0)
        score   = 0
        reasons = []
        has_main = False

        if is_front_race and style in rear_styles:
            score += 3
            has_main = True
            reasons.append('前有利の流れにもかかわらず、' + style + '策で' + str(pos) + '着に食い込む')
        elif is_rear_race and style in front_styles:
            score += 3
            has_main = True
            reasons.append('後方有利の流れの中、' + style + '策から' + str(pos) + '着まで粘り込む')

        if agari is not None:
            if agari == agari_best:
                score += 3
                has_main = True
                reasons.append('上り3F ' + str(agari) + '秒はこのレースの最速タイム')
            elif agari <= top25_threshold:
                score += 2
                has_main = True
                reasons.append('上り3F ' + str(agari) + '秒（上位4分の1に入る末脚）')
            elif agari <= top33_threshold:
                score += 1
                reasons.append('上り3F ' + str(agari) + '秒（上位3分の1に入る末脚）')

        if c4 is not None and pos is not None:
            gained = c4 - pos
            if gained >= max(6, int(n * 0.4)):
                score += 3
                reasons.append('4角' + str(c4) + '番手から' + str(gained) + '頭差し切り（大幅追い込み）')
            elif gained >= 4:
                score += 2
                reasons.append('4角' + str(c4) + '番手から' + str(gained) + '頭差して' + str(pos) + '着')
            elif gained >= 2:
                score += 1
                reasons.append('4角' + str(c4) + '番手から' + str(gained) + '頭上げて' + str(pos) + '着')

        if pred_rank and pos:
            outperform = int(pred_rank) - int(pos)
            if outperform >= 7:
                score += 2
                reasons.append('予想' + str(pred_rank) + '位と低評価だったが' + str(pos) + '着に大幅上回る好走')
            elif outperform >= 4:
                score += 1
                reasons.append('予想' + str(pred_rank) + '位から' + str(pos) + '着と評価以上の走り')

        if style in front_styles and agari is not None and agari <= top33_threshold:
            if score > 0:
                score += 1
                reasons.append(style + 'で前半消耗しながら上り3F ' + str(agari) + '秒の末脚を維持')

        if gap_sec <= 0.1:
            score += 3
            reasons.append('1着との差はわずか' + str(gap_sec) + '秒（ほぼ差なし）')
        elif gap_sec <= 0.3:
            score += 2
            reasons.append('1着と' + str(gap_sec) + '秒差の僅差')
        elif gap_sec <= 0.5:
            score += 1
            reasons.append('1着と' + str(gap_sec) + '秒差（次走巻き返し圏内）')

        if score >= 4 and has_main and reasons:
            candidates.append({'horse': r, 'score': score})

    candidates.sort(key=lambda x: (-x['score'], x['horse']['入線順位']))
    return [c['horse'] for c in candidates[:3]]


def _parse_time_to_sec(s):
    if not s or str(s).strip() in ('', 'nan', 'None', '---', '----'):
        return None
    s = str(s).strip()
    parts = s.split('.')
    try:
        if len(parts) == 3:
            return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 10
        elif len(parts) == 2:
            return int(parts[0]) + int(parts[1]) / 10
    except (ValueError, IndexError):
        pass
    return None


def extract_from_review(html_path):
    html = html_path.read_text(encoding='utf-8', errors='ignore')

    m_data = re.search(r'const DATA\s*=\s*(\[.*?\]);', html, re.DOTALL)
    if not m_data:
        return []
    try:
        rows = json.loads(m_data.group(1))
    except json.JSONDecodeError:
        return []

    m_race = re.search(r'const RACE\s*=\s*(\{.*?\});', html, re.DOTALL)
    if not m_race:
        return []
    try:
        race = json.loads(m_race.group(1))
    except json.JSONDecodeError:
        return []

    if not any('着差_sec' in r for r in rows):
        winner_time = None
        for r in rows:
            if r.get('入線順位') == 1:
                winner_time = _parse_time_to_sec(r.get('タイム', ''))
                break
        for r in rows:
            t = _parse_time_to_sec(r.get('タイム', ''))
            if t is not None and winner_time is not None:
                r['着差_sec'] = round(t - winner_time, 1)
            else:
                r['着差_sec'] = 99.0

    pickup_horses = _find_pickup_horses(rows, race)
    if not pickup_horses:
        return []

    year  = str(race.get('年', ''))
    month = str(race.get('月', '')).zfill(2)
    day   = str(race.get('日', '')).zfill(2)
    date_str = year + '/' + month + '/' + day if year else ''

    def _clean(v):
        """pandasのNaNが文字列化された 'nan' を空文字に置換"""
        s = str(v).strip() if v is not None else ''
        return '' if s.lower() == 'nan' else s

    place = _clean(race.get('場所', ''))
    rnum  = int(race.get('R', 0)) if race.get('R') else 0
    rname = _clean(race.get('レース名', ''))
    klass = _clean(race.get('クラス名', ''))

    if not date_str:
        stem  = html_path.stem
        m_fn  = re.match(r'(\d{4})(\d{2})(\d{2})_([A-Z]+)(\d+)R', stem)
        if m_fn:
            date_str = m_fn.group(1) + '/' + m_fn.group(2) + '/' + m_fn.group(3)
            place    = PLACE_MAP.get(m_fn.group(4), m_fn.group(4))
            rnum     = int(m_fn.group(5))

    today = datetime.date.today().isoformat()
    entries = []
    for horse in pickup_horses:
        entries.append({
            '馬名': horse['馬名'],
            '登録日': today,
            '追加者': '',
            '元レース': {
                '日付': date_str,
                '場所': place,
                'R': rnum,
                'レース名': rname,
                'クラス': klass,
            },
            'メモ': '',
        })
    return entries


def load_memo():
    if MEMO_JSON.exists():
        try:
            return json.loads(MEMO_JSON.read_text(encoding='utf-8'))
        except Exception:
            pass
    return []


def save_memo(data):
    MEMO_JSON.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def dedup_key(entry):
    r = entry.get('元レース', {})
    return str(entry.get('馬名', '')) + '|' + str(r.get('日付', '')) + '|' + str(r.get('R', ''))


def main():
    existing = load_memo()
    existing_keys = {dedup_key(e) for e in existing}

    review_files = sorted(BASE.glob('*_review.html'))
    print('回顧HTML: ' + str(len(review_files)) + '件をスキャン中（新ロジック適用）...\n')

    added_total = 0
    for html_path in review_files:
        entries = extract_from_review(html_path)
        if not entries:
            continue
        added = []
        for e in entries:
            k = dedup_key(e)
            if k not in existing_keys:
                existing.append(e)
                existing_keys.add(k)
                added.append(e['馬名'])
        if added:
            ri = entries[0]['元レース']
            print('  [' + html_path.name + ']')
            print('    ' + str(ri['日付']) + ' ' + str(ri['場所']) + str(ri['R']) + 'R  -> 追加: ' + ', '.join(added))
            added_total += len(added)

    if added_total == 0:
        print('新たに追加する馬はありませんでした。')
        return

    save_memo(existing)
    print('\n合計 ' + str(added_total) + '頭 を memo_horses.json に追加しました。')
    print('\n次のコマンドでGitHubに反映してください:')
    print('  git add memo_horses.json')
    print('  git commit -m "memo: 新ロジック(B案)で次走注目馬を再登録"')
    print('  git push origin main')


if __name__ == '__main__':
    main()
