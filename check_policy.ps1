Write-Host "===== セキュリティポリシー診断 ====="
# Smart App Control（スマートアプリコントロール）の状態
$sac = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' -ErrorAction SilentlyContinue).VerifiedAndReputablePolicyState
switch ("$sac") {
  '0' { $s = 'OFF（無効）' }
  '1' { $s = 'ON（有効・強制）★これが原因の可能性大' }
  '2' { $s = 'Evaluation（評価モード）★これが原因の可能性大' }
  ''  { $s = '項目なし（この環境では未使用）' }
  default { $s = "不明値: $sac" }
}
Write-Host "Smart App Control : $s"

# 有効なウイルス対策製品
Write-Host "--- ウイルス対策製品 ---"
try {
  Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct -ErrorAction Stop |
    ForEach-Object { Write-Host ("  {0}" -f $_.displayName) }
} catch { Write-Host "  取得できませんでした" }

# 対象DLLがまだ存在するか（隔離されていないか）
$dll = 'C:\Users\r-ito\JVLinkToSQLite\Urasandesu.JVLinkToSQLite.Basis.dll'
Write-Host "--- 対象DLLの存在 ---"
if (Test-Path $dll) { Write-Host "  存在します（隔離はされていない）" } else { Write-Host "  ★見つかりません（セキュリティソフトに隔離された可能性）" }
