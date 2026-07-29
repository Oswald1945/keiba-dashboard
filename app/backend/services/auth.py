# -*- coding: utf-8 -*-
"""招待制のログイン。

外部に公開するときだけ使う。自分のPCの中で動かしている間は無効のまま。

作り:
  - 利用者は app/data/users.json に置く（管理者が発行する。自己登録はできない）
  - パスワードは PBKDF2-HMAC-SHA256 で保存。平文もパスワードのハッシュ元も残さない
  - ログイン状態は署名付きCookie。改ざんすると弾かれる
  - 追加ライブラリは使わない（標準の hashlib / hmac / secrets のみ）

管理者の操作:
    python app/tools/user_admin.py add <ID>       利用者を追加
    python app/tools/user_admin.py list           一覧
    python app/tools/user_admin.py remove <ID>    削除
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from .. import config

USERS_JSON = config.DATA_DIR / 'users.json'
INVITES_JSON = config.DATA_DIR / 'invites.json'
SECRET_FILE = config.DATA_DIR / 'session_secret.txt'

INVITE_DAYS = 7          # 招待リンクの有効期間
PASSWORD_MIN = 10        # パスワードの最低文字数
USER_ID_RE = r'^[A-Za-z0-9_-]{3,20}$'

COOKIE_NAME = 'keiba_session'
SESSION_DAYS = 14
PBKDF2_ROUNDS = 240_000

# 総当たり対策。IDごとに失敗回数を数え、続けて外すと待たせる。
_FAILS: dict = {}
FAIL_LIMIT = 5
FAIL_WINDOW = 300      # 5分間に5回外したら
FAIL_LOCK = 300        # 5分ロック


def enabled() -> bool:
    """公開モードのときだけログインを要求する。"""
    return config.PUBLIC_MODE


# ── パスワード ───────────────────────────────────────────────
def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PBKDF2_ROUNDS)
    return f'pbkdf2_sha256${PBKDF2_ROUNDS}${base64.b64encode(salt).decode()}' \
           f'${base64.b64encode(dk).decode()}'


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_b64, dk_b64 = stored.split('$')
        if algo != 'pbkdf2_sha256':
            return False
        dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'),
                                 base64.b64decode(salt_b64), int(rounds))
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


# ── 利用者 ───────────────────────────────────────────────────
def load_users() -> dict:
    if not USERS_JSON.exists():
        return {}
    try:
        return json.loads(USERS_JSON.read_text(encoding='utf-8'))
    except Exception:
        return {}


def save_users(users: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = USERS_JSON.with_suffix('.tmp')
    tmp.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(USERS_JSON)
    try:
        os.chmod(USERS_JSON, 0o600)
    except OSError:
        pass


# ── 招待リンク ───────────────────────────────────────────────
def load_invites() -> dict:
    if not INVITES_JSON.exists():
        return {}
    try:
        return json.loads(INVITES_JSON.read_text(encoding='utf-8'))
    except Exception:
        return {}


def save_invites(inv: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = INVITES_JSON.with_suffix('.tmp')
    tmp.write_text(json.dumps(inv, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(INVITES_JSON)
    try:
        os.chmod(INVITES_JSON, 0o600)
    except OSError:
        pass


def create_invite(memo: str = '', days: int = INVITE_DAYS) -> str:
    """1回だけ使える招待トークンを発行する。"""
    token = secrets.token_urlsafe(24)
    inv = load_invites()
    inv[token] = {
        'created': time.strftime('%Y-%m-%d %H:%M'),
        'expires': int(time.time()) + days * 86400,
        'memo': memo,
        'used_by': None,
    }
    save_invites(inv)
    return token


def invite_state(token: str) -> str:
    """'ok' / 'used' / 'expired' / 'unknown' を返す。"""
    rec = load_invites().get(token)
    if not rec:
        return 'unknown'
    if rec.get('used_by'):
        return 'used'
    if int(rec.get('expires', 0)) < time.time():
        return 'expired'
    return 'ok'


def check_new_account(user_id: str, password: str, password2: str) -> str | None:
    """登録内容の不備を日本語で返す。問題なければ None。"""
    import re
    if not re.match(USER_ID_RE, user_id or ''):
        return 'IDは半角英数字・ハイフン・アンダースコアで3〜20文字にしてください。'
    if user_id in load_users():
        return 'そのIDは既に使われています。別のIDにしてください。'
    if len(password or '') < PASSWORD_MIN:
        return f'パスワードは{PASSWORD_MIN}文字以上にしてください。'
    if password != password2:
        return 'パスワードが一致しません。'
    return None


def consume_invite(token: str, user_id: str, password: str) -> str | None:
    """招待を使ってアカウントを作る。成功したらセッション文字列を返す。"""
    if invite_state(token) != 'ok':
        return None
    users = load_users()
    users[user_id] = {
        'password': hash_password(password),
        'created': time.strftime('%Y-%m-%d'),
        'memo': load_invites().get(token, {}).get('memo', ''),
    }
    save_users(users)
    inv = load_invites()
    inv[token]['used_by'] = user_id
    inv[token]['used_at'] = time.strftime('%Y-%m-%d %H:%M')
    save_invites(inv)
    return make_session(user_id)


def change_password(user_id: str, current: str, new: str, new2: str) -> str | None:
    """パスワード変更。問題があれば日本語のメッセージを返す。"""
    users = load_users()
    u = users.get(user_id)
    if not u or not verify_password(current, u.get('password', '')):
        return '現在のパスワードが違います。'
    if len(new or '') < PASSWORD_MIN:
        return f'新しいパスワードは{PASSWORD_MIN}文字以上にしてください。'
    if new != new2:
        return '新しいパスワードが一致しません。'
    u['password'] = hash_password(new)
    users[user_id] = u
    save_users(users)
    return None


# ── 署名付きCookie ───────────────────────────────────────────
def _secret() -> bytes:
    """このサーバー固有の署名鍵。無ければ作る。"""
    if SECRET_FILE.exists():
        return SECRET_FILE.read_bytes()
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(32)
    SECRET_FILE.write_bytes(key)
    try:
        os.chmod(SECRET_FILE, 0o600)
    except OSError:
        pass
    return key


def make_session(user_id: str) -> str:
    exp = int(time.time()) + SESSION_DAYS * 86400
    body = f'{user_id}:{exp}'.encode('utf-8')
    sig = hmac.new(_secret(), body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(body + b'.' + sig).decode()


def read_session(token: str) -> str | None:
    """正しい署名で期限内なら利用者IDを返す。それ以外は None。"""
    try:
        raw = base64.urlsafe_b64decode(token.encode())
        body, sig = raw.rsplit(b'.', 1)
        expect = hmac.new(_secret(), body, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expect):
            return None
        user_id, exp = body.decode('utf-8').rsplit(':', 1)
        if int(exp) < time.time():
            return None
        if user_id not in load_users():
            return None          # 削除された利用者はその場で無効
        return user_id
    except Exception:
        return None


# ── ログイン ─────────────────────────────────────────────────
def locked_until(user_id: str) -> float:
    rec = _FAILS.get(user_id)
    if not rec:
        return 0.0
    count, first, until = rec
    return until


def login(user_id: str, password: str) -> str | None:
    """成功したらセッション用の文字列を返す。失敗は None。"""
    now = time.time()
    rec = _FAILS.get(user_id)
    if rec and rec[2] > now:
        return None                              # ロック中
    users = load_users()
    u = users.get(user_id)
    ok = bool(u) and verify_password(password, u.get('password', ''))
    if not ok:
        count, first, _ = rec or (0, now, 0.0)
        if now - first > FAIL_WINDOW:
            count, first = 0, now
        count += 1
        _FAILS[user_id] = (count, first,
                           now + FAIL_LOCK if count >= FAIL_LIMIT else 0.0)
        return None
    _FAILS.pop(user_id, None)
    return make_session(user_id)
