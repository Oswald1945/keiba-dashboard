# -*- coding: utf-8 -*-
"""公開サーバーの利用者（招待した人）を管理する。

利用者は**招待リンク**から、自分でIDとパスワードを決めて登録します。
管理者はパスワードを知りません（ハッシュしか保存されません）。

使い方:
    python app/tools/user_admin.py invite --memo "山田さん"   招待リンクを発行
    python app/tools/user_admin.py invites                    招待の一覧
    python app/tools/user_admin.py revoke <トークン>          未使用の招待を取り消す
    python app/tools/user_admin.py list                       利用者の一覧
    python app/tools/user_admin.py remove <ID>                利用者を削除

パスワードを忘れた人には、新しい招待リンクを発行するのではなく、
その人を remove してから invite で作り直してもらってください
（IDを引き継ぎたい場合も同じ手順で、同じIDを取り直せます）。
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.backend.services import auth   # noqa: E402

DEFAULT_BASE = 'https://（サーバーのアドレス）'


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    i = sub.add_parser('invite', help='招待リンクを発行')
    i.add_argument('--memo', default='', help='誰用かのメモ（任意）')
    i.add_argument('--days', type=int, default=auth.INVITE_DAYS, help='有効日数')
    i.add_argument('--base', default=DEFAULT_BASE, help='公開URL（例 https://example.com）')
    sub.add_parser('invites', help='招待の一覧')
    rv = sub.add_parser('revoke', help='未使用の招待を取り消す')
    rv.add_argument('token')
    sub.add_parser('list', help='利用者の一覧')
    rm = sub.add_parser('remove', help='利用者を削除')
    rm.add_argument('user_id')
    args = ap.parse_args()

    if args.cmd == 'invite':
        token = auth.create_invite(args.memo, args.days)
        print()
        print('─' * 62)
        print(f'  {args.base.rstrip("/")}/invite/{token}')
        print('─' * 62)
        print(f'このリンクを本人にだけ直接お渡しください（有効 {args.days} 日・1回限り）。')
        print('本人がIDとパスワードを決めて登録します。')
        if args.base == DEFAULT_BASE:
            print()
            print('※ 公開URLが未確定のため仮表示です。決まったら --base で指定してください。')
            print('   例: python app/tools/user_admin.py invite --base https://example.com')
        return 0

    if args.cmd == 'invites':
        inv = auth.load_invites()
        if not inv:
            print('招待はありません。')
            return 0
        now = time.time()
        print(f'{len(inv)} 件')
        for tok, r in sorted(inv.items(), key=lambda x: x[1].get('created', '')):
            if r.get('used_by'):
                state = f'使用済み → {r["used_by"]}（{r.get("used_at", "")}）'
            elif int(r.get('expires', 0)) < now:
                state = '期限切れ'
            else:
                残り = int((int(r['expires']) - now) / 86400)
                state = f'未使用（あと{残り}日）'
            print(f'  {tok[:16]}…  {r.get("created", "")}  {state}  {r.get("memo", "")}')
        return 0

    if args.cmd == 'revoke':
        inv = auth.load_invites()
        hit = [t for t in inv if t.startswith(args.token)]
        if not hit:
            print('その招待は見つかりません。invites で確認してください。')
            return 1
        if len(hit) > 1:
            print('複数一致しました。もう少し長く指定してください。')
            return 1
        tok = hit[0]
        if inv[tok].get('used_by'):
            print('既に使用済みです。取り消しではなく remove で利用者を削除してください。')
            return 1
        inv.pop(tok)
        auth.save_invites(inv)
        print('招待を取り消しました。このリンクは使えません。')
        return 0

    users = auth.load_users()

    if args.cmd == 'list':
        if not users:
            print('利用者はまだ登録されていません。')
            return 0
        print(f'{len(users)} 名')
        for uid, u in sorted(users.items()):
            print(f'  {uid:<16} 登録 {u.get("created", "-")}  {u.get("memo", "")}')
        return 0

    if args.cmd == 'remove':
        if args.user_id not in users:
            print(f'{args.user_id} は登録されていません。')
            return 1
        users.pop(args.user_id)
        auth.save_users(users)
        print(f'{args.user_id} を削除しました。ログイン中でもすぐ使えなくなります。')
        return 0

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
