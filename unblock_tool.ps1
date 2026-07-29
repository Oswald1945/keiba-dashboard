$d = 'C:\Users\r-ito\JVLinkToSQLite'
$files = Get-ChildItem -LiteralPath $d -Recurse -File
$before = 0
foreach ($x in $files) {
    if (Get-Item -LiteralPath $x.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue) { $before++ }
}
Write-Host ("対象ファイル数: {0} / うちブロック(MotW)あり: {1}" -f $files.Count, $before)

# 解除（2通りで確実に）
$files | Unblock-File -ErrorAction SilentlyContinue
foreach ($x in $files) {
    Remove-Item -LiteralPath $x.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue
}

$after = 0
foreach ($x in $files) {
    if (Get-Item -LiteralPath $x.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue) { $after++ }
}
Write-Host ("解除後の残りブロック: {0}" -f $after)
if ($after -eq 0) {
    Write-Host "OK: すべて解除しました。次に run_update_manual.bat を再実行してください。"
} else {
    Write-Host "注意: ブロックが残っています。Smart App Control 等ポリシーの可能性があります。"
}
