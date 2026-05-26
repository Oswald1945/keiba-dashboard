# -*- coding: utf-8 -*-
"""自信あり条件: 実人気チェック → SmartRC推定人気順チェックに修正"""
import pathlib

src = pathlib.Path(__file__).parent / 'build_dashboard_v3.py'
data = src.read_bytes()

old = (
    "_pred1_is_fav = next((h.get('人気') for h in horses if h['馬名'] == _pred1_name), 99) == 1"
).encode('utf-8')

new = (
    "_pred1_smartrc_rank = next(\n"
    "    (int(h.get('SmartRC推定人気順') or 99)\n"
    "     for h in horses if h['馬名'] == _pred1_name), 99)\n"
    "_pred1_is_fav = _pred1_smartrc_rank == 1  # SmartRC推定1番人気=妙味なし"
).encode('utf-8')

cnt = data.count(old)
print(f'パターン一致: {cnt}件')
assert cnt == 1, 'パターンが見つかりません'
data = data.replace(old, new, 1)
src.write_bytes(data)
print('完了')
