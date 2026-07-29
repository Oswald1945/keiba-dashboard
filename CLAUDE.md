# CLAUDE.md — 競馬予想/回顧ダッシュボード プロジェクトメモリ

> このファイルは Claude Code が起動時に読むプロジェクト共通知識です。ここに書いた前提・規約・パイプラインは全作業で有効。詳細な設計/課題/ルールは `docs/` を参照。

## 0. このプロジェクトは何か
JRA競馬の **予想ダッシュボード** と **回顧ダッシュボード** を自動生成し GitHub Pages に公開する仕組み。
データ源は JRA-VAN DataLab（JV-Link）を `JVLinkToSQLite` で SQLite 化した `race.db`。
ユーザー（くろあめ / 伊藤涼平）は **非エンジニア**。バッチ(.bat)ダブルクリック運用が前提。回答は日本語・簡潔に。

## 1. 最重要の事実（判断の土台）
- **モデルは市場に妙味では勝てない**（5年・10+アプローチで検証済）。単勝EV・三連系オーバーレイ・条件スライス・重み再最適化のいずれも控除率を超えない。軸複勝率の上限≈50-51%＜1番人気62%。
  → よって **スコアの目的は「妙味(ROI)」ではなく「的中精度(順位相関・軸複勝率)」の向上**。買い判定/期待値は別レイヤー（ユーザーがオッズ手入力してEV判定する道具）。
- 詳細は `モデル検証_総括_20260723.md`、因子の精査は `スコア項目台帳.md`。
- **新馬・未勝利は精度検証外**（採点対象から外す運用推奨）。

## 2. 中核パイプライン（この4本＋制御が本体）
```
race.db ──jv_export.py──▶ input/{出馬表,過去走,坂路,ウッド,レース結果}_YYYYMMDD_{場R}.csv
                              │
run_new.py が input/ をスキャンし各レースごとに:
  score_horse_v3.py ─▶ horses_data.json (+ scores_*.csv)   # 採点(16因子)
  build_dashboard_v3.py ─▶ {race_id}_pred.html             # 予想ダッシュボード
  build_review.py       ─▶ {race_id}_review.html           # 回顧(結果あり時/--review)
  → GitHub Pages へ push、URLを shared_urls.txt に記録
```
補助: `result_loader.py`(結果CSV/HTML統一ロード), `bet_recon.py`(買い目再構築・券種別照合), `baseline_time.py`(独自基準タイム/馬場差/クラス判定), `payout_parser.py`(HTML払戻), `predict_select.py`(会場/レース対話選択), `smartrc_fetch.py`(SmartRC取得), `check_results.py`(結果取得状況NL/RT確認)。

## 3. race.db（JVLinkToSQLite）の要点
- パス: `C:\Users\r-ito\JVLinkToSQLite\race.db`（**サンドボックス未マウント**。Claudeは直接読めない→ユーザーがバッチ実行）。
- テーブル命名: `<配信タイミング>_<レコード種別>_<サフィックス>`。**蓄積系=`NL_`／速報系=`RT_`**。
  - 主要: `NL_RA_RACE`(レース詳細), `NL_SE_RACE_UMA`(馬毎), `NL_HR_PAY`(払戻), `NL_UM_UMA`(馬マスタ), `NL_HC_HANRO`(坂路), `NL_WC_WOOD`(ウッド)。速報は `RT_RA_RACE/RT_SE_RACE_UMA/RT_HR_PAY`。
