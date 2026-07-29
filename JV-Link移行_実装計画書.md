# JV-Link データ取得 自動化 実装計画書

作成日: 2026-07-21
対象: keiba-dashboard 予測パイプラインのデータ取得自動化（TARGET 手動書き出しの置換）

---

## 1. 目的とゴール

TARGET の手動 CSV 書き出し（①出馬表・過去走・調教、⑤レース結果）を、JV-Link 経由の自動取得へ置換する。副次的に JV-Data 相当の自前 SQLite 履歴 DB を保有し、⑦分析・バックテストの基盤とする。最終的に週次サイクル（予測 → 結果 → レビュー）の完全自動化に近づける。

非ゴール: ②SmartRC・③クッション値/含水率・天気予報は JV-Link では取得できないため本計画の対象外（別ルート継続、7章）。

---

## 2. 結論（採用方式）

**Route B: JVLinkToSQLite（OSS/CLI）で JV-Data → SQLite を取込 + 自前 Python 変換層** を採用する。

採用理由:

- JV-Link は 32bit COM（CLSID 2AB1774D…）。64bit Python から直叩きは不可で、32bit Python 化か DLL Surrogate のレジストリ細工が必要（＝Route A の最大コスト）。JVLinkToSQLite は .NET アプリ内部でこの問題を解決済みで、出力の SQLite はビット数非依存 → 既存 64bit Python からそのまま読める。
- 必要データを全網羅（3章）。CLI `-m exec` + 差分更新（最新読み出しポイント記録）で headless 自動化に適合。
- 利用キーは既存 JV-Link 設定を再利用（契約中・キーありのため初期 GUI 設定も原則不要）。

Route A（自前 pywin32）はフォールバック。JVLinkToSQLite のスキーマ/更新粒度が要件に合わなくなった場合にのみ検討する。

---

## 3. データ網羅性（JVLinkToSQLite で確認済み）

必要データはすべて対応テーブルが存在する（NL_ = 蓄積系 / RT_ = 速報系）。

| パイプライン用途 | JV-Data レコード | JVLinkToSQLite テーブル |
| --- | --- | --- |
| ①出馬表 / 過去走（核） | SE | NL_SE_RACE_UMA（当日: RT_SE_RACE_UMA） |
| レース詳細 | RA | NL_RA_RACE（当日: RT_RA_RACE） |
| ⑤結果・払戻 | HR | NL_HR_PAY（当日: RT_HR_PAY） |
| ①坂路調教 | HC | NL_HC_HANRO |
| ①ウッド調教 | WC | NL_WC_WOOD |
| 馬/騎手/調教師マスタ | UM / KS / CH | NL_UM_UMA / NL_KS_KISYU / NL_CH_CHOKYOSI |
| オッズ（単複〜三連単） | O1〜O6 | NL_O1〜O6（当日: RT_O1〜O6） |
| 票数 | H1 / H6 | NL_H1_* / NL_H6_*（当日: RT_*） |
| 馬体重（速報） | WH | RT_WH_BATAIJYU |
| 天候・馬場状態（速報） | WE | RT_WE_WEATHER |
| マイニング予想 | DM / TM | NL/RT_DM_INFO・TM_INFO |
| 開催スケジュール | YS | NL_YS_SCHEDULE |

→ ①⑤に必要な全データに加え、オッズ・馬体重・天候馬場・JRA-VAN マイニング予想まで取得可能。マイニング（DM/TM）は ②SmartRC の代替/補助候補になり得る。

---

## 4. アーキテクチャ

```
[JRA-VAN Data Lab]
      │ JV-Link (32bit COM)
      ▼
[JVLinkToSQLite (.NET CLI)]  ──►  race.db (SQLite, ビット数非依存)
                                        │
        [jv_export.py (自前 / 64bit Python)]  ◄──┘
                                        │
        既存 input/ 形式の CSV/JSON を生成
                                        ▼
        既存 run_new.py → score_horse_v3.py 以降は無改修
```

2 プロセス疎結合構成。取込（JVLinkToSQLite）と変換（Python）を SQLite でつなぐ。取込側が落ちても変換側は last-good の DB で動ける。

---

## 5. 取得モードと運用

| 局面 | モード / 方法 | 内容 |
| --- | --- | --- |
| 初回セットアップ | `-m exec`（setting.xml で範囲指定） | 直近 N 年（例 3〜5 年）・必要種別のみ取得 |
| 日次差分（蓄積系） | `-m exec` を定期実行 | 最新読み出しポイント記録により新規分のみ取得 |
| 当日速報（馬体重・馬場確定・実オッズ） | Event（速報）モード | 前日夜予測は蓄積系で充足。直前情報を使う場合に併用 |

CLI 要点（確認済み）:

- モード: `Exec` / `Event` / `Init` / `About` / `DefaultSetting`
- `-d, --datasource`（既定 `race.db`）: SQLite パス
- `-s, --setting`（既定 `setting.xml`）: 取得対象種別・期間の動作設定
- `-t, --throttlesize`（既定 100）: JV-Link 過負荷エラー時に増やす
- `-u, --skipslastmodifiedupdate`: 最新読み出しポイント更新をスキップ
- `-l, --loglevel` / ExitCode 仕様 → スケジューラでの成否判定に利用
- `-m init`: 利用キー設定 GUI。**既存 JV-Link にキー設定済みなら不要**

