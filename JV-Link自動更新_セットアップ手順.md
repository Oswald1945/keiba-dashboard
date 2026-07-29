# JV-Link（JVLinkToSQLite）差分更新 自動化 セットアップ手順

作成日: 2026-07-21
目的: 履歴DB `race.db` を、**手動実行・スケジューラ実行の両対応**で最新化する。
関連: `JV-Link移行_実装計画書.md` / `JV-Link移行_列マッピングと変換層設計.md`

このフォルダに同梱の3ファイルで構成:

| ファイル | 役割 |
| --- | --- |
| `jvlink_update.ps1` | 差分更新の**実体**（手動・自動の両方がこれを呼ぶ）。二重起動防止・終了コード判定・ログ出力付き |
| `run_update_manual.bat` | 手動実行用ランチャー（ダブルクリックで `jvlink_update.ps1` を起動） |
| `register_task.ps1` | 日次差分更新をタスクスケジューラに登録 |

---

## 前提（確認済み）

- JV-Link 4.9.0 インストール済み（32bit）・**利用キー登録済み** → JVLinkToSQLite の `-m init` は不要。
- Python / PowerShell / タスクスケジューラ 完備。

---

## STEP 1. JVLinkToSQLite の導入（初回のみ・手作業）

> 外部exeの取得・実行のため、この初回導入だけはご自身の操作になります。

1. GitHub リリースから最新版を取得: https://github.com/urasandesu/JVLinkToSQLite/releases
2. 自己解凍ファイルを実行して展開し、フォルダを **`C:\Users\r-ito\JVLinkToSQLite`** にリネーム／配置。
   （別の場所に置く場合は、後述の各スクリプトのパス引数を合わせて変更）
3. 動作確認: そのフォルダで PowerShell を開き `.\jvlinktosqlite` を実行 → ヘルプが表示されればOK。

## STEP 2. 設定ファイルの配置と初回取得

設定ファイルは用意済み（`keiba-dashboard` 内）。編集不要でコピーするだけ。

- **`setting.xml`**: 日々の差分更新用（通常更新ON・過去オッズ除外・セットアップ/速報OFF）。
- **`setting_setup15.xml`**: 15年一括取得用（セットアップON、RACE/坂路/血統/開催日程/マイニング等を 2011-07-21 から取得）。※ウッド調教はJRA-VAN提供開始が2021-07-27のため約5年分。

手順:

1. 上記2ファイルを **`C:\Users\r-ito\JVLinkToSQLite`** にコピー。
2. **動作確認（短時間）**: `keiba-dashboard` の `run_update_manual.bat` をダブルクリック。過去約1年を取得し `race.db` が作られる。終了コード 0 なら成功。
3. **15年一括取得（初回のみ・長時間）**: `keiba-dashboard` の `run_setup15_once.bat` をダブルクリック。過去15年を取り込む（数十分〜数時間。中断しても再実行で続行）。
4. 以降は STEP 4 のスケジューラが `setting.xml` で毎日差分更新する。

## STEP 3. 自動化スクリプトの配置

- `jvlink_update.ps1` / `run_update_manual.bat` / `register_task.ps1` は既に **`C:\Users\r-ito\keiba-dashboard`**（プロジェクトフォルダ）にあります。**移動・コピー不要**です。
- スクリプトはツール本体（`C:\Users\r-ito\JVLinkToSQLite`）をパス指定で参照します。ツールを別の場所に置いた場合のみ、`jvlink_update.ps1` の `-ToolDir/-Db/-Setting/-LogDir` を実際のパスに合わせてください。

## STEP 4. スケジューラ登録

```powershell
cd C:\Users\r-ito\keiba-dashboard
powershell -NoProfile -ExecutionPolicy Bypass -File .\register_task.ps1
```
- 既定は **毎日 05:00**。時刻を変えるなら `-Time '06:30'`、タスク名は `-TaskName` で変更可。
- ログオン中の対話セッションで実行（パスワード保存不要・JV-Link安定動作のため）。
- PC起動漏れ時は次回起動後に自動キャッチアップ。

---

## 使い方

### 手動実行（いつでも可）

- `run_update_manual.bat`（`C:\Users\r-ito\keiba-dashboard` 内）を**ダブルクリック**、または
  ```powershell
  cd C:\Users\r-ito\keiba-dashboard
  .\jvlink_update.ps1
  ```
- スケジューラ実行と**同じ実体**を呼ぶため挙動は同一。実行中に手動起動しても二重起動防止でスキップされ安全。

### 自動実行（差分更新）

- 登録後は毎日自動で `-m exec`（差分）を実行。手動での操作は不要。
- テスト起動: `Start-ScheduledTask -TaskName 'JVLinkToSQLite_DailyDiff'`
- 実行状況: `Get-ScheduledTaskInfo -TaskName 'JVLinkToSQLite_DailyDiff'`

### ログ

- `C:\Users\r-ito\JVLinkToSQLite\logs\jvlink_YYYYMMDD_HHmmss.log` に毎回出力（30日で自動削除）。

---

## 終了コード（トラブル判断の目安）

| コード | 意味 | 対処 |
| --- | --- | --- |
| 0 | 正常終了（差分反映） | — |
| -1〜-1000 | JV-Link関係エラー（例 -504=サーバーメンテ中） | **一時要因が多い**。次回実行で回復することが大半。頻発時のみ調査 |
| -2001 | ラッパー検知の未知エラー | ログ保存。DB破損等の可能性 |
| -3001 | 引数解析不可 | スクリプトの引数指定を確認 |
| -3002 | 注意点あり終了 | setting.xml 等を確認 |
| -3003 | JV-Link以外の例外 | ログ保存。必要なら作者へ報告 |

JV-Link のエラーコード詳細: https://developer.jra-van.jp/t/topic/822

### -303（利用キーが空値）が出た場合

利用キーが登録済みに見えても JVOpen が -303 になることがある。原因は「JV-Link がサーバー認証して作る内部サービスキーが未作成」。対処:

1. スタート → `JV-Link設定` を開く（**管理者では開かない**）。
2. 利用キー（5つの値）が入っていることを確認し、**「OK」を押す**（キャンセルでは認証されない）。OK押下でサーバー認証が走りサービスキーが作られる。
3. その後、通常実行で取得できる。

**重要: 本ツールは管理者権限で実行しない。** 利用キーは通常ユーザーのプロファイルに保存されるため、管理者で実行すると別プロファイルとなりキーが空扱い（全種別 -303）になる。スケジューラ登録（register_task.ps1）も通常権限（Limited）で登録済み。

---

## メモ

- `race.db` は今後 `jv_export.py`（変換層）と `baseline_time.py`（独自基準タイム算出）が参照する。既定では `C:\Users\r-ito\JVLinkToSQLite\race.db`。パイプラインから参照しやすい場所に置きたい場合は STEP 2/3 のパスを合わせて調整する。
- `race.db` は大きくなるため、Git 管理対象に含めない（`.gitignore` 推奨）。
- 当日速報（馬体重・馬場確定・実オッズ）が必要になった段階で、別途 `event` モードの運用を追加する（本手順は蓄積系の差分更新が対象）。
