# SKILLS_PLAN — skill構成案

Claude Code / Cowork の **skill** として切り出す提案。各skillは `SKILL.md`（説明＋手順）＋補助スクリプトで構成。
目的: 反復運用（取得→採点→公開→回顧→検証）を名前付きで呼べるようにし、手順の属人化を排除する。

## 想定skill一覧
| skill名 | 役割 | 主な参照/呼び出し | トリガ例 |
|---|---|---|---|
| `keiba-predict` | 当日予想の生成（更新→会場/R選択→採点→公開） | `run_predict_select.bat`→SmartRC/馬場→`run_predict_dash.bat` | 「今日の予想を作って」 |
| `keiba-review` | レース確定後の回顧生成（速報RT_取得→再export→--review） | 速報系有効化→`check_results.py`→`run_review_today.bat` | 「昨日の回顧を出して」 |
| `keiba-baba` | 馬場情報の登録（画像/テキスト→`baba_manual.json`） | 画像読み取り→検証→JSON追記 | 「馬場を登録して」 |
| `keiba-memo` | メモ馬の管理（追加/一覧/回顧から自動抽出） | `memo_horses.json` / `register_memo_from_reviews.py` | 「メモ馬を見せて/追加して」 |
| `keiba-accuracy` | 的中精度検証（期間/会場/クラス/馬場別の集計） | `validate_accuracy.py` / `build_review.py` 指標 | 「精度を検証して」 |
| `keiba-value` | 買い判定の妙味検証（券種別的中/回収・確定配当照合） | `bet_recon.py` / `roi_backtest.py` | 「妙味を検証して」 |
| `keiba-data-update` | JV-Link差分更新＋取得状況確認 | `run_update_manual.bat` / `check_results.py` | 「データを更新して」 |

## 各skillの設計指針
- **前提の明示**: 「JV-Linkキー確認(設定→OK)」「race.dbはローカル」「.batはASCII」を各SKILL.md冒頭に。
- **非エンジニア向け**: 手順は「どのバッチをダブルクリック」まで具体化。専門語は最小限。
- **共通ルール参照**: `RULES_AND_NOTES.md` の遵守（コード変更前確認・削除しない・馬場は確認）。
- **入出力の固定**: 生成物パス・命名（`{race_id}_pred.html` / `_review.html`、`baba_manual.json` 形式）を明記。
- **失敗時フォールバック**: SmartRC自動取得失敗→手動、速報未配信→取得不可表示＋翌日確定、を各skillに記載。

## パッケージング（将来）
- 上記を1つの **プラグイン（marketplace配布可）** にまとめる案: `keiba-dashboard-plugin`（skills＋必要なら簡易MCP）。
- アプリ化(APP_BUILD_METAPROMPT)後は、skillは「管理APIを叩く薄いラッパ」に置き換え可能。

## 優先度
1. `keiba-predict` / `keiba-review`（日次の中核）
2. `keiba-baba` / `keiba-memo`（入力・管理）
3. `keiba-accuracy` / `keiba-value` / `keiba-data-update`（検証・保守）
