# 公開サーバーの設置・運用手順（さくらのVPS / Ubuntu 24.04）

このPCで採点・生成し、その成果物を公開サーバーへ送って、招待した人に見てもらうための手順です。
**すでに構築済み**の内容を記録したものでもあります。作り直すときはこの順で進めれば同じ環境になります。

---

## 全体像

```
[このPC]  採点・生成・管理・検証   ← 従来どおり。電源は落としてOK
    │
    │  生成後に同期（約94MB・数十秒）
    ↓
[公開サーバー]  閲覧＋メモ書き込み   ← 常時稼働・ログイン必須
    ↑
    │  招待した数名がスマホ・PCから
```

**サーバーに置かないもの**：`race.db`（約2GB）、JV-Link、採点エンジン（pandas/numpy）、検証データ。
これらはこのPC専用です。サーバーには**閲覧に必要な分だけ**を置きます。

---

## 現在の構成

| 項目 | 値 |
|---|---|
| 事業者 | さくらのVPS |
| IPアドレス | `49.212.183.192` |
| ログインユーザー | `ubuntu` |
| OS | Ubuntu 24.04 LTS |
| Python | 3.12.3（OS標準。追加導入は不要） |
| 設置場所 | `/opt/keiba` |
| 公開URL | `https://oz-king-keiba.com`（`www` 付きも可） |
| ディスク使用量 | 約180MB |

---

## 1. サーバーとOS

さくらのVPSのコントロールパネルから、**OSインストール → Ubuntu 24.04** を選ぶだけです。
数分で完了し、`ubuntu` ユーザーとSSH鍵（またはパスワード）が用意されます。

> **なぜ さくらのVPS なのか**
> 当初お名前.com VPSで構築を試みましたが、ISOからのUbuntu導入がインストーラーの
> クラッシュ・コンソール切断で完走しませんでした（26.04・24.04とも）。
> さくらのVPSは Ubuntu 24.04 を標準テンプレートとして持っており、導入は全自動です。

---

## 2. 通信を許可する（パケットフィルタ）

**ここを忘れると、サーバー内で何を設定しても外から繋がりません。**
さくらのVPSは既定で通信を絞っており、これは**サーバー内の設定では解除できません**。

```
コントロールパネル → サーバー詳細 → 「パケットフィルター」
   → 「パケットフィルターを設定」
```

以下を1つの設定にまとめて登録します。

| フィルターの名前 | プロトコル | ポート番号 | 送信元IP |
|---|---|---|---|
| Web | TCP | **80 / 443 / 22** | すべて許可 |

- **80・443** … Webの閲覧と証明書の取得に必要
- **22** … SSH接続。**消すとサーバーに入れなくなります**
- 送信元は「すべて許可」で正しいです。閲覧者を限定するのはアプリのログインの役目です

> 万一22番を消してしまっても、コントロールパネルの**コンソール機能**は
> パケットフィルタの影響を受けないため、そこから修正できます。

サーバー内の `ufw` は**無効のまま**にしています。通信制御をパケットフィルタに一本化し、
「どちらで止まっているのか分からない」状態を避けるためです。

---

## 3. アプリを置く

### 3-1. 置き場所と実行環境

```bash
sudo mkdir -p /opt/keiba && sudo chown $USER:$USER /opt/keiba
cd /opt/keiba && python3 -m venv .venv
.venv/bin/pip install fastapi uvicorn
```

導入されるのは `fastapi` `uvicorn` とその依存だけです（14個・数MB）。
**pandas・numpy は入れません。**採点をサーバーで行わないためで、
`score_horse_v3.py` が無くても動くようフォールバックを用意してあります。

### 3-2. ファイルを送る

**このPCで実行**します。

```bash
scp -r app run_new.py ubuntu@49.212.183.192:/opt/keiba/
```

`run_new.py` は会場名の対応表のために必要です（標準ライブラリだけで動きます）。

### 3-3. 開催回・発走時刻の控えを作る

一覧に出る「第2回2日目」「15:30」は `race.db` から取っています。
サーバーには `race.db` を置けないので、**必要な分だけJSONに書き出して**持っていきます。

```bash
python app/tools/export_kaisai.py
```

`app/data/kaisai_cache.json`（約23KB）ができます。
**この作成は同期ツールが毎回自動で行う**ので、普段は意識する必要はありません。
これが無い場合は、開催回・発走時刻が表示されないだけで、一覧そのものは表示されます。

