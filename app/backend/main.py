# -*- coding: utf-8 -*-
"""FastAPI エントリポイント。

起動: run_app.bat（中身は python -m uvicorn app.backend.main:app）
既定では 127.0.0.1:8000 のみで待ち受ける（自分のPC内だけ）。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .routers import login, memo, odds, public
from .services import auth

app = FastAPI(
    title='競馬予想/回顧ダッシュボード',
    description='既存の採点パイプラインをそのままエンジンとして使うWebアプリ',
    version='0.1.0',
)

app.include_router(public.router)
app.include_router(odds.router)
app.include_router(memo.router)

if config.PUBLIC_MODE:
    # 公開モードでは管理・検証を**読み込まない**。
    # 画面から隠すだけではURLを直接叩かれると動いてしまうので、
    # ルーター自体を登録せず「存在しない」状態にする。
    app.include_router(login.router)
else:
    from .routers import admin, validation
    app.include_router(admin.router)
    app.include_router(validation.router)


@app.middleware('http')
async def require_login(request: Request, call_next):
    """公開モードでは、ログインしていない要求をすべて止める。

    ダッシュボードHTMLも含めて止める（URLを知っていれば見える、を防ぐ）。
    """
    if not auth.enabled():
        return await call_next(request)

    path = request.url.path
    if path.startswith(login.OPEN_PATHS) or path.startswith('/assets/'):
        return await call_next(request)

    if auth.read_session(request.cookies.get(auth.COOKIE_NAME, '')):
        return await call_next(request)

    if path.startswith('/api/'):
        return JSONResponse({'detail': 'ログインしてください'}, status_code=401)
    return RedirectResponse(f'/login?next={path}', status_code=303)

_PLACEHOLDER = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>競馬ダッシュボード</title>
<style>body{font-family:system-ui,sans-serif;background:#1a1a2e;color:#eee;
padding:24px;line-height:1.8}code{background:#000;padding:2px 6px;border-radius:4px}</style>
</head><body>
<h1>バックエンドは動いています</h1>
<p>画面（フロントエンド）がまだビルドされていません。</p>
<p>開発中は <code>app/frontend</code> で <code>npm run dev</code> を実行してください。</p>
<p>APIの一覧は <a href="/docs" style="color:#f1c40f">/docs</a> で確認できます。</p>
</body></html>"""


@app.get('/', response_class=HTMLResponse, include_in_schema=False)
def index():
    idx = config.FRONTEND_DIST / 'index.html'
    if idx.exists():
        return HTMLResponse(idx.read_text(encoding='utf-8'))
    return HTMLResponse(_PLACEHOLDER)


if config.FRONTEND_DIST.exists():
    # ビルド済みフロントを配信（開発時は Vite の dev サーバを使うのでここは不要）
    app.mount('/assets',
              StaticFiles(directory=config.FRONTEND_DIST / 'assets'),
              name='assets')
