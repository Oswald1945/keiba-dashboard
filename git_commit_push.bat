@echo off
chcp 65001 > nul
cd /d "C:\Users\r-ito\keiba-dashboard"

echo [1/4] index.lock を削除中...
if exist ".git\index.lock" (
    del /f ".git\index.lock"
    echo       削除しました
) else (
    echo       index.lock なし（スキップ）
)

echo [2/4] git add -A ...
git add -A

echo [3/4] git commit ...
git -c user.email="jrock.b.b.express@gmail.com" -c user.name="くろあめ" commit -m "feat: 4改善実装 1時計pts上限緩和 2開催週バイアス 3調教フロア 4SmartRC E係数改善"

echo [4/4] git push ...
git push

echo.
echo 完了しました！このウィンドウを閉じてください。
pause
