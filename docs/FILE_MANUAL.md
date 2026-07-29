# FILE_MANUAL — ファイル配置マニュアル

ルート: `C:\Users\r-ito\keiba-dashboard\`
方針: **中核スクリプト/バッチ/恒久データ/ドキュメントはルート直下維持**（.batがパス参照するため移動しない）。
日付別の中間・出力ファイルは `_archive/` へ退避（`cleanup_archive.bat` がホワイトリスト方式で退避。削除はユーザー判断）。

---

## 1. 中核スクリプト（本体・維持）
| ファイル | 役割 |
|---|---|
| `run_new.py` | パイプライン制御（input/走査→採点→pred/review→公開→done移動） |
| `jv_export.py` | race.db → TARGET互換CSV（出馬表/過去走/坂路/ウッド/レース結果＋払戻/脚質、RT_フォールバック） |
| `score_horse_v3.py` | 16因子採点（地方馬/P3/P4/順位予想） |
| `build_dashboard_v3.py` | 予想ダッシュボードHTML生成（EVシミュレータ/買い目提案） |
| `build_review.py` | 回顧ダッシュボードHTML生成（的中/精度/コーナー通過/脚質） |
| `result_loader.py` | 結果CSV/Excel/HTML統一ロード＋ペース指標補完 |
| `bet_recon.py` | 買い目再構築・券種別結果照合（回収/期待値） |
| `baseline_time.py` | 独自基準タイム/馬場差/クラス判定/場コード |
| `payout_parser.py` | HTML払戻パーサ |
| `predict_select.py` | 会場/レース対話選択（エクスポート） |
| `smartrc_fetch.py` | SmartRC取得 |
| `check_results.py` | 結果取得状況(NL_/RT_)確認 |
| `run_new` 補助: `register_memo_from_reviews.py` | 回顧HTMLから次走注目メモ抽出 |

## 2. バッチ（運用・維持）
| バッチ | 役割 |
|---|---|
| `run_predict_select.bat` | ①更新＋会場/レース選択＋エクスポート |
| `run_predict_dash.bat` | ④採点→予想ダッシュボード（run_new.py） |
| `run_review_today.bat` | ⑤回顧生成（速報結果で再export→run_new --review --force） |
| `run_regen_today.bat` | 当日予想の全再生成（--force） |
| `run_update_manual.bat` / `jvlink_update.ps1` | JV-Link差分更新（-m exec） |
| `run_predict_data.bat` | ①の従来版（日付/場/R範囲プロンプト） |
| その他 `run_*.bat` | 分析・バックテスト用（factor/roi/rescore系）。アプリ化後は整理候補 |

## 3. 恒久データ・設定（維持）
| ファイル | 内容 |
|---|---|
| `baba_manual.json` / `baba_manual.example.json` | 当日馬場手動入力（日付→会場→良/稍重/重/不良＋天候/クッション/含水率） |
| `memo_horses.json` | メモ馬（次走注目） |
| `course_bias.json` / `course_tenkai_bias.json` / `course_times_full_new.json` | コース特性・基準タイムDB（採点入力） |
| `factor_rows.jsonl` / `factor_rows_p3.jsonl` / `factor_rows_cal.jsonl` | 5年因子データ（精度/検証用・大） |
| `payouts_cache.jsonl` / `racemeta_cache.jsonl` / `roi_rows.jsonl` | バックテストキャッシュ |
| `*_10y_win_utf8.csv` / `all_venues_10y_win.csv` / `waku_summary_*.txt` | 10年枠/コース集計（参考） |
| `競馬勉強会_コース解説テキスト_定量化.xlsx` | コース特徴の定量化ソース |
| `setting.xml` / `setting_setup15.xml` | JVLinkToSQLite設定 |
| `requirements.txt` / `db_schema.txt` | 依存/スキーマ |
| `shared_urls.txt` | 公開URLログ |

## 4. ドキュメント
| 場所 | 内容 |
|---|---|
| `CLAUDE.md`(root) | プロジェクト知識（Claude Code用メモリ） |
| `docs/APP_BUILD_METAPROMPT.md` | アプリ構築メタプロンプト |
| `docs/BACKLOG.md` | 未着手課題 |
| `docs/RULES_AND_NOTES.md` | 共通ルール・注意事項 |
| `docs/FILE_MANUAL.md` | 本ファイル |
| `docs/SKILLS_PLAN.md` | skill構成案 |
| `スコア項目台帳.md` | 16因子の精査台帳（採点自動化の基盤） |
| `ライブ予想_運用手順.md` | 当日予想/回顧の運用手順 |
| `モデル検証_総括_20260723.md` | 妙味検証の総括（市場に勝てない結論） |
| `JV-Link移行_*.md` / `JV移行_検証結果_*.md` / `TARGET_EXPORT_SPEC.md` | JV移行の設計・検証・仕様 |
| `JV-Link自動更新_セットアップ手順.md` | 差分更新セットアップ |
| その他 `*_report.md` / `HANDOFF*.md` / `AUDIT*.md` 等 | 過去の分析レポート（履歴）。`docs/reports/` へ整理候補 |

## 5. 作業領域（維持）
| 場所 | 内容 |
|---|---|
| `input/` | 当日エクスポートCSVの受け皿 |
| `input/done/` | pred/review完了後の移動先 |
| `jv_out/` | JV出力の一時領域 |

## 6. 退避対象（`_archive/` へ / `cleanup_archive.bat`）
※ 再生成可能な日付別の中間・出力。削除はユーザー判断。直近日(最新開催)は残す運用も可。
- `baba_YYYYMMDD_*.json`（自動取得馬場キャッシュ。真の入力は `baba_manual.json`）… 約328
- `horses_data_YYYYMMDD_*.json`（採点出力・再生成可）… 約327
- `scores_YYYYMMDD_*.csv`（採点スコア・再生成可）… 約327
- `smartrc_YYYYMMDD_*.json`（過去分。直近は残す）… 約326
- `haraimodoshi_YYYYMMDD_*.json`（払戻キャッシュ・再生成可）… 約184
- `*_pred.html` / `*_review.html`（生成済ダッシュボード。Pages公開済。ローカルは退避可）… 約610
- 単発分析レポート `*_report.md`、一時 `git_result.txt` 等
- **保護（退避しない）**: セクション1-5の全ファイル、`baba_manual.json`、`memo_horses.json`、`*.jsonl`、`course_*.json`、`setting*.xml`。

> 目安: ルート540MB。退避で大幅削減。真に不要なら `_archive/` をユーザーが削除。
