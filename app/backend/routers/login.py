# -*- coding: utf-8 -*-
"""ログイン画面とアクセス制御。公開モードのときだけ効く。"""
from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..services import auth

router = APIRouter()

# ログインしていなくても通す道（ログイン画面・招待画面と、その見た目に必要なもの）
OPEN_PATHS = ('/login', '/invite/', '/api/health', '/favicon.ico')

_PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ログイン — 競馬予想/回顧ダッシュボード</title>
<style>
  :root {{ --green:#004c2c; --line:#b4c9be; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:#dde8e2; color:#2b2b2b; padding:16px;
         font-family:"Hiragino Sans","ヒラギノ角ゴ ProN W3",メイリオ,Meiryo,sans-serif; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:12px;
          width:100%; max-width:360px; overflow:hidden; }}
  h1 {{ margin:0; background:var(--green); color:#fff; font-size:16px; padding:14px 16px; }}
  form {{ padding:18px 16px; display:grid; gap:12px; }}
  label {{ font-size:12px; color:#4d5a53; }}
  input {{ width:100%; padding:11px 12px; font-size:16px; border:1px solid var(--line);
          border-radius:8px; font-family:inherit; }}
  button {{ padding:12px; font-size:15px; font-weight:700; color:#fff; background:var(--green);
           border:none; border-radius:8px; cursor:pointer; font-family:inherit; }}
  .err {{ background:#fdeee6; border:1px solid #d9865a; color:#8a4520;
         padding:9px 12px; border-radius:8px; font-size:13px; }}
  .note {{ padding:0 16px 16px; font-size:11px; color:#4d5a53; line-height:1.7; }}
</style></head><body>
<div class="card">
  <h1>競馬予想 / 回顧ダッシュボード</h1>
  <form method="post" action="/login">
    {error}
    <div><label for="u">ID</label><input id="u" name="user_id" autocomplete="username"
         autocapitalize="off" autocorrect="off" required></div>
    <div><label for="p">パスワード</label><input id="p" name="password" type="password"
         autocomplete="current-password" required></div>
    <input type="hidden" name="next" value="{next}">
    <button type="submit">ログイン</button>
  </form>
  <div class="note">招待制です。IDとパスワードは管理者から受け取ってください。</div>
</div>
</body></html>"""


def _page(error: str = '', next_url: str = '/') -> HTMLResponse:
    err = f'<div class="err">{error}</div>' if error else ''
    safe_next = next_url if next_url.startswith('/') else '/'
    return HTMLResponse(_PAGE.format(error=err, next=safe_next))


@router.get('/login', response_class=HTMLResponse, include_in_schema=False)
def login_form(request: Request):
    if auth.read_session(request.cookies.get(auth.COOKIE_NAME, '')):
        return RedirectResponse('/', status_code=303)
    nxt = request.query_params.get('next', '/')
    return _page(next_url=nxt)


@router.post('/login', include_in_schema=False)
async def login_submit(request: Request):
    # FastAPI の Form(...) は python-multipart を要求するので、
    # 追加ライブラリを増やさないよう本文を自前で読む（通常のフォーム送信）。
    raw = (await request.body()).decode('utf-8', errors='replace')
    form = dict(urllib.parse.parse_qsl(raw, keep_blank_values=True))
    user_id = form.get('user_id', '').strip()
    password = form.get('password', '')
    next = form.get('next', '/')

    token = auth.login(user_id, password)
    if not token:
        # 「IDが無い」と「パスワードが違う」は区別しない（IDの存在を教えないため）
        return _page('IDまたはパスワードが違います。', next)
    resp = RedirectResponse(next if next.startswith('/') else '/', status_code=303)
    resp.set_cookie(
        auth.COOKIE_NAME, token,
        max_age=auth.SESSION_DAYS * 86400,
        httponly=True,          # JavaScriptから読めない
        samesite='lax',
        secure=request.url.scheme == 'https',
    )
    return resp


@router.get('/logout', include_in_schema=False)
def logout():
    resp = RedirectResponse('/login', status_code=303)
    resp.delete_cookie(auth.COOKIE_NAME)
    return resp


# ── 招待リンクからの登録 ──────────────────────────────────────
_FORM = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — 競馬予想/回顧ダッシュボード</title>
<style>
  :root {{ --green:#004c2c; --line:#b4c9be; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
         background:#dde8e2; color:#2b2b2b; padding:16px;
         font-family:"Hiragino Sans","ヒラギノ角ゴ ProN W3",メイリオ,Meiryo,sans-serif; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:12px;
          width:100%; max-width:380px; overflow:hidden; }}
  h1 {{ margin:0; background:var(--green); color:#fff; font-size:16px; padding:14px 16px; }}
  form {{ padding:18px 16px; display:grid; gap:12px; }}
  label {{ font-size:12px; color:#4d5a53; }}
  input {{ width:100%; padding:11px 12px; font-size:16px; border:1px solid var(--line);
          border-radius:8px; font-family:inherit; }}
  button {{ padding:12px; font-size:15px; font-weight:700; color:#fff; background:var(--green);
           border:none; border-radius:8px; cursor:pointer; font-family:inherit; }}
  .err {{ background:#fdeee6; border:1px solid #d9865a; color:#8a4520;
         padding:9px 12px; border-radius:8px; font-size:13px; }}
  .ok {{ background:#e3f2ea; border:1px solid #0a7d3c; color:#0a5c34;
        padding:9px 12px; border-radius:8px; font-size:13px; }}
  .note {{ padding:0 16px 16px; font-size:11px; color:#4d5a53; line-height:1.7; }}
  a {{ color:#0155ad; }}
</style></head><body>
<div class="card">
  <h1>{title}</h1>
  {body}
  <div class="note">{note}</div>
</div>
</body></html>"""

_INVITE_NG = {
    'unknown': 'この招待リンクは無効です。管理者に新しいリンクを依頼してください。',
    'used': 'この招待リンクは既に使われています。ログイン画面からお入りください。',
    'expired': 'この招待リンクは期限切れです。管理者に新しいリンクを依頼してください。',
}


def _invite_page(token: str, error: str = '') -> HTMLResponse:
    err = f'<div class="err">{error}</div>' if error else ''
    body = f"""<form method="post" action="/invite/{token}">
    {err}
    <div><label for="u">ID（半角英数字3〜20文字・あとから変更できません）</label>
      <input id="u" name="user_id" autocomplete="username" autocapitalize="off"
             autocorrect="off" required></div>
    <div><label for="p">パスワード（{auth.PASSWORD_MIN}文字以上）</label>
      <input id="p" name="password" type="password" autocomplete="new-password" required></div>
    <div><label for="p2">パスワード（確認）</label>
      <input id="p2" name="password2" type="password" autocomplete="new-password" required></div>
    <button type="submit">登録して始める</button>
  </form>"""
    return HTMLResponse(_FORM.format(
        title='はじめての登録', body=body,
        note='このリンクは1回だけ使えます。IDとパスワードはご自身で決めてください。'
             'パスワードは管理者にも分かりません。'))


@router.get('/invite/{token}', response_class=HTMLResponse, include_in_schema=False)
def invite_form(token: str):
    st = auth.invite_state(token)
    if st != 'ok':
        return HTMLResponse(_FORM.format(
            title='招待リンク', body=f'<div style="padding:18px 16px"><div class="err">'
            f'{_INVITE_NG[st]}</div></div>',
            note='<a href="/login">ログイン画面へ</a>'), status_code=410)
    return _invite_page(token)


@router.post('/invite/{token}', include_in_schema=False)
async def invite_submit(token: str, request: Request):
    if auth.invite_state(token) != 'ok':
        return RedirectResponse(f'/invite/{token}', status_code=303)
    raw = (await request.body()).decode('utf-8', errors='replace')
    form = dict(urllib.parse.parse_qsl(raw, keep_blank_values=True))
    uid = form.get('user_id', '').strip()
    pw, pw2 = form.get('password', ''), form.get('password2', '')

    ng = auth.check_new_account(uid, pw, pw2)
    if ng:
        return _invite_page(token, ng)
    sess = auth.consume_invite(token, uid, pw)
    if not sess:
        return _invite_page(token, '登録できませんでした。リンクを開き直してください。')
    resp = RedirectResponse('/', status_code=303)
    resp.set_cookie(auth.COOKIE_NAME, sess, max_age=auth.SESSION_DAYS * 86400,
                    httponly=True, samesite='lax',
                    secure=request.url.scheme == 'https')
    return resp


# ── パスワード変更（ログイン後） ──────────────────────────────
def _password_page(msg: str = '', ok: bool = False) -> HTMLResponse:
    cls = 'ok' if ok else 'err'
    note = f'<div class="{cls}">{msg}</div>' if msg else ''
    body = f"""<form method="post" action="/settings/password">
    {note}
    <div><label for="c">現在のパスワード</label>
      <input id="c" name="current" type="password" autocomplete="current-password" required></div>
    <div><label for="n">新しいパスワード（{auth.PASSWORD_MIN}文字以上）</label>
      <input id="n" name="new" type="password" autocomplete="new-password" required></div>
    <div><label for="n2">新しいパスワード（確認）</label>
      <input id="n2" name="new2" type="password" autocomplete="new-password" required></div>
    <button type="submit">変更する</button>
  </form>"""
    return HTMLResponse(_FORM.format(title='パスワードの変更', body=body,
                                     note='<a href="/">ダッシュボードへ戻る</a>'))


@router.get('/settings/password', response_class=HTMLResponse, include_in_schema=False)
def password_form(request: Request):
    if not auth.read_session(request.cookies.get(auth.COOKIE_NAME, '')):
        return RedirectResponse('/login?next=/settings/password', status_code=303)
    return _password_page()


@router.post('/settings/password', include_in_schema=False)
async def password_submit(request: Request):
    uid = auth.read_session(request.cookies.get(auth.COOKIE_NAME, ''))
    if not uid:
        return RedirectResponse('/login?next=/settings/password', status_code=303)
    raw = (await request.body()).decode('utf-8', errors='replace')
    form = dict(urllib.parse.parse_qsl(raw, keep_blank_values=True))
    ng = auth.change_password(uid, form.get('current', ''),
                              form.get('new', ''), form.get('new2', ''))
    if ng:
        return _password_page(ng)
    return _password_page('パスワードを変更しました。', ok=True)
