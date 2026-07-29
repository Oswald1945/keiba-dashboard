<#
  JVLinkToSQLite 差分更新ラッパー（手動実行 / タスクスケジューラ 両対応）
  ------------------------------------------------------------------
  - `-m exec` は「最新読み出し開始ポイント日時」を記録するため、実行ごとに
    前回以降の差分のみを取得して race.db を最新化する。
  - 手動実行:   PowerShell から `.\jvlink_update.ps1` を実行、または
                同梱の run_update_manual.bat をダブルクリック。
  - 自動実行:   register_task.ps1 で登録した日次タスクが本スクリプトを呼ぶ。
  - 二重起動防止(Mutex)により、手動とスケジューラが同時に走っても衝突しない。

  戻り値(ExitCode)は JVLinkToSQLite の終了コードをそのまま返す:
    0=正常 / -1〜-1000=JV-Link関係(例:-504 メンテ中=一時要因) /
    -2001=ラッパー未知エラー / -3001=引数不正 / -3002=注意点あり / -3003=JV-Link以外の例外
#>
[CmdletBinding()]
param(
    # 環境に合わせて既定値を調整（またはコマンドラインで上書き）
    [string]$ToolDir      = 'C:\Users\r-ito\JVLinkToSQLite',
    [string]$DbPath           = 'C:\Users\r-ito\JVLinkToSQLite\race.db',
    [string]$Setting      = 'C:\Users\r-ito\JVLinkToSQLite\setting.xml',
    [string]$LogDir       = 'C:\Users\r-ito\JVLinkToSQLite\logs',
    [int]   $ThrottleSize = 100,
    # JVLinkToSQLite のモード。通常は差分更新の exec。将来 event 等に切替可能。
    [ValidateSet('exec','event')]
    [string]$Mode         = 'exec'
)

$ErrorActionPreference = 'Stop'
$exe = Join-Path $ToolDir 'jvlinktosqlite.exe'

# ── ログ準備 ─────────────────────────────────────────────
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
$stamp   = Get-Date -Format 'yyyyMMdd_HHmmss'
$logFile = Join-Path $LogDir "jvlink_$stamp.log"
function Log([string]$msg) {
    ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg) |
        Tee-Object -FilePath $logFile -Append
}

# ── 二重起動防止（手動 × スケジューラの衝突回避）──────────
$created = $false
$mutex = New-Object System.Threading.Mutex($true, 'Global\JVLinkToSQLiteUpdate', [ref]$created)
if (-not $created) {
    Log 'WARN 別の更新処理が実行中のため、今回はスキップしました。'
    exit 0
}

try {
    # ダウンロード由来のブロック(Mark of the Web)を解除。.NETアセンブリのロード拒否(0x800711C7)対策。
    Get-ChildItem -LiteralPath $ToolDir -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue
    if (-not (Test-Path $exe))     { Log "ERROR 実行ファイルが見つかりません: $exe"; exit 1 }
    if (-not (Test-Path $Setting)) { Log "ERROR setting.xml が見つかりません: $Setting"; exit 1 }

    Log "START jvlinktosqlite -m $Mode  (db=$DbPath, setting=$Setting, throttle=$ThrottleSize)"
    & $exe -m $Mode -d $DbPath -s $Setting -t $ThrottleSize *>&1 | Tee-Object -FilePath $logFile -Append
    $code = $LASTEXITCODE
    Log "END exitcode=$code"

    switch ($code) {
        0     { Log 'OK 正常終了（差分を反映しました）。' }
        -3001 { Log 'ERROR 引数解析不可(-3001)。スクリプトの引数指定を確認してください。' }
        -3002 { Log 'WARN 注意点あり終了(-3002)。setting.xml 等を確認してください。' }
        -3003 { Log 'ERROR JV-Link以外の例外(-3003)。上のログを保存し必要なら作者へ報告を。' }
        -2001 { Log 'ERROR ラッパー検知の未知エラー(-2001)。上のログを保存してください。' }
        default {
            if ($code -le -1 -and $code -ge -1000) {
                Log "WARN JV-Linkエラー($code)。サーバーメンテナンス(-504)等の一時要因の可能性が高く、次回実行で回復することが多いです。"
            } else {
                Log "WARN 未分類の終了コード($code)。"
            }
        }
    }
    exit $code
}
finally {
    $mutex.ReleaseMutex() | Out-Null
    $mutex.Dispose()
    # 30日より古いログを掃除
    Get-ChildItem $LogDir -Filter 'jvlink_*.log' -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
        Remove-Item -Force -ErrorAction SilentlyContinue
}
