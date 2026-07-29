<#
  JVLinkToSQLite 日次差分更新タスクを Windows タスクスケジューラに登録する。
  ------------------------------------------------------------------
  実行方法: PowerShell で本スクリプトを実行（管理者権限は不要。対話ユーザー
            自身のタスクとして登録するため）。
              powershell -NoProfile -ExecutionPolicy Bypass -File .\register_task.ps1
  仕様:
    - 毎日 $Time に jvlink_update.ps1（-m exec 差分更新）を実行。
    - ログオン中の対話セッションで実行（JV-Link/JV-LinkAgent の安定動作のため）。
    - PC起動漏れ時は次回起動後にキャッチアップ（StartWhenAvailable）。
    - 既に実行中なら新規起動しない（多重実行防止。ラッパー側Mutexと二重の安全）。
    - 手動実行(run_update_manual.bat / jvlink_update.ps1)はこの登録と無関係に常時可能。
#>
[CmdletBinding()]
param(
    [string]$TaskName   = 'JVLinkToSQLite_DailyDiff',
    [string]$ScriptPath = 'C:\Users\r-ito\keiba-dashboard\jvlink_update.ps1',
    [string]$Time       = '05:00'
)

if (-not (Test-Path $ScriptPath)) {
    throw "jvlink_update.ps1 が見つかりません: $ScriptPath  （-ScriptPath で正しいパスを指定してください）"
}

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""

$trigger = New-ScheduledTaskTrigger -Daily -At $Time

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)

# 現在のユーザーの対話セッションで実行（パスワード保存不要）
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action   $action `
    -Trigger  $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host "登録完了: タスク '$TaskName'（毎日 $Time 実行）"
Write-Host "テスト実行 : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "状態確認   : Get-ScheduledTaskInfo -TaskName '$TaskName'"
Write-Host "削除       : Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