- モード: `jvlinktosqlite -m exec`(蓄積系差分＋有効なら速報系), `-m event`, `-m init`, `-m defaultsetting`。設定は `setting.xml`。
- **JV-Linkキー確認**: データ取得前に JV-Link設定を起動→OK（怠ると RC=-303 利用キー空値）。
- **当日結果は速報系(RT_)から**: 蓄積系(NL_)の確定成績は翌日以降。当日回顧は setting.xml の `JVRealTimeDataUpdateSetting/IsEnabled=true` ＋ 対象開催日を設定して `-m exec`。0B15/0B14/0B13 が確定成績。RA記録の `LapTime0..24 / HaronTimeS3(前3F) / HaronTimeL3(後3F)` がラップ由来（速報に載らない場合あり→回顧側で「速報回顧では取得不可」表示、翌日NLで実値化）。
- JRA場コード 01-10（01札幌 04新潟 05東京 06中山 07中京 08京都 09阪神 10小倉…）。**30-55は地方(NAR)**。ローマ字略: sp/hk/fk/ng/tk/nk/ck/ky/hn/kk。

## 4. スコアリング（16因子）と重要ロジック
因子: 最高出力/クラス/時計/コース特徴/トラックバイアス/斤量/距離/コース適性/臨戦/人気補正/騎手/馬体重/継続/着差/クラス適応/上がり(+SmartRC評価)。各因子の内容・課題・改善点は **`スコア項目台帳.md`** に集約（自動化の基盤資料）。
採用済み改善: **P3=相対上がり**(ペース中立化), **P4=成績重み付きコース適性)**。P1(絶対devブレンド)は rank保存で軸を変えられず不採用。
- **順位予想**: 総合スコアの降順rank。ただし **地方実績のみ馬はJRA採点馬の後ろに回す**（下記）。
- **地方(NAR)馬**: 過去走の`場所`がJRA10場以外＝地方。JRA出走歴があれば**JRA走のみで採点**、無ければ地方走で採点し `地方実績のみ=True`。地方戦は**格を最低クラス(未勝利相当)に丸める**(`class_norm_eff`)。ダッシュボードは `📎参考(地方のみ)` バッジ・EVから除外・買い目軸から除外。
- **買い目軸 ≠ スコア1位**: 勝率cap(1/オッズ×MR, MR=3.0)適用後の勝率1位が軸。人気薄の過剰評価を抑制。ダッシュボードに注記表示。

## 5. 馬場・SmartRC・メモ（当日入力系）
- `baba_manual.json`: 日付→会場→{芝,ダート,天候,クッション値,含水率_芝,含水率_ダート}。run_newは自動取得より優先。値は 良/稍重/重/不良。
- SmartRC: `smartrc_{race_id}.json`（手動 or `smartrc_fetch.py`）。評価A-E＋推定人気。
- `memo_horses.json`: 次走注目メモ馬。回顧HTMLから自動抽出して追記（`register_memo_from_reviews.py` / run_new内）。

## 6. 運用フロー（詳細は `ライブ予想_運用手順.md`）
```
0. JV-Linkキー確認(設定→OK)
① run_predict_select.bat  … race.db更新＋会場/レース選択＋input/へエクスポート
② SmartRC 取得(手動 or 自動)
③ baba_manual.json に当日馬場を記入（チャットで伝えれば記入運用可）
④ run_predict_dash.bat (run_new.py) … 採点→pred.html→Pages公開
⑤ レース確定後: 速報系(RT_)取得 → run_review_today.bat (jv_export再+run_new --review) … 回顧公開
```

## 7. 環境・制約（厳守）
- `.bat` は **ASCII専用**（rem含め日本語禁止＝CP932文字化け）。CSV出力は cp932。
- サンドボックス: `mcp__workspace__bash` は独立実行(cwd継承なし)・timeout最大45s・**race.dbはマウント外**。Windowsパス⇄マウントパスは環境説明を参照。
- 破壊的操作(物理削除)はClaudeは行わない。移動(_archive/)か、ユーザーにスクリプト実行を促す。
- **コード変更前に必ず内容を説明して承認を得る**（共通ルール。`docs/RULES_AND_NOTES.md`）。

## 8. GitHub Pages 公開
- リポジトリの `keiba-dashboard`、公開URL `https://oswald1945.github.io/keiba-dashboard/{race_id}_pred.html` / `_review.html`。
- run_new が生成後に自動 push、URLを `shared_urls.txt` に追記。CRLF警告は無害。
