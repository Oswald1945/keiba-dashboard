# -*- coding: utf-8 -*-
"""生成した成果物を公開サーバーへ送る。

このPCで採点・生成したあとに実行する。送るのは閲覧に必要なものだけ。
race.db・採点データ・検証データは送らない（サーバーには不要で、重いため）。

送るもの:
    *_pred.html / *_review.html      ダッシュボード
    horses_data_*.json               レース一覧の元。**これが無いと一覧に出ない**
    baba_manual.json                 馬場データ
    app/data/kaisai_cache.json       開催回・発走時刻（race.db の代わり）

メモ馬（memo_horses.json）は特別扱い:
    サーバー側でも書き換わる（外出先や招待した人が書く）ため、単純に上書きすると
    相手の更新が消える。**サーバーを正**として統合し、結果を両側へ書き戻す。
    ただし「本文のあるものを空で潰さない」ことを優先する（下の merge_memo を参照）。

注目レース（featured_races.json）は同期しない:
    利用者ごとに持つ設計にしたため、それぞれの手元で完結する。

使い方:
    python app/tools/sync_to_server.py --check      送る内容を確認（送信しない）
    python app/tools/sync_to_server.py              送る
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.backend import config   # noqa: E402

CONF = config.DATA_DIR / 'server.json'
KAISAI_CACHE = config.DATA_DIR / 'kaisai_cache.json'

# scp はコマンドラインに全ファイル名を並べるので、Windows の長さ上限に当たる。
# 適当な数で区切って何回かに分けて呼ぶ。
BATCH = 60


def load_conf() -> dict:
    """接続先。app/data/server.json に置く（gitには入れない）。

    例:
      {"host": "example.com", "user": "keiba", "path": "/opt/keiba", "port": 22}
    """
    if not CONF.exists():
        return {}
    try:
        return json.loads(CONF.read_text(encoding='utf-8'))
    except Exception:
        return {}


def race_files(race_id: str) -> list:
    """1レース分の、閲覧に要るファイル。

    HTMLの命名は3種類あるので、実際の場所は paths に聞く。
    """
    from app.backend.services import paths
    out = []
    for p in (paths.pred_html(race_id), paths.review_html(race_id)):
        if p is not None:
            out.append(p)
    h = paths.horses_json(race_id)
    if h.exists():
        out.append(h)
    return out


def root_targets(only: list | None = None) -> list:
    """サーバーの設置フォルダ直下へ送るもの。

    only にレースIDを渡すと、そのレース分だけに絞る（管理画面から
    「選んだレースを公開する」を押したとき）。馬場は常に送る。
    """
    if only:
        out = []
        for rid in only:
            out.extend(race_files(rid))
    else:
        out = sorted(config.OUT_DIR.glob('*_pred.html'))
        out += sorted(config.OUT_DIR.glob('*_review.html'))
        out += sorted(config.OUT_DIR.glob('horses_data_*.json'))
    if config.BABA_MANUAL_JSON.exists():
        out.append(config.BABA_MANUAL_JSON)
    return out


def data_targets() -> list:
    """サーバーの app/data/ へ送るもの。"""
    return [KAISAI_CACHE] if KAISAI_CACHE.exists() else []


# ── メモ馬の統合 ────────────────────────────────────────────────
def _memo_key(e: dict) -> tuple:
    s = e.get('元レース') or {}
    return (e.get('馬名', ''), str(s.get('日付', '')), str(s.get('R', '')))


def _body(e: dict) -> str:
    return (e.get('メモ') or '').strip()


def merge_memo(local: list, remote: list) -> tuple:
    """サーバーを正としつつ、本文のあるものを空で潰さないように統合する。

    同じ馬・同じ元レースのものは「同じ登録」とみなす。

      サーバーに本文がある            → サーバーを採用（外出先で書いた内容を守る）
      サーバーが空でこちらに本文がある → こちらを採用（未同期の下書きを守る）
      サーバーに無い登録              → 追加する

    どちらにも本文があって食い違う場合はサーバーを採用し、件数を報告する。
    片方が空のときに上書きしないので、統合で本文が消えることはない。
    """
    merged: list = []
    filled: list = []       # サーバーが空で、こちらの本文を使ったもの
    conflicts: list = []    # 両方に本文があって食い違ったもの

    by_local = {_memo_key(e): e for e in local}
    for r in remote:
        k = _memo_key(r)
        l = by_local.get(k)
        e = dict(r)
        if l is not None and _body(l):
            if not _body(r):
                e['メモ'] = l['メモ']
                filled.append(e)
            elif _body(l) != _body(r):
                conflicts.append(e)
        merged.append(e)

    have = {_memo_key(e) for e in remote}
    added = [e for e in local if _memo_key(e) not in have]
    merged.extend(added)
    return merged, added, filled, conflicts


# ── サーバーとのやりとり ────────────────────────────────────────
def _ssh(conf: dict, script: str, data: bytes | None = None):
    cmd = ['ssh', '-p', str(conf.get('port', 22)),
           f'{conf["user"]}@{conf["host"]}', script]
    return subprocess.run(cmd, input=data, capture_output=True)


def remote_stats(conf: dict, subdir: str, patterns: list) -> dict:
    """サーバー側の {ファイル名: (サイズ, 更新時刻)}。取れなければ空。"""
    d = conf['path'].rstrip('/') + (f'/{subdir}' if subdir else '')
    script = f'cd {d} 2>/dev/null && stat -c "%n|%s|%Y" {" ".join(patterns)} 2>/dev/null'
    r = _ssh(conf, script)
    out: dict = {}
    for line in r.stdout.decode('utf-8', 'replace').splitlines():
        parts = line.strip().split('|')
        if len(parts) == 3:
            try:
                out[parts[0]] = (int(parts[1]), int(parts[2]))
            except ValueError:
                continue
    return out


def changed_only(files: list, remote: dict) -> list:
    """サーバーに無い、または中身が変わったものだけに絞る。

    scp -p で更新時刻ごと送るので、次回はここで一致して送信対象から外れる。
    """
    out = []
    for f in files:
        st = f.stat()
        r = remote.get(f.name)
        if r is None or r[0] != st.st_size or abs(r[1] - int(st.st_mtime)) > 2:
            out.append(f)
    return out


def send(conf: dict, files: list, subdir: str = '') -> int:
    if not files:
        return 0
    d = conf['path'].rstrip('/') + (f'/{subdir}' if subdir else '') + '/'
    dest = f'{conf["user"]}@{conf["host"]}:{d}'
    port = str(conf.get('port', 22))
    for i in range(0, len(files), BATCH):
        chunk = [str(f) for f in files[i:i + BATCH]]
        # -p で更新時刻を保つ（次回の差分判定に使う）
        rc = subprocess.run(['scp', '-p', '-q', '-P', port] + chunk + [dest]).returncode
        if rc != 0:
            return rc
        print(f'    {min(i + BATCH, len(files))}/{len(files)} 件')
    return 0


def sync_memo(conf: dict, check: bool) -> int:
    local = []
    if config.MEMO_JSON.exists():
        try:
            local = json.loads(config.MEMO_JSON.read_text(encoding='utf-8'))
        except Exception as e:
            print(f'  このPCのメモが読めません: {e}')
            return 1

    remote_path = conf['path'].rstrip('/') + '/memo_horses.json'
    r = _ssh(conf, f'cat {remote_path} 2>/dev/null')
    remote = []
    if r.returncode == 0 and r.stdout.strip():
        try:
            remote = json.loads(r.stdout.decode('utf-8'))
        except Exception as e:
            print(f'  サーバーのメモが読めません（中断します）: {e}')
            return 1

    merged, added, filled, conflicts = merge_memo(local, remote)
    print(f'  このPC {len(local)} 件 / サーバー {len(remote)} 件 → 統合後 {len(merged)} 件')
    print(f'    サーバーへ追加     : {len(added)} 件')
    print(f'    本文をPCから補完   : {len(filled)} 件')
    if conflicts:
        print(f'    本文が食い違い     : {len(conflicts)} 件（サーバー側を採用）')
        for e in conflicts[:5]:
            print(f'      - {e.get("馬名", "")}')
        if len(conflicts) > 5:
            print(f'      ほか {len(conflicts) - 5} 件')

    if check:
        return 0

    payload = json.dumps(merged, ensure_ascii=False, indent=2).encode('utf-8')

    # サーバー側：退避してから一時ファイル→置換
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    script = (f'f={remote_path}; '
              f'if [ -f "$f" ]; then cp -p "$f" "$f.{stamp}.bak"; fi; '
              f'cat > "$f.tmp" && mv "$f.tmp" "$f"')
    w = _ssh(conf, script, payload)
    if w.returncode != 0:
        print('  サーバーへの書き込みに失敗しました:',
              w.stderr.decode('utf-8', 'replace').strip())
        return 1
    print('  サーバーを更新しました（旧ファイルは .bak で残しています）')

    # このPC側：退避してから一時ファイル→置換
    if config.MEMO_JSON.exists():
        config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config.MEMO_JSON,
                     config.BACKUP_DIR / f'memo_horses_{stamp}_sync.json')
    tmp = config.MEMO_JSON.with_suffix('.tmp')
    tmp.write_bytes(payload)
    tmp.replace(config.MEMO_JSON)
    print('  このPCも更新しました（旧ファイルは _archive に退避）')
    return 0


def print_status(conf: dict, date: str) -> int:
    """指定日の各レースが、サーバーに反映済みかどうかをJSONで出す。

    管理画面が「未公開のものを選ぶ」ために使う。
    送信はしない（読み取りだけ）。
    """
    from app.backend.services import catalog, paths
    remote = remote_stats(conf, '', ['*_pred.html', '*_review.html'])

    def state(p) -> str:
        if p is None:
            return 'none'
        st = p.stat()
        r = remote.get(p.name)
        if r is None:
            return 'pending'
        return 'sent' if (r[0] == st.st_size and abs(r[1] - int(st.st_mtime)) <= 2) else 'pending'

    out = {}
    for row in catalog.list_races():
        if row['date'] != date:
            continue
        rid = row['race_id']
        out[rid] = {'pred': state(paths.pred_html(rid)),
                    'review': state(paths.review_html(rid))}
    print(json.dumps(out, ensure_ascii=False))
    return 0


def verify(conf: dict) -> None:
    """送ったあと、サーバー側で何件見えているかを確認する。

    「送ったつもりで反映されていない」を、その場で気づけるようにする。
    """
    path = conf['path'].rstrip('/')
    script = (
        f"cd {path} && {path}/.venv/bin/python - <<'PYEOF'\n"
        "import os, sys\n"
        "os.environ['KEIBA_PUBLIC'] = '1'\n"
        f"sys.path.insert(0, '{path}')\n"
        "from app.backend.services import catalog\n"
        "rows = catalog.list_races()\n"
        "print(len(rows), sum(1 for r in rows if r['has_pred']),"
        " sum(1 for r in rows if r['has_review']))\n"
        'PYEOF'
    )
    r = _ssh(conf, script)
    parts = r.stdout.decode('utf-8', 'replace').split()
    if r.returncode != 0 or len(parts) != 3:
        print('  確認できませんでした（送信自体は完了しています）')
        return
    total, pred, review = parts
    print(f'  サーバーの一覧: {total} レース（予想 {pred} / 回顧 {review}）')


def export_kaisai() -> None:
    """開催回・発走時刻の控えを作り直す（実行忘れの防止）。

    race.db を読むので、このPCでしか作れない。失敗しても同期は続ける
    （開催回・発走時刻が古いままになるだけで、一覧は表示できる）。
    """
    script = pathlib.Path(__file__).with_name('export_kaisai.py')
    if subprocess.run([sys.executable, str(script)]).returncode != 0:
        print('  作れませんでした（開催回・発走時刻は更新されません）')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='送らずに内容だけ確認する')
    ap.add_argument('--only', nargs='*', metavar='レースID',
                    help='指定したレースだけ送る（管理画面の「選んだレースを公開」用）')
    ap.add_argument('--status', metavar='YYYYMMDD',
                    help='その日の各レースが反映済みかをJSONで出す（送信しない）')
    args = ap.parse_args()

    conf = load_conf()
    if not conf:
        print(f'接続先が未設定です。{CONF} に次の形で保存してください:')
        print('  {"host": "example.com", "user": "keiba", "path": "/opt/keiba", "port": 22}')
        return 1

    if args.status:
        return print_status(conf, args.status)

    print('■ 開催回・発走時刻の控えを更新')
    if args.check:
        print('  （--check のため実行しません）')
    else:
        export_kaisai()

    files = root_targets(args.only)
    data = data_targets()
    total = sum(f.stat().st_size for f in files + data) / 1024 / 1024
    print()
    if args.only:
        print(f'■ 対象: 選んだ {len(args.only)} レース')
    print(f'■ 送る対象: {len(files) + len(data)} ファイル / {total:.1f} MB')
    print(f'  予想HTML     : {sum(1 for f in files if f.name.endswith("_pred.html"))} 件')
    print(f'  回顧HTML     : {sum(1 for f in files if f.name.endswith("_review.html"))} 件')
    print(f'  レース一覧の元: {sum(1 for f in files if f.name.startswith("horses_data_"))} 件')

    print()
    print(f'■ 送信先: {conf["user"]}@{conf["host"]}:{conf["path"]}/')
    print('  サーバーの状態を確認しています…')
    r_root = remote_stats(conf, '', ['*_pred.html', '*_review.html',
                                     'horses_data_*.json', 'baba_manual.json'])
    r_data = remote_stats(conf, 'app/data', ['kaisai_cache.json'])
    todo = changed_only(files, r_root)
    todo_data = changed_only(data, r_data)
    todo_mb = sum(f.stat().st_size for f in todo + todo_data) / 1024 / 1024
    print(f'  今回送るのは {len(todo) + len(todo_data)} ファイル / {todo_mb:.1f} MB'
          f'（残りは同じ内容なので送りません）')

    print()
    print('■ メモ馬の統合')
    rc = sync_memo(conf, args.check)
    if rc:
        return rc

    if args.check:
        print()
        print('（--check のため送信しません）')
        return 0

    print()
    print('■ 送信')
    rc = send(conf, todo)
    if rc:
        return rc
    rc = send(conf, todo_data, 'app/data')
    if rc:
        return rc
    print('  完了しました。')

    print()
    print('■ 反映確認')
    verify(conf)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
