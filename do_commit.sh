#!/bin/bash
cd /c/Users/r-ito/keiba-dashboard
rm -f .git/index.lock
echo "[1] lock removed"
git add -A
echo "[2] add done"
git -c user.email="jrock.b.b.express@gmail.com" -c user.name="kuroame" commit -m "feat: time relaxation, kai-day bias, training floor, smartrc E coeff"
echo "[3] commit done"
git push
echo "[4] push done"
