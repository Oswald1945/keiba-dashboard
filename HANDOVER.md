# 競馬ダッシュボード プロジェクト引継ぎ資料
作成日: 2026-06-08

---

## プロジェクト概要

**GitHubリポジトリ:** `oswald1945/keiba-dashboard`  
**GitHub Pages URL:** `https://oswald1945.github.io/keiba-dashboard/`  
**ローカルフォルダ:** `C:\Users\r-ito\keiba-dashboard\`  
**メモ馬管理URL:** `https://oswald1945.github.io/keiba-dashboard/memo_horses.html`

JRAの競馬レースについて、CSVデータから予想ダッシュボードHTMLと回顧ダッシュボードHTMLを自動生成し、GitHub Pagesに公開するシステム。

---

## 主要ファイル構成

| ファイル | 役割 |
|---|---|
| `score_horse_v3.py` | 18因子スコアリングエンジン（馬ごとの得点計算） |
| `build_dashboard_v3.py` | 予想ダッシュボードHTML生成（EV simulator付き） |
| `build_review.py` | 回顧ダッシュボードHTML生成 |
| `run_new.py` | メインオーケストレーター（input/スキャン→生成→git push） |
| `fetch_baba.py` | JRA馬場情報取得スクリプト |
| `resample_test.py` | done/フォルダからの再生成ツール |
| `smartrc_fetch.py` | SmartRC評価データ取得 |
| `register_memo_from_reviews.py` | 回顧からメモ馬を自動登録 |

---

## ワークフロー

### 通常フロー
```
input/{種別}_{日付}_{レースID}.csv を配置
    ↓
python run_new.py          # 予想生成 → GitHub push
python run_new.py --review # 回顧生成 → GitHub push
```

### 再生成フロー（done/フォルダから）
```
python resample_test.py --date 20260607   # 特定日を全再生成
python resample_test.py --race 20260607_hs11  # 特定レースを再生成
python resample_test.py --all             # 全レース再生成
python resample_test.py --list            # 利用可能レース一覧
```

### 強制再生成オプション
```
python run_new.py --force          # pred生成済でも強制再生成
python run_new.py --review --force # review生成済でも強制再生成
```

---

## ファイル命名規則

### inputファイル
```
{種別}_{日付}_{レースID}.{csv|xlsx}

種別: 過去走 / 出馬表 / 坂路 / ウッド / レース結果 / レースデータ
日付: YYYYMMDD
レースID例: hs7, hs11, tk12, kt10
```

### 出力HTML
```
pred_{日付}_{レースID}.html         # 予想ダッシュボード
{日付}_{venue}{R}R_C{n}_{レース名}_review.html  # 回顧ダッシュボード
```

---

## 会場コードマッピング（_VENUE_CODE_MAP）

run_new.py と fetch_baba.py の両方に定義されている。

```python
# JRA
'TK','TO' → 東京
'CB','NA','NS' → 中山
'HN','HS' → 阪神      ← HS追加済み（以前はHSが欠落していてエラー）
'KT','KY' → 京都
'CK','CC' → 中京
'NK','NG','NI' → 新潟
'HK' → 函館
'SM','SP' → 札幌
'FK' → 福島
'KO','KK' → 小倉
# NAR（地方競馬）
'OI' → 大井, 'KW' → 川崎, 'SK','FB' → 船橋
'UW','UR' → 浦和, 'KZ' → 金沢, 'MO' → 盛岡
'MZ' → 水沢, 'FY' → 福山, 'KM' → 高知
'SA' → 佐賀, 'HI' → 姫路, 'EN' → 園田
```

---

## スコアリング概要（score_horse_v3.py）

### スコア構成（満点目安 ≈ 100pt）
| 因子 | 配点 | 説明 |
|---|---|---|
| 最高出力 | 30pt | 出馬表TGX 偏差値化 |
| クラス補正 | 25pt | クラス重み × 着順スコア |
| タイム偏差 | 20pt | コース平均タイムとの差（馬場補正込み） |
| 展開適性 | ±15pt | 脚質 × 想定ペース |
| コース適性 | ±10pt | コース特性類似度 |
| 斤量補正 | 0/-1pt | 57kg以上で-1pt |
| 距離補正 | -2〜+2pt | 400m以上の延長ペナルティ |
| 臨戦補正 | -4〜+1pt | 出走間隔7段階 |
| 騎手実績 | ±2pt | Bayesian収縮付き |
| 馬体重補正 | 0/-1pt | 大幅増減で減点 |
| 継続騎乗 | 0/+1pt | 同騎手継続で加点 |
| 前走着差 | -2〜+1pt | 着差の大小 |
| SmartRC評価補正 | -4.5〜+4.5pt | 過去5走の有利不利加重平均 |
| 上がりpts | ±3pt | 上がり3F偏差値 |

