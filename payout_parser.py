# -*- coding: utf-8 -*-
"""
payout_parser.py — TARGET の HTML レース結果から払戻（配当）を抽出する。

TARGET の HTML 結果には、回顧用データ（着順・タイム・通過順位・PCI・上3F・決め手・
前走情報 等）に加え、全券種の払戻（単勝/複勝/枠連/馬連/ワイド/馬単/三連複/三連単）が
含まれる。本モジュールは払戻セクションをパースして
  {券種: [(組番, 配当円), ...]} を返す。

使い方:
  from payout_parser import parse_payout
  po = parse_payout('レース結果_20260614_hd10.html')
  # po['umaren'] -> [('10-12', 9970)]
"""
import re
import unicodedata

# 表記ゆれを正規化したうえでのキー対応（全角→半角 NFKC 後）
_BET_KEYS = {
    '単勝': 'tansho', '複勝': 'fukusho', '枠連': 'wakuren', '馬連': 'umaren',
    'ワイド': 'wide', '馬単': 'umatan', '3連複': 'sanrenpuku', '3連単': 'sanrentan',
}
# 組番\配当 のパターン（金額は ¥(cp932で \) が前置される。(人気) は除外される）
_PAIR = re.compile(r'([0-9]{1,2}(?:-[0-9]{1,2}){0,2})\s*\\([0-9,]+)')


def parse_payout(html_path, encoding='cp932'):
    """HTMLパスから {券種en: [(組番, 配当int), ...]} を返す。"""
    raw = open(html_path, 'rb').read()
    try:
        t = raw.decode(encoding)
    except UnicodeDecodeError:
        t = raw.decode('utf-8', errors='replace')
    txt = re.sub(r'<[^>]+>', ' ', t)
    txt = re.sub(r'[ \t]+', ' ', txt)
    out = {}
    for line in txt.splitlines():
        l = unicodedata.normalize('NFKC', line.strip())
        if not l:
            continue
        for jp, en in _BET_KEYS.items():
            if l.startswith(jp):
                items = []
                for combo, amt in _PAIR.findall(l[len(jp):]):
                    try:
                        items.append((combo, int(amt.replace(',', ''))))
                    except ValueError:
                        pass
                if items:
                    out[en] = items
                break
    return out


if __name__ == '__main__':
    import sys, json
    p = sys.argv[1]
    print(json.dumps(parse_payout(p), ensure_ascii=False, indent=2))