---

## 4. 常時起動するようにする

```bash
sudo tee /etc/systemd/system/keiba.service > /dev/null <<'EOF'
[Unit]
Description=Keiba dashboard (public)
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/keiba
Environment=KEIBA_PUBLIC=1
ExecStart=/opt/keiba/.venv/bin/uvicorn app.backend.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload && sudo systemctl enable --now keiba
```

> **`KEIBA_PUBLIC=1` が公開モードの目印です。**
> これが付いていると、ログインが必須になり、**管理・検証の機能はそもそも読み込まれません**。
> 画面から隠しているのではなく、サーバー上にコードとして存在しない状態になります。

`--host 127.0.0.1` は、外からuvicornに直接繋げないようにするためです。
外部との通信はすべて次のCaddyが受けます。

動作確認：

```bash
curl -I http://127.0.0.1:8000/login
```

`HTTP/1.1 200 OK` が返れば、アプリは動いています。

---

## 5. HTTPS（Caddy）

### 5-1. ドメインを向ける

ドメイン側のDNSに、**Aレコード**を2つ登録します。

| ホスト名 | 種別 | 値 |
|---|---|---|
| （空欄＝ドメイン自体） | A | `49.212.183.192` |
| `www` | A | `49.212.183.192` |

さくらのドメインで取得した場合、ネームサーバーは既定で
`ns1.dns.ne.jp` / `ns2.dns.ne.jp` に設定済みなので、**追加の指定は不要**です。

反映を確認：

```bash
nslookup oz-king-keiba.com 8.8.8.8
```

### 5-2. Caddyを入れる

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

### 5-3. 設定

```bash
sudo tee /etc/caddy/Caddyfile > /dev/null <<'EOF'
oz-king-keiba.com, www.oz-king-keiba.com {
	reverse_proxy 127.0.0.1:8000
	encode gzip zstd
}
EOF
sudo systemctl enable --now caddy
sudo systemctl restart caddy
```

証明書（Let's Encrypt）は**自動で取得・更新**されます。手作業は不要です。
`encode gzip zstd` は、HTMLを圧縮して送るための指定です（回線の細いスマホで効きます）。

> 証明書の取得に失敗する場合、原因はほぼ次の2つです。
> ① パケットフィルタで80番が開いていない ② DNSがまだ反映されていない
> Caddyは60秒ごとに自動で再挑戦するので、原因を直せば放置で取得されます。

---

## 6. 招待する（**サーバー上で実行します**）

> ### ⚠️ このPCで発行しても機能しません
> 利用者データ（`users.json` / `invites.json`）は、**アプリが動いているサーバー側**にあります。
> このPCで発行した招待をサーバーは知らないため、招待された方はログインできません。
>
> 同期ツールもこれらのファイルを送りません。**送るべきでもありません** —
> 利用者がサーバー上で設定したパスワードを、このPCの古い内容で上書きしてしまうためです。

サーバーにSSHで入ってから実行します。

```bash
cd /opt/keiba && .venv/bin/python app/tools/user_admin.py invite \
  --memo "山田さん" --base https://oz-king-keiba.com
```

表示されたURLを、本人にだけ直接お渡しください。

- **1回だけ使えます**（有効7日）
- 本人がIDとパスワードを決めます。**あなたにもパスワードは分かりません**（ハッシュしか保存しません）
- 誤送信・期限切れなら取り消して発行し直せます

その他の操作（すべてサーバー上で）：

```bash
cd /opt/keiba && .venv/bin/python app/tools/user_admin.py invites
```

| コマンド | 内容 |
|---|---|
| `invites` | 発行済みの招待の一覧 |
| `revoke <トークン>` | 未使用の招待を取り消す |
| `list` | 登録済みの利用者の一覧 |
| `remove <ID>` | 利用者を削除（即時無効） |

パスワードを忘れた方には、`remove` してから `invite` で作り直してもらいます。
同じIDを取り直すこともできます。

---

## 7. 更新を反映する

いつもどおりこのPCで採点・生成したあと、**1回だけ実行**します。

```bash
python app/tools/sync_to_server.py --check
```

```bash
python app/tools/sync_to_server.py
```

初回のみ、接続先を `app/data/server.json` に書きます（gitには入れません）。

```json
{"host": "49.212.183.192", "user": "ubuntu", "path": "/opt/keiba", "port": 22}
```