---

## 6. 変換層（jv_export.py）設計

責務: `race.db` の正規化テーブルを、既存パイプラインが食う入力形式（`出馬表_<rid>.csv`、過去走、調教 等）へ変換する。

実装方針: レース単位で `SE + RA + UM + HC/WC`（必要に応じ `DM/TM`）を JOIN し、TARGET CSV 相当の列へ写像する。

最重要タスク: **列マッピング表の確定**。TARGET 書き出し CSV のヘッダ ⇔ JVLinkToSQLite テーブル列 を対応付け、PoC で 1 レース分を突合して差分ゼロを確認する。文字コードは既存 CSV（SJIS 想定）に合わせる。

---

## 7. JV-Link で埋まらない部分（別ルート継続）

- **②SmartRC 推定人気/評価**: 第三者サービス。既存 `smartrc_fetch.py` を継続。マイニング（DM/TM）が近い代替になり得るため、フェーズ 3 で比較検証する。
- **③クッション値・含水率**: JV-Data 非提供（JRA 馬場ページで前日昼過ぎ／当日 9:30 頃公表）。既存 `fetch_baba.py` を継続。JV-Link の RT_WE_WEATHER は馬場状態（良/稍/重/不良）・天候のみ。
- **天気予報**: 気象 API 等で別取得（既存踏襲）。

---

## 8. リスクと対策

| リスク | 対策 |
| --- | --- |
| 32bit COM 問題 | JVLinkToSQLite 採用で回避。Route A 選択時のみ DLL Surrogate 対応 |
| ライセンス（GPL-3.0） | 別プロセス CLI として実行し SQLite を読むだけなら Python 側へ GPL は伝播しない。改変再配布時のみ GPL 義務が生じる |
| JV-Data の二次利用規約 | 公開物は派生予想のため通常問題化しにくいが、生データ再配布は制限。コミュニティに商用利用問い合わせ導線あり、念のため確認 |
| JV-Link 過負荷エラー | `throttlesize` を増やす |
| 初回取得時間 | 取得年数を絞る。マシン性能依存（数十分〜） |
| ツール保守性 | star 少だが JRA-VAN 公式掲載・2026 年も更新継続。停止時は EveryDB/Route A へ移行可（SQLite・JV-Data 相当のため乗換容易） |

---

## 9. PoC 手順（最短検証）

前提: JV-Link 本体インストール済み・利用キー設定済み（契約中・キーあり）。

1. JVLinkToSQLiteArtifact を DL・展開し `C:\JVLinkToSQLite` に配置。`.\jvlinktosqlite` でヘルプ表示を確認。
2. （キー未設定の場合のみ）`.\jvlinktosqlite -m init` でキー設定。
3. `setting.xml` を「直近 1 年・必要種別（RA/SE/HR/UM/HC/WC/O*/H*）」に設定。
4. `.\jvlinktosqlite -m exec -d race.db` を実行し `race.db` 生成を確認。
5. Python から `race.db` を開き、直近 1 レースの SE/RA/UM/HC/WC を取り出す。
6. 同レースの TARGET 書き出し CSV と列突合 → `jv_export.py` の列マッピングを確定。
7. `jv_export.py` で `input/` 相当 CSV を生成 → 既存 `run_new.py` を回し、既存出力と一致することを確認。

**検証ゲート**: 「JV-Link 由来の入力で `run_new.py` が既存と同一スコアを再現」できれば置換成立。

---

## 10. 段階導入ロードマップ

| フェーズ | 内容 |
| --- | --- |
| 0 検証 | 上記 PoC。1 レースで置換成立を確認 |
| 1 ①⑤置換 | 蓄積系日次 `-m exec` をタスクスケジューラ化 + jv_export で全レース供給。TARGET 手動書き出し廃止 |
| 2 当日速報 | Event モードで馬体重・馬場確定・実オッズを取込み、直前更新に対応 |
| 3 ⑦基盤 | 取得年数を拡張し履歴 DB をバックテストに活用。マイニング(DM/TM) と SmartRC を比較検証 |

---

## 11. 未確定・次アクション

- [ ] JV-Link 本体のインストール／COM 登録状況の確認（希望あれば画面で確認可）
- [ ] TARGET 書き出し CSV の実ヘッダ取得（列マッピングの入力データ）
- [ ] setting.xml の対象種別・取得年数の確定
- [ ] 実行マシン／スケジューラ（Windows タスクスケジューラ）方針の確定

---

## 参考ソース

- JVLinkToSQLite（GitHub / Wiki）: https://github.com/urasandesu/JVLinkToSQLite
- JVLinkToSQLite Getting Started: https://github.com/urasandesu/JVLinkToSQLite/wiki/Getting-Started
- JVLinkToSQLite テーブル仕様: https://github.com/urasandesu/JVLinkToSQLite/wiki/Table-Spec
- JV-Link 32bit と Python(64bit): https://zenn.dev/hraps/articles/fb6ce9b1151ced
- JRA-VAN 開発者コミュニティ「過去40年分のデータダウンロード時間」: https://developer.jra-van.jp/t/topic/766
- JRA 馬場情報（クッション値・含水率）: https://www.jra.go.jp/keiba/baba/cushion/
