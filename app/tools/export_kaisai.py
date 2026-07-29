# -*- coding: utf-8 -*-
"""開催回・開催日目・発走時刻を小さなJSONに書き出す。

公開サーバーには race.db（約2GB・Windows/COM依存）を置けないため、
一覧に出す「第2回2日目」「15:30」だけを取り出して持っていく。

出力: app/data/kaisai_cache.json（数十KB）
      同期ツールがサーバーへ送り、race.db が無い環境ではこれを読む。

使い方:
    python app/tools/export_kaisai.py
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.backend import config                        # noqa: E402
from app.backend.services import catalog, racedb      # noqa: E402

OUT = config.DATA_DIR / 'kaisai_cache.json'


def main() -> int:
    rows = catalog.list_races()
    dates = sorted({r['date'] for r in rows if r.get('date')})
    if not dates:
        print('レースがありません。')
        return 1

    info = racedb.kaisai_info(dates)      # (日付, 場コード) -> {'kaiji','nichiji'}
    times = racedb.start_times(dates)     # (日付, 場コード, R) -> 'HH:MM'

    data = {
        'kaisai': {f'{d}|{j}': v for (d, j), v in info.items()},
        'start_times': {f'{d}|{j}|{r}': t for (d, j, r), t in times.items()},
    }
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    tmp.replace(OUT)

    size = OUT.stat().st_size / 1024
    print(f'書き出しました: {OUT.name}  {size:.1f} KB')
    print(f'  対象日付   : {len(dates)} 日（{dates[0]}〜{dates[-1]}）')
    print(f'  開催情報   : {len(data["kaisai"])} 件')
    print(f'  発走時刻   : {len(data["start_times"])} 件')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