### SmartRC評価係数
```python
SMARTRC_HYOKA_PTS = {
    'A': +4.5,  # 大きく不利 → 実力過小評価
    'B': +2.5,  # やや不利
    'C':  0.0,  # 中立
    'D': -2.5,  # やや有利に恵まれた
    'E': -4.5,  # 大きく有利
}
```

---

## 既知の修正済みバグ・注意点

### 1. `WAKU_BG is not defined` ReferenceError（修正済み）
- **原因:** `WAKU_BG`定数がinner functionスコープ外で未定義
- **修正:** `build_dashboard_v3.py` のメインJSスコープ（関数定義より前）に`const WAKU_BG = {...}`を追加

### 2. HS（阪神）会場コード欠落（修正済み）
- **原因:** `run_new.py`と`fetch_baba.py`の会場コードマップに`HS`が未登録
- **修正:** 両ファイルに`'HS': '阪神'`を追加（`HN`と並記）

### 3. EV初期値がフラットにならない問題（修正済み）
- **原因:** `_userOdds`初期化が`computeEV`関数外で行われ、デフォルト値でEVが計算されていた
- **修正:** `_userOdds`初期化を`computeEV`関数内部の先頭に移動

### 4. ファイルトランケーション（繰り返し発生しやすい）
- **現象:** 大きなPythonファイルを編集後に末尾が切れる
- **対処:** 編集後に`wc -l`で行数確認 + 末尾`if __name__ == '__main__':`の有無チェック
- 補完スクリプト: `repair_score_horse.py`（過去に使用）

### 5. Nullバイト混入（修正済み）
- **原因:** 不明（ファイル保存時の問題）
- **修正:** `data.replace(b'\x00', b'')`でnullバイトを除去してからパース

---

## 現在の状態（2026-06-08時点）

### 最新の予想ダッシュボード（2026-06-07 阪神・東京）

**📍 阪神（hs）**
- R7: https://oswald1945.github.io/keiba-dashboard/pred_20260607_hs7.html
- R8: https://oswald1945.github.io/keiba-dashboard/pred_20260607_hs8.html
- R9: https://oswald1945.github.io/keiba-dashboard/pred_20260607_hs9.html
- R10: https://oswald1945.github.io/keiba-dashboard/pred_20260607_hs10.html
- R11: https://oswald1945.github.io/keiba-dashboard/pred_20260607_hs11.html
- R12: https://oswald1945.github.io/keiba-dashboard/pred_20260607_hs12.html

**📍 東京（tk）**
- R7: https://oswald1945.github.io/keiba-dashboard/pred_20260607_tk7.html
- R8: https://oswald1945.github.io/keiba-dashboard/pred_20260607_tk8.html
- R9: https://oswald1945.github.io/keiba-dashboard/pred_20260607_tk9.html
- R10: https://oswald1945.github.io/keiba-dashboard/pred_20260607_tk10.html
- R11: https://oswald1945.github.io/keiba-dashboard/pred_20260607_tk11.html
- R12: https://oswald1945.github.io/keiba-dashboard/pred_20260607_tk12.html

### 最新の回顧ダッシュボード（2026-06-07）
- HN7R: https://oswald1945.github.io/keiba-dashboard/20260607_HN7R_C1_review.html
- HN8R: https://oswald1945.github.io/keiba-dashboard/20260607_HN8R_C1_review.html
- HN9R: https://oswald1945.github.io/keiba-dashboard/20260607_HN9R_C2_SumotoTokubetsu_review.html
- HN10R〜HN12R: 同様にGitHub Pages公開済み
- TK7R〜TK12R: 同様にGitHub Pages公開済み（安田記念含む）

### doneフォルダ状況
- `input/done/` に蓄積中（2022〜2026年のレースデータ）

---

## よく使うコマンド

```bash
# 作業ディレクトリ
cd C:\Users\r-ito\keiba-dashboard

# 予想生成
python run_new.py

# 回顧生成
python run_new.py --review

# 強制再生成（予想）
python run_new.py --force

# 特定日の全レース再生成
python resample_test.py --date 20260607

# 利用可能レース一覧
python resample_test.py --list

# 馬場情報取得（例: 東京 2026-06-14）
python fetch_baba.py --venue 東京 --date 20260614 --out baba_TK.json

# メモ馬管理URL
https://oswald1945.github.io/keiba-dashboard/memo_horses.html
```

---

## 今後の改善候補（未着手）

1. **スコア精度向上** - コース適性・距離適性の更なる細分化
2. **複数日付の回顧一括生成** - `resample_test.py`への機能追加
3. **SmartRC評価の重み調整** - 現状の±4.5ptが最適かの検証
4. **馬場状態の予想への反映精度向上** - 雨量→馬場劣化の推定精度改善
5. **UI改善** - ダッシュボードのモバイル表示最適化

---

## 新セッション開始用プロンプト

→ 別ファイル `HANDOVER_PROMPT.md` を参照