同期ツールは次のことを自動で行います。**手作業は上の1コマンドだけです。**

1. `export_kaisai.py` を実行して開催回・発走時刻の控えを作り直す
2. サーバーと**中身を突き合わせ、変わったファイルだけ**を送る
3. メモ馬を統合する（下記）

### 送るもの

| ファイル | 役割 |
|---|---|
| `*_pred.html` / `*_review.html` | ダッシュボード本体 |
| `horses_data_*.json` | **レース一覧の元。これが無いと一覧に出ません** |
| `baba_manual.json` | 馬場データ |
| `app/data/kaisai_cache.json` | 開催回・発走時刻 |

初回は約147MBですが、2回目以降は**変わった分だけ**なので数秒で終わります。
（`--check` を付けると、今回何件送るかだけを確認できます。）

### メモ馬の扱い（重要）

メモは**2箇所で書き換わります**。

- **このPC**：回顧を作ると次走注目馬が自動で登録される
- **サーバー**：外出先のご自身や招待した方が本文を書く

そのまま上書きすると、どちらかの更新が消えます。同期ツールは統合したうえで、
**結果を両側へ書き戻します**（外出先で書いたメモがこのPCでも読めます）。
判定は「馬名＋元レースの日付＋R」で行い、次の規則で本文を選びます。

| | 採用するもの |
|---|---|
| サーバーに本文がある | **サーバー**（外出先で書いた内容を守る） |
| サーバーが空で、PCに本文がある | **PC**（未同期の下書きを守る） |
| 両方に本文があって食い違う | サーバー。**件数と馬名を画面に表示します** |
| サーバーに無い登録 | 追加する |

**片方が空のときに上書きしないので、統合で本文が消えることはありません。**
書き込み前に、サーバー側は `.bak`、このPC側は `_archive` へ退避します。

### 注目レースは同期しません

注目レースは**利用者ごと**に持っています（他の方の印は見えません）。
それぞれの手元で完結するため、同期の対象外です。

---

## 8. サーバーの権限について

構築中は作業のためパスワードなしで何でも実行できる状態にしていましたが、**運用開始時に外しました**。
現在パスワードなしで実行できるのは、次の5コマンドだけです。

```
/etc/sudoers.d/90-keiba-ops
    systemctl restart / start / stop   keiba
    systemctl restart / reload         caddy
```

- 状態確認（`systemctl status`）とログ閲覧（`journalctl`）は**元々sudo不要**なので含めていません
- それ以外の管理操作は、`ubuntu` のパスワードを入力すれば実行できます（sudoグループ所属のため）
- この範囲に絞ることで、SSH鍵が漏れた場合の被害を「アプリの再起動」までに抑えています

---

## 9. 困ったとき

| 症状 | 確認すること |
|---|---|
| 画面が出ない | `systemctl status keiba`（sudo不要） |
| 鍵マークが出ない | `systemctl status caddy` / パケットフィルタの80番 |
| 外から繋がらない | **まずパケットフィルタ**。サーバー内のufwではありません |
| 一覧は出るが中身が古い | このPCで `sync_to_server.py` を実行 |
| 新しいレースが一覧に出ない | 同上。`horses_data_*.json` が送られると出ます |
| 開催回・発走時刻が出ない | 同上（同期ツールが自動で作り直します） |
| ログインできない | サーバー上で `user_admin.py list` に登録があるか |
| 5分待たされる | パスワードを5回間違えると5分ロックされます |
| 動作記録を見たい | `journalctl -u keiba -n 100`（sudo不要） |
| 再起動したい | `sudo systemctl restart keiba` |

外から届いているかを、**このPCから**確かめる方法：

```bash
curl -I https://oz-king-keiba.com/login
```

`HTTP/2 200` が返れば正常です。

---

## 補足：サーバーに管理機能はありません

公開モードでは、管理・検証のAPIを**そもそも読み込みません**。
URLを直接叩いても届きません（画面から隠しているのではありません）。

採点・公開・JV-Link更新・検証は、**このPCでのみ**行えます。

---

## 補足：Ubuntu 24.04 のサポート期限

標準サポートは2029年4月までです。それまでに新しいLTSへ移行します。
このアプリはOSに依存する部分が少ない（Python標準＋FastAPIのみ）ため、
移行は「新しいサーバーを立てて2〜7章をなぞり、同期し直す」だけで済みます。
