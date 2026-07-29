# -*- coding: utf-8 -*-
"""基準データと今の出力の「どこが違うか」を人が読める形で出す。

数値がズレたときに「馬名 / 項目名 / 基準値 → 今の値」で見えないと
原因を追えないので、単なる不一致ではなく差分の中身を返す。
"""
from __future__ import annotations

import math

REL_TOL = 1e-9
ABS_TOL = 1e-9


def _num_equal(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if a is None or b is None:
        return a is b
    fa, fb = float(a), float(b)
    if math.isnan(fa) and math.isnan(fb):
        return True
    return math.isclose(fa, fb, rel_tol=REL_TOL, abs_tol=ABS_TOL)


def diff(expected, actual, path: str = '', out: list | None = None,
         limit: int = 40) -> list:
    """再帰的に比較して差分のリストを返す。要素は (場所, 基準値, 今の値)。"""
    if out is None:
        out = []
    if len(out) >= limit:
        return out

    if isinstance(expected, dict) and isinstance(actual, dict):
        for k in expected:
            if k not in actual:
                out.append((f'{path}.{k}', expected[k], '(項目なし)'))
            else:
                diff(expected[k], actual[k], f'{path}.{k}', out, limit)
        for k in actual:
            if k not in expected:
                out.append((f'{path}.{k}', '(項目なし)', actual[k]))
        return out

    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            out.append((f'{path}[]件数', len(expected), len(actual)))
            return out
        for i, (e, a) in enumerate(zip(expected, actual)):
            label = f'{path}[{i}]'
            if isinstance(e, dict) and '馬名' in e:
                label = f'{path}[{e["馬名"]}]'
            diff(e, a, label, out, limit)
        return out

    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if not _num_equal(expected, actual):
            out.append((path, expected, actual))
        return out

    if expected != actual:
        out.append((path, expected, actual))
    return out


def format_diff(rows: list, head: int = 20) -> str:
    if not rows:
        return '(差分なし)'
    lines = [f'差分 {len(rows)} 件（先頭{min(head, len(rows))}件）:']
    for where, exp, act in rows[:head]:
        lines.append(f'  {where}: 基準={exp!r} → 今回={act!r}')
    if len(rows) > head:
        lines.append(f'  ... 他 {len(rows) - head} 件')
    return '\n'.join(lines)
