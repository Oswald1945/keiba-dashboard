# 新セッション開始用プロンプト

以下をそのままコワークの最初のメッセージにコピー＆ペーストしてください。

---

## ▼ コピー用プロンプト ▼

```
競馬予想ダッシュボードシステムの開発を継続したいです。
引継ぎ資料を読んで状況を把握してから作業を開始してください。

【引継ぎ資料】
C:\Users\r-ito\keiba-dashboard\HANDOVER.md

【プロジェクト概要】
- ローカルフォルダ: C:\Users\r-ito\keiba-dashboard\
- GitHub Pages: https://oswald1945.github.io/keiba-dashboard/
- JRAレースの予想・回顧HTMLダッシュボードを自動生成するPythonシステム

【主要スクリプト】
- score_horse_v3.py    : スコアリングエンジン（18因子）
- build_dashboard_v3.py: 予想HTML生成（EVシミュレーター付き）
- build_review.py      : 回顧HTML生成
- run_new.py           : メインオーケストレーター（生成→git push）
- fetch_baba.py        : 馬場情報取得
- resample_test.py     : done/フォルダからの再生成ツール

【よく使うコマンド】
  python run_new.py                    # 予想生成
  python run_new.py --review           # 回顧生成
  python run_new.py --force            # 強制再生成
  python resample_test.py --date YYYYMMDD  # 特定日を再生成

【メモ馬管理】
https://oswald1945.github.io/keiba-dashboard/memo_horses.html

今回やりたいこと:
[ここに具体的な依頼内容を書いてください]
```

---

## よくある依頼パターン（テンプレート）

### パターンA: 予想ダッシュボード生成
```
input/フォルダにCSVを配置しました。
予想ダッシュボードを生成してGitHub Pagesに公開してください。
```

### パターンB: 回顧ダッシュボード生成
```
20260607のレース結果CSVをinput/フォルダに配置しました。
回顧ダッシュボードを生成してGitHub Pagesに公開してください。
```

### パターンC: スコアリング改修
```
score_horse_v3.pyの○○補正を修正したいです。
詳細: [修正内容]
```

### パターンD: UI改修
```
build_dashboard_v3.pyのUIを修正したいです。
詳細: [修正内容]
```

### パターンE: 過去レースの再生成
```
done/フォルダにある20260607のレースを再生成したいです。
python resample_test.py --date 20260607 を実行してください。
```

---

## 注意事項（引継ぎ先への申し送り）

1. **ファイル編集後は必ず行数確認** - 大きなPythonファイルはトランケーションが起きやすい
   ```bash
   wc -l score_horse_v3.py build_dashboard_v3.py
   ```

2. **会場コードは run_new.py と fetch_baba.py の両方を確認** - 片方だけ直すとバグる

3. **EV simulator のデバッグ** - `_userOdds` 初期化は `computeEV` 関数の内部にある

4. **WAKU_BG定数** - `build_dashboard_v3.py` のメインJSスコープで定義済み（関数外）

5. **git pushは run_new.py が自動で行う** - 手動でgit操作は不要
