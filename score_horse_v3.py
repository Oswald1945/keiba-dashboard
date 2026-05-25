"""
競馬予想スコア計算ロジック v3
対象: 東京 芝1600m 18頭立て

スコア構成 (最大値合計 ≈ 100pt):
  最高出力    30pt  : 出馬表TGX（条件別+時間減衰）の偏差値化
  クラス補正  25pt  : クラス重み × 着順スコア 加重平均
  タイム偏差  20pt  : コース平均タイムとの差 (A-1 馬場補正込み)
  展開適性   ±15pt  : 脚質 × 想定ペース
  A-2 斤量補正 0/-1pt: 57kg以上で-1pt（重斤量のみ）
  A-3 距離補正 -2〜+2pt: 400m以上距離延長ペナルティ + TGX高指数ボーナス
  A-4 コース適性 ±10pt: コース特性類似度（コーナー区分追加）
  A-5 臨戦補正 -4〜+1pt: 出走間隔7段階（長期休養ペナルティ緩和版）
  A-7 騎手実績 ±2pt : Bayesian収縮付き騎手スコア
  ④  馬体重補正 0/-1pt: 大幅増減で減点
  ⑥  継続騎乗  0/+1pt: 同騎手継続で加点
  ⑧  前走着差  -2〜+1pt: 着差の大小で評価
  SmartRC評価補正 -4.5〜+4.5pt: 過去5走の有利不利評価加重平均(A/B=不利→上方修正, D/E=有利→下方修正)
  ※廃止: A-6 PCI補正、C-3 調教評価（坂路/ウッドLap1は表示のみ）
"""

import pandas as pd
import numpy as np
import json
import unicodedata
from datetime import date, timedelta
from collections import defaultdict

# ─────────────────────────────────────────────────────────────────────────────
# SmartRC 連携
# ─────────────────────────────────────────────────────────────────────────────

# 評価列 補正係数（緩やか設定 / 将来的に強化可能）
# A/B = 不利を受けた → 実力は結果より高い → 上方修正
# C   = 中立
# D/E = 有利を受けた → 結果は過大評価の可能性 → 下方修正
SMARTRC_HYOKA_PTS = {
    'A': +4.5,   # 大きく不利を受けた → 実力過小評価 → 強めに上方修正
    'B': +2.5,   # やや不利
    'C':  0.0,   # 中立
    'D': -2.5,   # やや有利な展開に恵まれた → 下方修正
    'E': -4.5,   # 大きく有利 → 強めに下方修正
}


def load_smartrc_data(json_path: str) -> dict:
    """
    smartrc_{race_id}.json を読み込み、馬名 → フィールド辞書 を返す。
    キー: hname (馬名文字列)
    """
    import pathlib
    p = pathlib.Path(json_path)
    if not p.exists():
        print(f"  [SmartRC] JSONが見つかりません: {json_path}")
        return {}
    with open(p, encoding='utf-8') as f:
        obj = json.load(f)
    horses = obj.get('horses', {})
    print(f"  [SmartRC] {len(horses)}頭分のデータを読み込みました ({p.name})")
    return horses


def calc_smartrc_pts(hyoka: str) -> float:
    """評価列(h1_fr_baba等)の1値をスコア補正値に変換する（加重平均の部品）。"""
    if not hyoka:
        return 0.0
    return SMARTRC_HYOKA_PTS.get(str(hyoka).strip().upper(), 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────────────────────────────────────
TARGET_COURSE = "東京芝1600m"
TARGET_DIST   = 1600
RACE_DATE     = date(2026, 5, 10)

CLASS_WEIGHTS = {
    'G1': 2.2, 'G2': 1.7, 'G3': 1.5,
    'OP': 1.3, 'L': 1.3,
    '3勝': 1.1, '2勝': 1.0, '1勝': 0.9,
    '未勝利': 0.7, '新馬': 0.7, '不明': 0.6,
}

# クラス序列（昇級戦判定用: 数値が大きいほど上位クラス）
CLASS_RANK = {
    'G1': 9, 'G2': 8, 'G3': 7,
    'OP': 6, 'L': 6,
    '3勝': 5, '2勝': 4, '1勝': 3,
    '未勝利': 2, '新馬': 1, '不明': 0,
}

# ─────────────────────────────────────────────────────────────────────────────
# A-4  コース特性データベース  (JRA 全開催場・全主要距離対応)
# 凡例: 直線=最終直線長(m), 1C距離=スタートから1コーナーまでの距離(m)
#       坂=最終直線の坂の急峻度(0=平坦,1=緩,2=急), 回り=進行方向, 洋芝=洋芝フラグ
# ─────────────────────────────────────────────────────────────────────────────
COURSE_FEATURES = {
    # ── 東京 (左回り / 芝直線526m / ダート直線502m / 坂なし) ──────────────
    "東京芝1400m":     {"直線": 526, "1C距離":  549, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 0},
    "東京芝1600m":     {"直線": 526, "1C距離":  349, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 0},
    "東京芝1800m":     {"直線": 526, "1C距離":  149, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 0},
    "東京芝2000m":     {"直線": 526, "1C距離":  619, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 0},
    "東京芝2300m":     {"直線": 526, "1C距離":  919, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 0},
    "東京芝2400m":     {"直線": 526, "1C距離":  719, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 0},
    "東京芝2500m":     {"直線": 526, "1C距離":  819, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 0},
    "東京芝3400m":     {"直線": 526, "1C距離": 1100, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 0},
    "東京ダート1300m":  {"直線": 502, "1C距離":  453, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 0},
    "東京ダート1400m":  {"直線": 502, "1C距離":  553, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 0},
    "東京ダート1600m":  {"直線": 502, "1C距離":  325, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 0},
    "東京ダート2100m":  {"直線": 502, "1C距離":  825, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 0},
    "東京ダート2400m":  {"直線": 502, "1C距離": 1025, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 0},

    # ── 中山 (右回り / 直線310m / 急坂あり) ─────────────────────────────
    "中山芝1200m":     {"直線": 310, "1C距離":  350, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 2},
    "中山芝1600m":     {"直線": 310, "1C距離":  296, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 2},
    "中山芝1800m":     {"直線": 310, "1C距離":  296, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 2},
    "中山芝2000m":     {"直線": 310, "1C距離":  400, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 2},
    "中山芝2200m":     {"直線": 310, "1C距離":  600, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 2},
    "中山芝2500m":     {"直線": 310, "1C距離":  800, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 2},
    "中山芝3600m":     {"直線": 310, "1C距離": 1300, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 2},
    "中山ダート1200m":  {"直線": 310, "1C距離":  350, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 2},
    "中山ダート1800m":  {"直線": 310, "1C距離":  350, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 2},
    "中山ダート2400m":  {"直線": 310, "1C距離":  800, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 2},

    # ── 阪神 (右回り / 外回り芝直線474m / 内回り芝直線356m / ダート直線352m / 急坂あり) ──
    # 注: 芝1200m・2000m・2200m・3000mは内回りのみ(JRA公式コース表より確認済)
    #     1C距離=「レース最初のコーナーまでの距離」(物理的な1Cとは異なる場合あり)
    #     1200m/1400m/3000m: スタートが向正面(S3), 最初のコーナー=物理3C
    #     2000m: スタートが正面直線(HS), 最初のコーナー=物理1C
    #     2200m: スタートが4C付近, 最初のコーナー=物理1C (4C+HS+F経由)
    #     検証: T3+S4+T4=585.5m固定 → 1200m:258+585.5+356.5=1200 / 3000m:369+585.5+356.5=1311=3000-1689
    "阪神芝1200m":     {"直線": 356, "1C距離":  258, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 1},  # 内回りのみ(向正面スタート, 最初のコーナー=3C)
    "阪神芝1200m内":   {"直線": 356, "1C距離":  258, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 1},
    "阪神芝1400m":     {"直線": 356, "1C距離":  440, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 1},  # 向正面スタート, 最初のコーナー=3C
    "阪神芝1600m":     {"直線": 474, "1C距離":  208, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 0},
    "阪神芝1800m":     {"直線": 474, "1C距離":  368, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 0},
    "阪神芝2000m":     {"直線": 356, "1C距離":  325, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 1},  # 内回りのみ(fallback), 正面直線スタート
    "阪神芝2000m内":   {"直線": 356, "1C距離":  325, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 1},
    "阪神芝2200m":     {"直線": 356, "1C距離":  525, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 1},  # 内回りのみ(fallback), 4C付近スタート
    "阪神芝2200m内":   {"直線": 356, "1C距離":  525, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 1},
    "阪神芝3000m":     {"直線": 356, "1C距離":  369, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 1},  # 内回りのみ(fallback), 向正面2C出口スタート
    "阪神芝3000m内":   {"直線": 356, "1C距離":  369, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 1},
    "阪神ダート1200m":  {"直線": 352, "1C距離":  100, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 1},
    "阪神ダート1400m":  {"直線": 352, "1C距離":  300, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 1},
    "阪神ダート1800m":  {"直線": 352, "1C距離":  200, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 1},
    "阪神ダート2000m":  {"直線": 352, "1C距離":  400, "坂": 2, "回り": "右", "洋芝": False, "コーナー": 1},

    # ── 京都 (右回り / 外回り芝直線404m / 内回り芝直線314m / ダート直線329m / 緩坂) ──
    # 注: 芝1200m=内回りのみ / 1400m・1600m=内外両用 / 1800m以上=外回りのみ / 2000m=内回りのみ
    "京都芝1200m":     {"直線": 314, "1C距離":  100, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 2},
    # 1400m 内/外（内=新馬・未勝利, 外=1勝以上）
    "京都芝1400m":     {"直線": 404, "1C距離":  220, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 0},  # 外回りと同値(fallback)
    "京都芝1400m内":   {"直線": 314, "1C距離":  200, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 2},
    "京都芝1400m外":   {"直線": 404, "1C距離":  220, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 0},
    # 1600m 内/外（内=1勝以下, 外=2勝以上）
    "京都芝1600m":     {"直線": 404, "1C距離":  420, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 0},  # 外回りと同値(fallback)
    "京都芝1600m内":   {"直線": 314, "1C距離":  400, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 2},
    "京都芝1600m外":   {"直線": 404, "1C距離":  420, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 0},
    "京都芝1800m":     {"直線": 404, "1C距離":  620, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 0},  # 外回りのみ
    # 2000m=内回りのみ(トラックコード=0, コーナー回数=4)。旧エントリ(直線404m)を修正
    "京都芝2000m":     {"直線": 314, "1C距離":  200, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 2},  # 内回りのみ(fallback)
    "京都芝2000m内":   {"直線": 314, "1C距離":  200, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 2},
    "京都芝2200m":     {"直線": 404, "1C距離":  820, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 0},  # 外回りのみ
    "京都芝2400m":     {"直線": 404, "1C距離": 1020, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 0},
    "京都芝3000m":     {"直線": 404, "1C距離": 1420, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 0},
    "京都芝3200m":     {"直線": 404, "1C距離": 1620, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 0},
    "京都ダート1200m":  {"直線": 329, "1C距離":  100, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 1},
    "京都ダート1400m":  {"直線": 329, "1C距離":  300, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 1},
    "京都ダート1800m":  {"直線": 329, "1C距離":  300, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 1},

    # ── 中京 (左回り / 直線413m / 急坂あり) ──────────────────────────────
    "中京芝1200m":     {"直線": 413, "1C距離":  100, "坂": 2, "回り": "左", "洋芝": False, "コーナー": 1},
    "中京芝1400m":     {"直線": 413, "1C距離":  452, "坂": 2, "回り": "左", "洋芝": False, "コーナー": 1},
    "中京芝1600m":     {"直線": 413, "1C距離":  252, "坂": 2, "回り": "左", "洋芝": False, "コーナー": 1},
    "中京芝2000m":     {"直線": 413, "1C距離":  452, "坂": 2, "回り": "左", "洋芝": False, "コーナー": 1},
    "中京ダート1200m":  {"直線": 410, "1C距離":  100, "坂": 2, "回り": "左", "洋芝": False, "コーナー": 1},
    "中京ダート1400m":  {"直線": 410, "1C距離":  400, "坂": 2, "回り": "左", "洋芝": False, "コーナー": 1},
    "中京ダート1800m":  {"直線": 410, "1C距離":  300, "坂": 2, "回り": "左", "洋芝": False, "コーナー": 1},
    "中京ダート1900m":  {"直線": 410, "1C距離":  400, "坂": 2, "回り": "左", "洋芝": False, "コーナー": 1},

    # ── 新潟 (左回り / 外回り芝直線659m / 内回り芝直線359m / ダート直線354m / 平坦) ──
    "新潟芝1000m":     {"直線":1000, "1C距離": 1000, "坂": 0, "回り": "直", "洋芝": False, "コーナー": 0},
    "新潟芝1200m":     {"直線": 359, "1C距離":  100, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 2},
    "新潟芝1400m":     {"直線": 359, "1C距離":  359, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 2},
    "新潟芝1600m":     {"直線": 659, "1C距離":  559, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 1},
    "新潟芝1800m":     {"直線": 659, "1C距離":  659, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 1},
    "新潟芝2000m":     {"直線": 659, "1C距離":  859, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 1},  # 外回りと同値(fallback)
    "新潟芝2000m内":   {"直線": 359, "1C距離":  400, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 2},
    "新潟芝2000m外":   {"直線": 659, "1C距離":  859, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 1},
    "新潟芝2200m":     {"直線": 659, "1C距離": 1059, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 1},
    "新潟芝2400m":     {"直線": 659, "1C距離": 1259, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 1},
    "新潟ダート1200m":  {"直線": 354, "1C距離":  100, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 2},
    "新潟ダート1800m":  {"直線": 354, "1C距離":  300, "坂": 0, "回り": "左", "洋芝": False, "コーナー": 2},

    # ── 福島 (右回り / 直線292m / 緩坂) ─────────────────────────────────
    "福島芝1200m":     {"直線": 292, "1C距離":  296, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 2},
    "福島芝1800m":     {"直線": 292, "1C距離":  296, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 2},
    "福島芝2000m":     {"直線": 292, "1C距離":  496, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 2},
    "福島ダート1150m":  {"直線": 295, "1C距離":  100, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 2},
    "福島ダート1700m":  {"直線": 295, "1C距離":  300, "坂": 1, "回り": "右", "洋芝": False, "コーナー": 2},

    # ── 小倉 (右回り / 直線293m / 平坦) ──────────────────────────────────
    "小倉芝1200m":     {"直線": 293, "1C距離":  100, "坂": 0, "回り": "右", "洋芝": False, "コーナー": 2},
    "小倉芝1800m":     {"直線": 293, "1C距離":  400, "坂": 0, "回り": "右", "洋芝": False, "コーナー": 2},
    "小倉芝2000m":     {"直線": 293, "1C距離":  600, "坂": 0, "回り": "右", "洋芝": False, "コーナー": 2},
    "小倉芝2600m":     {"直線": 293, "1C距離": 1200, "坂": 0, "回り": "右", "洋芝": False, "コーナー": 2},
    "小倉ダート1000m":  {"直線": 293, "1C距離":  100, "坂": 0, "回り": "右", "洋芝": False, "コーナー": 2},
    "小倉ダート1700m":  {"直線": 293, "1C距離":  300, "坂": 0, "回り": "右", "洋芝": False, "コーナー": 2},

    # ── 札幌 (右回り / 直線266m / 平坦 / 洋芝) ───────────────────────────
    "札幌芝1200m":     {"直線": 266, "1C距離":  100, "坂": 0, "回り": "右", "洋芝": True, "コーナー": 1},
    "札幌芝1500m":     {"直線": 266, "1C距離":  400, "坂": 0, "回り": "右", "洋芝": True, "コーナー": 1},
    "札幌芝1800m":     {"直線": 266, "1C距離":  100, "坂": 0, "回り": "右", "洋芝": True, "コーナー": 1},
    "札幌芝2000m":     {"直線": 266, "1C距離":  300, "坂": 0, "回り": "右", "洋芝": True, "コーナー": 1},
    "札幌芝2600m":     {"直線": 266, "1C距離":  900, "坂": 0, "回り": "右", "洋芝": True, "コーナー": 1},
    "札幌ダート1000m":  {"直線": 266, "1C距離":  100, "坂": 0, "回り": "右", "洋芝": False, "コーナー": 1},
    "札幌ダート1700m":  {"直線": 266, "1C距離":  300, "坂": 0, "回り": "右", "洋芝": False, "コーナー": 1},
    "札幌ダート2400m":  {"直線": 266, "1C距離":  900, "坂": 0, "回り": "右", "洋芝": False, "コーナー": 1},

    # ── 函館 (右回り / 直線262m / 平坦 / 洋芝) ───────────────────────────
    "函館芝1000m":     {"直線": 262, "1C距離":  100, "坂": 0, "回り": "右", "洋芝": True, "コーナー": 2},
    "函館芝1200m":     {"直線": 262, "1C距離":  100, "坂": 0, "回り": "右", "洋芝": True, "コーナー": 2},
    "函館芝1800m":     {"直線": 262, "1C距離":  100, "坂": 0, "回り": "右", "洋芝": True, "コーナー": 2},
    "函館芝2000m":     {"直線": 262, "1C距離":  300, "坂": 0, "回り": "右", "洋芝": True, "コーナー": 2},
    "函館芝2600m":     {"直線": 262, "1C距離":  900, "坂": 0, "回り": "右", "洋芝": True, "コーナー": 2},
    "函館ダート1000m":  {"直線": 262, "1C距離":  100, "坂": 0, "回り": "右", "洋芝": False, "コーナー": 2},
    "函館ダート1700m":  {"直線": 262, "1C距離":  300, "坂": 0, "回り": "右", "洋芝": False, "コーナー": 2},
    "函館ダート2400m":  {"直線": 262, "1C距離":  900, "坂": 0, "回り": "右", "洋芝": False, "コーナー": 2},
}

# ─────────────────────────────────────────────────────────────────────────────
# ユーティリティ関数
# ─────────────────────────────────────────────────────────────────────────────

def recency_weight(rank: int) -> float:
    """緩やかな指数減衰: 0.93^(rank-1)  rank1→1.0, rank5→0.75, rank10→0.52"""
    return max(0.5, 0.93 ** (rank - 1))


# ─────────────────────────────────────────────────────────────────────────────
# 最高出力pts 用ヘルパー（TGX列＋時間減衰）
# ─────────────────────────────────────────────────────────────────────────────

def get_tgx_col(surface: str, dist_m: float) -> str:
    """今走の芝/ダ・距離からTGX列名を返す"""
    is_turf = (surface == '芝')
    is_short = (dist_m <= 1700)
    if is_turf:
        return 'TGX芝短' if is_short else 'TGX芝中'
    else:
        return 'TGXダ短' if is_short else 'TGXダ中'


def calc_tgx_adjusted(horse_name: str, shutuba_df, sub: 'pd.DataFrame',
                       race_date: 'date', surface: str, dist_m: float) -> float:
    """
    出馬表のTGX値（補正タイムの条件別ベスト）を取得し、
    そのベストをマークした時期に応じた時間減衰を適用して返す。

    減衰テーブル（ピーク日からの経過月数）:
      0〜6ヶ月  → ×1.00
      6〜12ヶ月 → ×0.98
      12〜24ヶ月→ ×0.96
      24〜36ヶ月→ ×0.93
      36ヶ月超  → ×0.90
    """
    if shutuba_df is None:
        return None
    rows = shutuba_df[shutuba_df['馬名'] == horse_name]
    if rows.empty:
        return None

    tgx_col = get_tgx_col(surface, dist_m)
    raw = rows.iloc[0].get(tgx_col)
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        # 条件別TGXが無い場合はTGX直前で代替
        raw = rows.iloc[0].get('TGX直前')
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return None
    # 括弧付き値（例: "(  0)"）やスペースを除去してから変換
    if isinstance(raw, str):
        raw = raw.strip().lstrip('(').rstrip(')').strip()
    tgx_val = float(raw)
    if tgx_val <= 0:
        return None

    # ピーク日を過去走から特定（条件一致ランで補正タイムが最大の走）
    peak_months = None
    if not sub.empty and '補正タイム' in sub.columns:
        cond = sub.copy()
        is_turf = (surface == '芝')
        is_short = (dist_m <= 1700)
        if is_turf:
            cond = cond[cond['芝・ダ'] != 'ダ']
        else:
            cond = cond[cond['芝・ダ'] == 'ダ']
        dist_num = pd.to_numeric(cond['距離'], errors='coerce')
        if is_short:
            cond = cond[dist_num <= 1700]
        else:
            cond = cond[dist_num > 1700]
        cond = cond[pd.to_numeric(cond['補正タイム'], errors='coerce').notna()]
        if not cond.empty:
            best_idx = pd.to_numeric(cond['補正タイム'], errors='coerce').idxmax()
            best_row = cond.loc[best_idx]
            try:
                y = to_year4(best_row['年'])
                m = int(best_row['月'])
                d = int(best_row['日'])
                peak_months = (race_date - date(y, m, d)).days / 30.0
            except Exception:
                pass

    # 時間減衰適用（緩やか: 最大10%減）
    if peak_months is not None:
        if peak_months <= 6:
            decay = 1.00
        elif peak_months <= 12:
            decay = 0.98
        elif peak_months <= 24:
            decay = 0.96
        elif peak_months <= 36:
            decay = 0.93
        else:
            decay = 0.90
        tgx_val *= decay

    return tgx_val


def normalize_class(s) -> str:
    if pd.isna(s): return '不明'
    s = unicodedata.normalize('NFKC', str(s)).strip()
    if 'G1' in s or 'GⅠ' in s: return 'G1'
    if 'G2' in s or 'GⅡ' in s: return 'G2'
    if 'G3' in s or 'GⅢ' in s: return 'G3'
    if 'L' in s or 'OP' in s.upper() or 'オープン' in s: return 'OP'
    if '3勝' in s: return '3勝'
    if '2勝' in s: return '2勝'
    if '1勝' in s: return '1勝'
    if '未勝利' in s: return '未勝利'
    if '新馬' in s: return '新馬'
    return '不明'


def parse_time_str(t):
    if t is None or (isinstance(t, float) and np.isnan(t)): return np.nan
    s = str(t).strip().replace(':', '.').replace('．', '.').replace('：', '.')
    parts = s.split('.')
    if len(parts) == 3:
        m, sec, frac = parts
        return int(m) * 60 + int(sec) + int(frac) / 10 ** len(frac)
    if len(parts) == 2:
        try: return float(s)
        except: return np.nan
    return np.nan


def class_str_to_avg_key(class_name: str) -> str:
    mapping = {
        'G1': '重賞・OP', 'G2': '重賞・OP', 'G3': '重賞・OP',
        'OP': '重賞・OP', 'L': '重賞・OP',
        '3勝': '3勝', '2勝': '2勝', '1勝': '1勝',
        '未勝利': '未勝利', '新馬': '新馬',
    }
    return mapping.get(class_name, '2勝')


def course_key_from_row(row) -> str:
    """過去走レコードから course_key を生成。トラックコードで内/外を識別。"""
    loc   = row['場所']
    track = row['芝・ダ']
    dist  = int(row['距離'])
    base  = f"{loc}{'ダート' if track == 'ダ' else '芝'}{dist}m"
    if track != 'ダ':
        tcode = row.get('トラックコード', None)
        if pd.notna(tcode):
            tc = int(tcode)
            if tc == 0:
                candidate = base + '内'
            elif tc == 8:
                candidate = base + '外'
            else:
                candidate = base
            # COURSE_FEATURESにキーが存在する場合のみ内外サフィックスを付与
            if candidate in COURSE_FEATURES:
                return candidate
    return base


# ── 出馬表から内/外を判定するルックアップ (場所, 距離) → サフィックス ──────────
# コーナー回数で一意に判断できるもの。曖昧なケース(1400m/1600m)はクラスで判断。
_INNER_OUTER_BY_DIST = {
    # 京都芝（外回り距離はサフィックスなし=COURSE_FEATURESの既存キーを使用）
    ('京都', 1200): '内',   # 内回りのみ
    ('京都', 1800): '',     # 外回りのみ
    ('京都', 2000): '内',   # 内回りのみ(トラックコード=0, コーナー=4で確認済)
    ('京都', 2200): '',     # 外回りのみ
    ('京都', 2400): '',     # 外回りのみ
    ('京都', 3000): '',     # 外回りのみ
    ('京都', 3200): '',     # 外回りのみ
    # 阪神芝（JRA公式コース表より: 1200m・2000m・2200m・3000mは内回りのみ）
    ('阪神', 1200): '内',   # 内回りのみ(直線356m)
    ('阪神', 2000): '内',   # 内回りのみ(大阪杯等, 直線356m, 1C=325m)
    ('阪神', 2200): '内',   # 内回りのみ(宝塚記念等, 直線356m, 1C=525m)
    ('阪神', 3000): '内',   # 内回りのみ(神戸新聞杯等, 直線356m, 1C=1325m)
}
# 1400m/1600mはクラスで判断（course_times_full_new.jsonの収録クラス分布に基づく）
_KY_INNER_CLASSES = {
    1400: {'新馬', '未勝利'},                # 内回り1400mは新馬・未勝利のみ
    1600: {'新馬', '未勝利', '1勝'},          # 内回り1600mは1勝以下
}


def _get_inner_outer(venue: str, surface: str, dist: int,
                     num_corners: int = 0, class_name: str = '') -> str:
    """出馬表情報から内回り/外回りサフィックス(''/'内'/'外')を返す。"""
    if surface == 'ダート':
        return ''
    key = (venue, dist)
    if key in _INNER_OUTER_BY_DIST:
        return _INNER_OUTER_BY_DIST[key]
    # 京都 1400m/1600m: クラスで内外を判定
    if venue == '京都' and dist in _KY_INNER_CLASSES:
        cn = class_name.strip()
        inner_set = _KY_INNER_CLASSES[dist]
        is_inner = cn in inner_set
        suffix = '内' if is_inner else '外'
        candidate = f"{venue}芝{dist}m{suffix}"
        return suffix if candidate in COURSE_FEATURES else ''
    # 新潟 2000m: コーナー回数で判断（内=2, 外=4またはその他）
    if venue == '新潟' and dist == 2000:
        return '内' if num_corners == 2 else '外'
    return ''


def class_score(着順, 頭数) -> float:
    if pd.isna(着順) or pd.isna(頭数) or 頭数 <= 0: return 0.0
    return (頭数 - 着順 + 1) / 頭数


def deviation_score(values, mean=None, std=None):
    if mean is None: mean = np.nanmean(values)
    if std  is None: std  = np.nanstd(values)
    if std == 0: return [50.0] * len(values)
    return [(v - mean) / std * 10 + 50 for v in values]



# ── 芝スタートのダートコース（外枠有利）──────────────────────────
TURF_START_DIRT = {
    "東京ダート1600m", "中山ダート1200m", "京都ダート1400m",
    "阪神ダート1400m", "阪神ダート2000m",
    "福島ダート1150m", "新潟ダート1200m", "中京ダート1400m",
}

def pace_bias_from_course(course_key: str, dist: int) -> float:
    """
    コース特性・距離帯・馬場種別に基づくペース複合補正値。
    正値→ハイペース方向, 負値→スロー/前有利方向
    ダートは芝より前が止まりにくくスロー傾向 → -2 固定バイアス
    """
    f = COURSE_FEATURES.get(course_key, {})
    bias = 0.0
    # 直線長: 長いほど差し馬が伸びやすく前がペースを上げざるを得ない
    straight = f.get('直線', 350)
    if   straight >= 500: bias += 2.0   # 東京・新潟外（超長い）
    elif straight >= 400: bias += 1.0   # 阪神外・中京・京都外
    elif straight <= 280: bias -= 1.0   # 函館・福島・小倉（短い）
    # コーナー区分: 小回りはペース上がりにくい・タイト→前有利
    corner = f.get('コーナー', 1)
    if   corner == 2: bias -= 2.0       # 小回り（中山・函館・小倉・福島等）
    elif corner == 0: bias += 1.0       # 大回り（東京・阪神外・京都外）
    # 坂: 急坂はスタミナ消耗でペース自然に落ちる
    slope = f.get('坂', 0)
    if slope == 2: bias -= 1.0
    # 距離帯: 長距離はスロー・短距離はハイ
    if   dist > 2200:  bias -= 2.0
    elif dist > 1700:  bias -= 1.0
    elif dist <= 1400: bias += 1.0
    # ダートバイアス: 砂は前が止まりにくく基本スロー/前有利傾向
    if 'ダート' in course_key:
        bias -= 2.0
    return bias

def course_bonus_modifier(course_key: str) -> dict:
    """
    コース特性（直線長・坂・コーナー区分）に基づく脚質ボーナス修正量。
    展開ptのベースボーナスに加算する。
    """
    f = COURSE_FEATURES.get(course_key, {})
    mod = {'逃げ': 0, '先行': 0, '差し': 0, '追込': 0}
    # 直線長: 長いほど差し有利、短いほど先行有利
    straight = f.get('直線', 350)
    if straight >= 500:          # 東京・新潟外
        mod['差し'] += 2; mod['追込'] += 2
        mod['逃げ'] -= 2; mod['先行'] -= 1
    elif straight >= 400:        # 阪神外・中京・京都外
        mod['差し'] += 1; mod['追込'] += 1
        mod['逃げ'] -= 1
    elif straight <= 280:        # 函館・福島・小倉
        mod['逃げ'] += 2; mod['先行'] += 1
        mod['差し'] -= 1; mod['追込'] -= 2
    # 坂: 急坂は逃げ先行がバテやすい→差し相対有利
    slope = f.get('坂', 0)
    if slope == 2:
        mod['逃げ'] -= 1; mod['先行'] -= 1
        mod['差し'] += 1
    # コーナー区分: 小回りは先行有利、大回りは差し有利
    corner = f.get('コーナー', 1)
    if corner == 2:              # 小回り
        mod['逃げ'] += 1; mod['先行'] += 2
        mod['差し'] -= 1; mod['追込'] -= 2
    elif corner == 0:            # 大回り
        mod['差し'] += 1; mod['追込'] += 1
        mod['逃げ'] -= 1
    # ダートは芝より前が残りやすい（砂は差しが伸びにくい）
    if 'ダート' in course_key:
        mod['逃げ'] += 2; mod['先行'] += 2
        mod['差し'] -= 1; mod['追込'] -= 2
    return mod

def calc_wakuban_pts(umaban, kyakushitsu: str, target_course: str, num_horses: int) -> float:
    """
    ⑤ 枠順×脚質補正
    - 芝スタートのダートコース: 外枠（9番以降）は芝区間が長く先行有利→加点
    - 通常コース: 逃げ馬×内枠→加点 / 逃げ馬×大外→減点
    - 先行馬×内枠→小加点
    """
    if umaban is None or pd.isna(umaban): return 0.0
    umaban = int(umaban)
    is_turf_start = target_course in TURF_START_DIRT
    is_outer      = umaban >= 9
    is_far_outer  = umaban >= max(10, num_horses - 2)
    is_inner      = umaban <= 4

    if is_turf_start:
        # 芝スタートダート: 外枠の方が芝加速区間が長くスタートダッシュ有利
        if is_outer and kyakushitsu in ('逃げ', '先行'):
            return 1.5
        elif is_outer:
            return 0.5
        return 0.0
    else:
        # 通常コース
        if kyakushitsu == '逃げ':
            if is_inner:      return  1.0   # 内枠→ハナ取りやすい
            if is_far_outer:  return -1.0   # 大外→ハナ争い不利
        elif kyakushitsu == '先行':
            if is_inner:      return  0.5   # 内枠→好位確保しやすい
        return 0.0

def classify_脚質(avg_4kaku, 頭数_avg) -> str:
    if pd.isna(avg_4kaku) or avg_4kaku == 0: return '不明'
    # 頭数相対化閾値（差し過少分類→先行の正解率改善）
    # 逃げ: 絶対的な1〜2番手。先行: 頭数の37%以内。差し: 70%以内。
    n = float(頭数_avg) if (頭数_avg is not None and not pd.isna(頭数_avg) and float(頭数_avg) > 1) else 16.0
    nige_thr   = 2.0                        # 逃げ: 1〜2番手（絶対的先頭グループ）
    senkou_thr = max(5.5, n * 0.37)         # 先行: 16頭→5.9, 18頭→6.7
    sashi_thr  = max(9.5, n * 0.70)         # 差し: 16頭→11.2, 18頭→12.6
    if avg_4kaku <= nige_thr:   return '逃げ'
    if avg_4kaku <= senkou_thr: return '先行'
    if avg_4kaku <= sashi_thr:  return '差し'
    return '追込'


def weighted_avg_4kaku(sub_sorted_desc) -> float:
    """
    最近2〜3走に重みをかけた4角通過順の加重平均（改善②）。
    sub_sorted_desc: 日付降順ソート済みのDataFrame
    重み: 1走目=3, 2走目=2, 3走目=1, 4走目以降=0.5
    """
    legs = []
    weights = []
    base_weights = [3.0, 2.0, 1.0]
    for i, (_, row) in enumerate(sub_sorted_desc.iterrows()):
        pos = None
        for p in [row['通過順4角'], row['通過順3角'],
                  row['通過順2角'], row['通過順1角']]:
            if not pd.isna(p) and p > 0:
                pos = float(p)
                break
        if pos is None:
            continue
        w = base_weights[i] if i < len(base_weights) else 0.5
        legs.append(pos)
        weights.append(w)
    if not legs:
        return np.nan
    return float(np.average(legs, weights=weights))


def to_year4(y) -> int:
    y = int(y)
    if y < 100: y += 2000
    return y


def fmt_sec_to_time(sec) -> str:
    if sec is None or np.isnan(sec): return '-'
    m = int(sec) // 60
    s = sec - m * 60
    return f"{m}:{s:05.2f}"


# ─────────────────────────────────────────────────────────────────────────────
# A-1  馬場状態補正
# ─────────────────────────────────────────────────────────────────────────────

def going_adj_sec(going, surface, dist_m: float) -> float:
    """
    馬場状態から走破タイムを良馬場相当に換算するための補正秒数 (秒/km)。
    corrected_time = actual_time - going_adj_sec

    データの馬場状態値: '良' / '稍'(稍重) / '重' / '不'(不良)

    係数は実データ（2750走）の馬場状態別タイム差から算出（trimmed mean）。

    芝: 重くなるほど遅くなる → adj > 0 (補正後タイムを短縮して実力を正当評価)
      良:0.0  稍:+0.7  重:+1.0  不:+1.5  (秒/km)
      例) 1800m・重 → +1.80秒の補正

    ダート: 軽い重さでは速くなるが重・不良では速くなる傾向にある
      良:0.0  稍:+0.3  重:-0.4  不:-0.4  (秒/km)
      ※ダート稍重は実データで平均+0.33秒/km（小距離ほど影響が小さく長距離ほど大きい）
      ※ダート重・不良は水分過多で逆に速くなるため負の補正
    """
    ratio = dist_m / 1000.0
    going_str = str(going).strip() if not pd.isna(going) else '良'
    if surface == '芝':
        adj_per_km = {'良': 0.0, '稍': 0.7, '重': 1.0, '不': 1.5}.get(going_str, 0.0)
    else:  # ダート
        adj_per_km = {'良': 0.0, '稍': 0.3, '重': -0.4, '不': -0.4}.get(going_str, 0.0)
    return adj_per_km * ratio



# ─────────────────────────────────────────────────────────────────────────────
# ④  馬体重増減補正
# ─────────────────────────────────────────────────────────────────────────────

def calc_taiju_pts(horse_name: str, shutuba_df) -> float:
    """
    馬体重増減補正 (-1〜0pt)
    大幅な増減は太め残り・体調不安の懸念として小さく減点。
      |増減| ≥ 20kg : -1.0pt
      |増減| 12-19kg: -0.5pt
      |増減| ≤ 11kg : 0pt
    """
    if shutuba_df is None: return 0.0
    rows = shutuba_df[shutuba_df['馬名'] == horse_name]
    if rows.empty: return 0.0
    try:
        # '増減'列はshutuba読込時に'馬体重増減_raw'へ改名される場合がある
        delta = None
        for _col in ('馬体重増減_raw', '増減', '馬体重増減'):
            if _col in rows.columns:
                _v = rows.iloc[0][_col]
                if _v is not None and not (isinstance(_v, float) and np.isnan(_v)):
                    delta = float(_v)
                    break
        if delta is None: return 0.0
        if abs(delta) >= 20: return -1.0
        if abs(delta) >= 12: return -0.5
    except Exception:
        pass
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# ⑥  継続騎乗補正
# ─────────────────────────────────────────────────────────────────────────────

def calc_keizoku_pts(horse_name: str, sub: pd.DataFrame, shutuba_df) -> float:
    """
    継続騎乗加点 (0 / +1pt)
    前走と同じ騎手が継続騎乗する場合に加点。
    馬の特性・コース取りを熟知している点を評価。
    """
    if shutuba_df is None or len(sub) == 0: return 0.0
    try:
        rows = shutuba_df[shutuba_df['馬名'] == horse_name]
        if rows.empty: return 0.0
        today_j = str(rows.iloc[0]['騎手']).strip()
        prev_j  = str(sub.iloc[0]['騎手']).strip()
        if today_j and prev_j and today_j != 'nan' and prev_j != 'nan':
            return 1.0 if today_j == prev_j else 0.0
    except Exception:
        pass
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# ⑧  前走着差補正
# ─────────────────────────────────────────────────────────────────────────────

# 前走クラス別着差係数: 高クラスの好走をより高く評価
CLASS_CHAKUSA_MULT = {
    'G1': 1.5, 'G2': 1.3, 'G3': 1.2, 'OP': 1.1,
    '3勝': 1.0, '2勝': 0.9, '1勝': 0.8, '未勝利': 0.6, '新馬': 0.5,
}


def calc_chakusa_pts(sub: pd.DataFrame) -> float:
    """
    前走着差補正 (-2〜+3pt)
    着差(秒)で前走の競争水準を評価する。着順より実力差を反映。
      1着             : +2.0pt × クラス係数 (最大 +3pt)
      着差 ≤ 0.5秒     : +1.0pt × クラス係数
      着差 0.6〜1.0秒  :  0.0pt
      着差 1.1〜2.0秒  : -1.0pt
      着差 > 2.0秒     : -2.0pt
    クラス係数: G1=1.5 → 新馬=0.5 (プラスのみ拡大、マイナスは変化なし)
    """
    if len(sub) == 0: return 0.0
    try:
        rank   = int(sub.iloc[0]['確定着順'])
        margin = float(sub.iloc[0]['着差タイム'])
        cn     = normalize_class(sub.iloc[0]['クラス名'])
        mult   = CLASS_CHAKUSA_MULT.get(cn, 1.0)
        if rank == 1:       base = 2.0
        elif margin <= 0.5: base = 1.0
        elif margin <= 1.0: base = 0.0
        elif margin <= 2.0: base = -1.0
        else:               base = -2.0
        # クラス係数はプラス（好走）のみに適用
        pts = base * mult if base > 0 else base
        return float(np.clip(pts, -2.0, 3.0))
    except Exception:
        pass
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# A-2  斤量補正
# ─────────────────────────────────────────────────────────────────────────────

def calc_kinryo_pts(sub: pd.DataFrame, today_weight: float = None) -> float:
    """
    A-2 斤量補正 (0 / -1pt)
    今走斤量が57kg以上の場合のみ-1pt（重斤量による不利）。

    ※斤量増減による評価（従来方式）は廃止。
      実データ分析で「強い馬ほど重い斤量を背負う」傾向から識別力がマイナスだったため。
    """
    try:
        if today_weight is not None and float(today_weight) >= 57.0:
            return -1.0
    except Exception:
        pass
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# A-3  距離適性補正
# ─────────────────────────────────────────────────────────────────────────────

def dist_range(d: int) -> str:
    """距離帯を返す。短距離/マイル/中距離/長距離"""
    if d <= 1400:   return '短距離'
    if d <= 1700:   return 'マイル'
    if d <= 2200:   return '中距離'
    return '長距離'


def calc_kyori_pts(sub: pd.DataFrame, target_dist: int = TARGET_DIST,
                   horse_name: str = None, shutuba_df=None,
                   target_surface: str = '芝') -> float:
    """
    A-3 距離適性補正 (-2〜+2pt)

    ① 前走距離差ペナルティ (0 / -2pt)
       前走との距離差が400m以上 → -2pt

    ② TGX高指数ボーナス (+2pt)
       今走と同条件（コース種別×距離帯）のTGX ≥ 95 → +2pt
       TGXは出馬表の条件別列を参照（TGX芝短/芝中/ダ短/ダ中）
       なければTGX直前で代替
    """
    # ① 前走距離差ペナルティ（400m以上の距離延長のみ）
    penalty = 0.0
    try:
        last_dist = int(sub.iloc[0]['距離'])
        if target_dist - last_dist >= 400:   # 距離延長が400m以上のときのみ減点
            penalty = -2.0
    except Exception:
        pass

    # ② TGX高指数ボーナス
    tgx_bonus = 0.0
    try:
        if horse_name is not None and shutuba_df is not None:
            s_row = shutuba_df[shutuba_df['馬名'] == horse_name]
            if not s_row.empty:
                # 条件別TGX列（今走と同じコース種別×距離帯）を優先
                tgx_val = None
                cond_col = get_tgx_col(target_surface, float(target_dist))
                for col in [cond_col, 'TGX直前']:
                    if col in s_row.columns:
                        v = pd.to_numeric(s_row.iloc[0][col], errors='coerce')
                        if not pd.isna(v):
                            tgx_val = float(v)
                            break
                if tgx_val is not None and tgx_val >= 95:
                    tgx_bonus = 2.0
    except Exception:
        pass

    return penalty + tgx_bonus


# ─────────────────────────────────────────────────────────────────────────────
# A-4  コース適性
# ─────────────────────────────────────────────────────────────────────────────

def course_similarity(past_key: str, today_key: str = TARGET_COURSE) -> float:
    """
    コース特性の類似度 (0.0〜1.0)
    重み: コーナー区分 0.20, 回り方向 0.25, 直線距離 0.20,
          1コーナーまで距離 0.15, 坂 0.15, 洋芝 0.05
    コーナー区分: 0=大回り, 1=中回り, 2=小回り
    """
    if past_key == today_key: return 1.0
    f = COURSE_FEATURES
    if past_key not in f or today_key not in f: return 0.45  # 不明は低めの中立
    p, t = f[past_key], f[today_key]
    sim = 0.0
    # コーナー区分 (0〜2の差を0〜1に正規化: 差0→1.0, 差1→0.5, 差2→0.0)
    corner_diff = abs(p.get('コーナー', 1) - t.get('コーナー', 1))
    sim += 0.20 * max(0.0, 1.0 - corner_diff / 2.0)
    sim += 0.25 * (1.0 if p['回り'] == t['回り'] else 0.0)
    sim += 0.20 * max(0.0, 1.0 - abs(p['直線'] - t['直線']) / 400.0)
    sim += 0.15 * max(0.0, 1.0 - abs(p['1C距離'] - t['1C距離']) / 500.0)
    sim += 0.15 * max(0.0, 1.0 - abs(p['坂'] - t['坂']) / 2.0)
    sim += 0.05 * (1.0 if p['洋芝'] == t['洋芝'] else 0.5)
    return sim


def calc_course_apt_pts(
    sub: pd.DataFrame,
    course_times: dict,
    today_key: str = TARGET_COURSE,
    ref: float = 0.55,
    scale: float = 20.0,
) -> tuple:
    """
    A-4 コース適性補正 (±10pt)
    類似コースで好走しているほど加点、異質コースのみなら減点。
    """
    if len(sub) == 0:
        return 0.0, 0.5

    total_w, total_sw = 0.0, 0.0
    for i, row in sub.iterrows():
        ck  = row['course_key']
        sim = course_similarity(ck, today_key)
        cn  = row['class_norm']
        cw  = CLASS_WEIGHTS.get(cn, 0.6)
        rw  = recency_weight(i + 1)
        w   = cw * rw
        total_sw += sim * w
        total_w  += w

    avg_sim = total_sw / total_w if total_w > 0 else ref
    pts = float(np.clip((avg_sim - ref) * scale, -10.0, 10.0))
    return pts, round(avg_sim, 3)


# ─────────────────────────────────────────────────────────────────────────────
# A-5  臨戦過程補正
# ─────────────────────────────────────────────────────────────────────────────

def calc_rinsen_pts(sub: pd.DataFrame, race_date: date = RACE_DATE) -> float:
    """
    A-5 臨戦過程補正（7段階）
      連闘    ( 〜 7日)  : -1pt  (状態に自信あり可能性あるが疲労リスク)
      中1週   ( 8〜14日) : -1pt  (やや疲労残りリスク)
      中2〜4週(15〜35日) :  0pt  (標準的な間隔)
      中5〜8週(36〜56日) : +1pt  (適度な間隔、叩き効果)
      3〜4ヶ月(57〜119日): -1pt  (やや間隔あき)
      4〜6ヶ月(120〜179日): -2pt (長期休養)
      6ヶ月超 (180日〜) : -4pt  (長期休養)
    """
    try:
        y = to_year4(sub.iloc[0]['年'])
        m = int(sub.iloc[0]['月'])
        d = int(sub.iloc[0]['日'])
        days = (race_date - date(y, m, d)).days
        if days >= 180: return -4.0
        if days >= 120: return -2.0
        if days >= 57:  return -1.0
        if days >= 36:  return  1.0
        if days >= 15:  return  0.0
        if days >= 8:   return -1.0
        return -1.0  # 連闘（〜7日）
    except Exception:
        pass
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# A-6  PCI 活用
# ─────────────────────────────────────────────────────────────────────────────

def calc_pci_pts(sub: pd.DataFrame, today_pace: str = 'high') -> float:
    """
    A-6 PCI補正 → 廃止（常に0を返す）
    分析の結果、相関が逆転していたため廃止。
    today_pace: 'high' (ハイペース想定) or 'low' (スロー想定) or 'mid'
    PCI<50 = ハイペース(前傾), PCI>=50 = スローペース(後傾)
    """
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# A-7  騎手実績
# ─────────────────────────────────────────────────────────────────────────────

def compute_jockey_scores(df: pd.DataFrame, shrink_k: int = 20) -> tuple:
    """
    全過去データから騎手別成績を集計し、Bayesian収縮スコアを返す。
    Returns: (jockey_scores_dict, prior)
      jockey_scores_dict: jockey_name → adjusted score
      prior: 全体加重平均
    """
    records = defaultdict(lambda: {'pw': 0.0, 'w': 0.0, 'n': 0})

    for _, row in df.iterrows():
        jockey = str(row.get('騎手', '')).strip()
        if not jockey or jockey == 'nan': continue
        cn  = normalize_class(row.get('クラス名'))
        cw  = CLASS_WEIGHTS.get(cn, 0.6)
        cs  = class_score(row.get('確定着順'), row.get('頭数'))
        records[jockey]['pw'] += cs * cw
        records[jockey]['w']  += cw
        records[jockey]['n']  += 1

    if not records:
        return {}, 0.45

    # grand prior (weighted)
    total_pw = sum(v['pw'] for v in records.values())
    total_w  = sum(v['w']  for v in records.values())
    prior    = total_pw / total_w if total_w > 0 else 0.45

    jockey_scores = {}
    for jockey, v in records.items():
        if v['w'] <= 0: continue
        raw_avg  = v['pw'] / v['w']
        eff_n    = v['n']
        adj      = prior + (raw_avg - prior) * eff_n / (eff_n + shrink_k)
        jockey_scores[jockey] = adj

    return jockey_scores, prior


def calc_jockey_pts(
    jockey: str,
    jockey_scores: dict,
    prior: float,
    field_avg: float,
    scale: float = 30.0,
) -> float:
    """A-7 騎手補正 (±2pt)"""
    score = jockey_scores.get(str(jockey).strip(), prior)
    pts   = float(np.clip((score - field_avg) * scale, -2.0, 2.0))
    return pts


# ─────────────────────────────────────────────────────────────────────────────
# C-3  調教評価
# ─────────────────────────────────────────────────────────────────────────────

def compute_training_pts(
    horses_list: list,
    sakuro_df: pd.DataFrame,
    wood_df:   pd.DataFrame,
    race_date: date = RACE_DATE,
    window_days: int = 14,
) -> tuple:
    """
    C-3 調教評価 (±3pt)
    坂路/ウッドの最終ラップ(Lap1 / 1F)をフィールド平均と比較。
    lower Lap1 = faster = better.

    Returns:
      training_pts:  horse_name → float
      training_info: horse_name → {'坂路Lap1': float or None, 'ウッドLap1': float or None}
    """
    # 日付をYYYYMMDD整数として比較 (年月日列はint型 YYYYMMDD)
    cutoff_int = int((race_date - timedelta(days=window_days)).strftime('%Y%m%d'))
    race_int   = int(race_date.strftime('%Y%m%d'))
    sakuro_best: dict = {}
    wood_best:   dict = {}

    # 坂路
    if sakuro_df is not None:
        try:
            sdf = sakuro_df.copy()
            # 年月日はYYYYMMDD整数。すでにint/floatなのでそのまま数値化
            date_s = pd.to_numeric(sdf['年月日'], errors='coerce')
            sdf = sdf[date_s.between(cutoff_int, race_int)]
            for horse in horses_list:
                sub = sdf[sdf['馬名'] == horse]
                if sub.empty: continue
                vals = pd.to_numeric(sub['Lap1'], errors='coerce').dropna()
                if vals.empty: continue
                sakuro_best[horse] = float(vals.min())
        except Exception as e:
            print(f"  坂路読み込みエラー: {e}")

    # ウッド
    if wood_df is not None:
        try:
            wdf = wood_df.copy()
            date_w = pd.to_numeric(wdf['年月日'], errors='coerce')
            wdf = wdf[date_w.between(cutoff_int, race_int)]
            lap_col = 'Lap1' if 'Lap1' in wdf.columns else '1F'
            for horse in horses_list:
                sub = wdf[wdf['馬名'] == horse].copy()
                if sub.empty: continue
                sub['lap_num'] = pd.to_numeric(sub[lap_col], errors='coerce')
                sub = sub[sub['lap_num'] < 15.0]  # 軽め調教を除外
                if sub.empty: continue
                wood_best[horse] = float(sub['lap_num'].min())
        except Exception as e:
            print(f"  ウッド読み込みエラー: {e}")

    # フィールド平均 (各トラック別)
    sakuro_vals = list(sakuro_best.values())
    wood_vals   = list(wood_best.values())
    sakuro_avg  = float(np.mean(sakuro_vals)) if sakuro_vals else None
    wood_avg    = float(np.mean(wood_vals))   if wood_vals   else None

    training_pts:  dict = {}
    training_info: dict = {}

    for horse in horses_list:
        scores = []
        if horse in sakuro_best and sakuro_avg is not None:
            s = (sakuro_avg - sakuro_best[horse]) * 2.0
            scores.append(s)
        if horse in wood_best and wood_avg is not None:
            s = (wood_avg - wood_best[horse]) * 2.0
            scores.append(s)

        pts = float(np.clip(np.mean(scores), -3.0, 3.0)) if scores else 0.0
        training_pts[horse]  = pts
        training_info[horse] = {
            '坂路Lap1':  sakuro_best.get(horse),
            'ウッドLap1': wood_best.get(horse),
        }

    print(f"  調教データ: 坂路 {len(sakuro_best)}頭 / ウッド {len(wood_best)}頭 (14日以内)")
    if sakuro_avg: print(f"    坂路フィールド平均Lap1: {sakuro_avg:.2f}s")
    if wood_avg:   print(f"    ウッドフィールド平均Lap1: {wood_avg:.2f}s")

    return training_pts, training_info


# ─────────────────────────────────────────────────────────────────────────────
# A-8  展開pts（位置取り確率ベース）
# ─────────────────────────────────────────────────────────────────────────────

def calc_position_pts(
    umaban: int,
    num_horses: int,
    avg_4kaku: float,
    past_avg_heads: float,
    target_course: str,
) -> float:
    """
    位置取りスコア: 枠番・頭数・コース特性 + 過去走4角通過順実績
    精度確認中につき ±2pt にクリップ。
    Returns: -2.0 ~ +2.0
    """
    # 1. 枠番から期待先行有利度（内枠=有利=高値）
    if umaban and num_horses > 0:
        try:
            waku_adv = (num_horses + 1 - int(umaban)) / num_horses  # 1=内枠, 0=外枠
        except (ValueError, TypeError):
            waku_adv = 0.5
    else:
        waku_adv = 0.5

    # コース特性: 小回りほど内枠の重要度を高める
    f      = COURSE_FEATURES.get(target_course, {})
    corner = f.get('コーナー', 1)          # 0=大回り, 1=普通, 2=小回り
    waku_weight = 0.3 + corner * 0.1       # 大回り=0.3, 普通=0.4, 小回り=0.5

    # 2. 過去走4角実績（実績がなければ枠番のみ）
    avg_4kaku_f = float(avg_4kaku) if (avg_4kaku is not None and not pd.isna(avg_4kaku)) else None
    if avg_4kaku_f and avg_4kaku_f > 0:
        avg_heads  = float(past_avg_heads) if (past_avg_heads and not pd.isna(past_avg_heads) and float(past_avg_heads) > 1) else float(num_horses)
        # 通過順を 0-1 に正規化（1位=1.0, 最後尾=0.0）
        actual_pos_ratio = 1.0 - (avg_4kaku_f - 1) / max(avg_heads - 1, 1)
        actual_pos_ratio = max(0.0, min(1.0, actual_pos_ratio))
        pos_score = waku_adv * waku_weight + actual_pos_ratio * (1 - waku_weight)
    else:
        pos_score = waku_adv

    # 3. 0-1 → -2〜+2 pt
    return float(np.clip((pos_score - 0.5) * 4.0, -2.0, 2.0))




def calc_tenkai_pts_all(
    res: 'pd.DataFrame',
    target_course: str,
    today_pace: str,
    num_horses: int,
    smartrc_ten_ranks: dict = None,
) -> 'pd.Series':
    """
    展開有利不利スコア（全馬一括計算、±4pt）

    旧 calc_position_pts（±2pt, 枠番+通過順のみ）を全面刷新。

    考慮要素:
    1. 予測位置比率: 過去走4角通過順（頭数正規化）+ SmartRCテン速度補正
    2. ゾーン割り当て: 逃げ/番手/先行/中団/後方
    3. ペース×ゾーン有利不利（today_pace: high/mid/low）
       - ハイ: 番手(3〜5番手)が最有利、逃げは消耗、後方もチャンスあり
       - スロー: 逃げ〜番手が有利、差し・追込は届きにくい
    4. 同ゾーン競合（混雑）ペナルティ: 許容頭数超過分 × -0.7pt
    5. コース特性×内枠優先: 小回りほど内枠ボーナス大
    """
    import numpy as np

    if res.empty:
        return pd.Series(dtype=float, index=res.index)

    n = max(int(num_horses), len(res))

    # ── 1. 予測位置比率 (0=最前方, 1=最後方) ──────────────────────────
    pos_ratios = []
    for _, r in res.iterrows():
        avg4   = r.get('平均4角通過順')
        avg_h  = r.get('平均頭数')
        avg4_f = float(avg4) if (avg4 is not None and not pd.isna(avg4) and float(avg4) > 0) else None
        avg_h_f = float(avg_h) if (avg_h is not None and not pd.isna(avg_h) and float(avg_h) > 1) else float(n)

        if avg4_f:
            base = (avg4_f - 1.0) / max(avg_h_f - 1.0, 1.0)
            base = max(0.0, min(1.0, base))
        else:
            base = 0.5  # データなし → 中間

        # SmartRCテン速度で補正（テン速度順位が小さい=速い → より前方）
        ten_r = r.get('SmartRCテン速度順位')
        if ten_r is not None:
            try:
                ten_adj = (float(ten_r) - 1.0) / max(n - 1.0, 1.0) * 0.15 - 0.075
                base = max(0.0, min(1.0, base + ten_adj))
            except (TypeError, ValueError):
                pass

        pos_ratios.append(base)

    res = res.copy()
    res['_pos_ratio'] = pos_ratios

    # ── 2. ゾーン割り当て (0=逃げ, 1=番手, 2=先行, 3=中団, 4=後方) ──
    def ratio_to_zone(ratio, nh):
        idx_f = ratio * (nh - 1)  # 予測絶対位置（0始まり）
        if idx_f < 1.5:                return 0  # 逃げ（先頭1〜2番手）
        if idx_f < 4.5:                return 1  # 番手（3〜5番手）
        if idx_f < nh * 0.32:          return 2  # 先行（〜頭数32%）
        if idx_f < nh * 0.68:          return 3  # 中団（〜68%）
        return 4                                   # 後方

    res['_zone'] = res['_pos_ratio'].apply(lambda r: ratio_to_zone(r, n))

    # ── 3. ペース×ゾーン有利不利 ─────────────────────────────────────
    if today_pace == 'high':
        # ハイペース: 逃げは消耗、番手(3〜5番手)が最有利
        # 中団まで展開の恩恵あり（差し馬が届きやすい）
        pace_zone_bonus = {0: -1.5, 1: +2.5, 2: +1.0, 3: +0.5, 4: -0.5}
    elif today_pace == 'low':
        # スローペース: 逃げ〜番手が有利、後方は展開負け
        pace_zone_bonus = {0: +2.0, 1: +2.5, 2: +0.5, 3: -0.5, 4: -2.0}
    else:  # mid
        # ミドル: 番手が最有利、比較的フラット
        pace_zone_bonus = {0: +0.5, 1: +2.0, 2: +1.0, 3: -0.0, 4: -1.0}

    # ── 4. 同ゾーン混雑ペナルティ ────────────────────────────────────
    zone_counts = res['_zone'].value_counts().to_dict()
    zone_capacity = {0: 2, 1: 3, 2: 4, 3: 5, 4: 4}  # 各ゾーンの許容頭数
    zone_penalty = {z: min(0.0, -(max(0, cnt - zone_capacity.get(z, 4))) * 0.7)
                    for z, cnt in zone_counts.items()}

    # ── 5. コース特性×内枠ボーナス ───────────────────────────────────
    f      = COURSE_FEATURES.get(target_course, {})
    corner = f.get('コーナー', 1)          # 0=大回り, 1=普通, 2=小回り
    inner_scale = 0.3 + corner * 0.15      # 大回り0.3, 普通0.45, 小回り0.6

    # ── 6. 各馬スコア計算 ─────────────────────────────────────────────
    results = []
    for _, r in res.iterrows():
        zone = int(r['_zone'])
        uma  = r.get('馬番')

        pt = pace_zone_bonus.get(zone, 0.0)
        pt += zone_penalty.get(zone, 0.0)

        # 内枠ボーナス
        if uma is not None:
            try:
                inner_bonus = (n + 1 - int(uma)) / n * inner_scale
                pt += inner_bonus
            except (ValueError, TypeError):
                pass

        results.append(pt)

    pts = pd.Series(results, index=res.index)
    return pts.clip(-4.0, 4.0)

# ─────────────────────────────────────────────────────────────────────────────
# メイン処理
# ─────────────────────────────────────────────────────────────────────────────

def compute_scores(
    df: pd.DataFrame,
    course_times: dict,
    shutuba_df:  pd.DataFrame = None,
    sakuro_df:   pd.DataFrame = None,
    wood_df:     pd.DataFrame = None,
    race_date:   date = RACE_DATE,
    target_dist: int  = TARGET_DIST,
    target_course: str = TARGET_COURSE,
    baba:        str  = '良',      # 馬場状態: 良/稍重/重/不良
    target_class: str = '',        # 今走クラス名（昇級戦判定用）
    smartrc_data: dict = None,     # SmartRC horses辞書 (load_smartrc_data()の戻り値)
) -> tuple:
    """
    18頭分のスコアを計算。
    Returns: (res_df, meta, past_races_map)
    """
    df = df.copy()
    df['class_norm'] = df['クラス名'].apply(normalize_class)
    df['date_int']   = (df['年'].astype(int) * 10000
                        + df['月'].astype(int) * 100
                        + df['日'].astype(int))
    df['course_key'] = df.apply(course_key_from_row, axis=1)

    horses = sorted(df['馬名'].unique().tolist())

    # 出馬表にあって過去走データにない馬（新馬・初出走等）も対象に追加
    # → 調教データ等がある場合に参考スコアとして算出する
    _known_horses = set(df['馬名'].values)
    _shutuba_only: set = set()
    if shutuba_df is not None:
        for _hn in shutuba_df['馬名'].astype(str).str.strip():
            if _hn and _hn != 'nan' and _hn not in _known_horses:
                _shutuba_only.add(_hn)
        if _shutuba_only:
            print(f"  [INFO] 過去走データなし（参考スコアのみ）: {sorted(_shutuba_only)}")
            horses = sorted(set(horses) | _shutuba_only)

    # ── A-7 騎手実績スコア (全過去データで事前計算) ─────────────
    print("  [A-7] 騎手実績スコア計算...")
    jockey_scores, jockey_prior = compute_jockey_scores(df)

    # ── C-3 調教評価 (全馬一括事前計算) ───────────────────────
    print("  [C-3] 調教評価計算...")
    training_pts_map, training_info_map = compute_training_pts(
        horses, sakuro_df, wood_df, race_date
    )

    # ── 脚質の事前判定 → ペース決定 ───────────────────────────
    legs_pre = []
    avg4_map = {}  # 馬名→加重平均4角通過順（ペース計算で再利用）
    for h in horses:
        sub = (df[df['馬名'] == h]
               .sort_values('date_int', ascending=False)
               .reset_index(drop=True))
        avg4 = weighted_avg_4kaku(sub)
        avg4_map[h] = avg4
        legs_pre.append(classify_脚質(avg4, sub['頭数'].mean()))

    leg_count_pre = {}
    for l in legs_pre: leg_count_pre[l] = leg_count_pre.get(l, 0) + 1
    front_pre = leg_count_pre.get('逃げ', 0) + leg_count_pre.get('先行', 0)

    # ── SmartRCテン速度競合によるペース圧力計算 ─────────────────
    # 「テン速度が速い馬が複数いる」→ 競り合いが発生 → ペースが速くなる
    _smartrc_ten_pre = []
    if smartrc_data:
        for h in horses:
            _src = (smartrc_data.get(h)
                    or smartrc_data.get(h.replace('　', ' '))
                    or smartrc_data.get(h.replace(' ', '　')))
            if _src:
                _v = _src.get('ten_has_rank')
                if _v not in (None, '', ' ', '  '):
                    try:
                        _smartrc_ten_pre.append(int(_v))
                    except (ValueError, TypeError):
                        pass

    # テン速度上位馬（1〜5位）の競合圧力
    _ten_fast_cnt  = sum(1 for r in _smartrc_ten_pre if r <= 5)
    _ten_top3_cnt  = sum(1 for r in _smartrc_ten_pre if r <= 3)
    smartrc_pace_pressure = _ten_fast_cnt * 0.3 + _ten_top3_cnt * 0.7

    # ── コース特性バイアス + 前走頭数ベースの圧力 ────────────────
    bias_pre = pace_bias_from_course(target_course, target_dist)

    # 距離帯別・先行頭数による基礎圧力
    if target_dist <= 1400 and front_pre >= 5:
        dist_band_bonus = 3.0
    elif 1401 <= target_dist <= 2000 and front_pre >= 6:
        dist_band_bonus = 2.0
    else:
        dist_band_bonus = 0.0

    # SmartRCデータがある場合はそちらを優先使用
    if _smartrc_ten_pre:
        eff_pre = front_pre * 0.5 + bias_pre + smartrc_pace_pressure + dist_band_bonus
    else:
        eff_pre = front_pre + bias_pre + dist_band_bonus

    if eff_pre >= 9:
        today_pace = 'high'
    elif eff_pre <= 4:
        today_pace = 'low'
    else:
        today_pace = 'mid'

    # ── 今走騎手リスト (A-7 フィールド平均用) ─────────────────
    today_jockeys = []
    for h in horses:
        jkey = None
        if shutuba_df is not None:
            s = shutuba_df[shutuba_df['馬名'] == h]
            if not s.empty:
                v = s.iloc[0].get('騎手')
                if not pd.isna(v): jkey = str(v).strip()
        if jkey is None:
            sub = df[df['馬名'] == h].sort_values('date_int', ascending=False)
            if not sub.empty: jkey = str(sub.iloc[0]['騎手']).strip()
        today_jockeys.append(jkey)

    jockey_field_avg = float(np.mean(
        [jockey_scores.get(j, jockey_prior) for j in today_jockeys if j]
    )) if today_jockeys else jockey_prior

    # ── メインループ ────────────────────────────────────────
    target_surface    = '芝' if '芝' in target_course else 'ダート'
    target_class_norm = normalize_class(target_class) if target_class else ''
    today_class_rank  = CLASS_RANK.get(target_class_norm, 0)
    results      = []
    past_races_map: dict = {}  # horse_name → list of race dicts (B-2用)

    for h in horses:
        sub = (df[df['馬名'] == h]
               .sort_values('date_int', ascending=False)
               .reset_index(drop=True))
        n_races = len(sub)

        # ── 最高出力 (TGX条件別＋時間減衰) ──────────────
        best_hosei = calc_tgx_adjusted(h, shutuba_df, sub, race_date,
                                        target_surface, target_dist)
        # TGXが取れない場合の代替処理
        if best_hosei is None:
            if shutuba_df is not None:
                # shutuba使用中だが当該馬のTGXが未入力 → NaN（偏差計算でmean扱い）
                best_hosei = np.nan
            else:
                # shutuba未使用 → 過去走の補正タイム列をTGX代替として使用
                _raw = pd.to_numeric(sub['補正タイム'], errors='coerce').max()
                best_hosei = float(_raw) if not pd.isna(_raw) else np.nan

        # ── クラス補正着順（着差係数込み）────────────────
        cs_total, cs_w = 0.0, 0.0
        for i, row in sub.iterrows():
            rw    = recency_weight(i + 1)
            cw    = CLASS_WEIGHTS.get(row['class_norm'], 0.6)
            pos   = class_score(row['確定着順'], row['頭数'])
            # 着差係数: 1着ならボーナス、大差負けなら減衰
            try:
                _rank   = int(row['確定着順'])
                _margin = float(row['着差タイム'])
                if _rank == 1:
                    mf = 1.30
                elif _margin <= 0.3:
                    mf = 1.10
                elif _margin <= 0.6:
                    mf = 1.00
                elif _margin <= 1.2:
                    mf = 0.90
                elif _margin <= 2.0:
                    mf = 0.75
                else:
                    mf = 0.60
            except Exception:
                mf = 1.00
            score = pos * mf * cw
            cs_total += score * rw
            cs_w     += rw
        class_corrected = cs_total / cs_w if cs_w > 0 else 0.0

        # ── タイム偏差 (A-1 馬場補正込み) ──────────────
        dev_vals, dev_ws = [], []
        past_race_list   = []

        for i, row in sub.iterrows():
            ck       = row['course_key']
            cn       = row['class_norm']
            avg_key  = class_str_to_avg_key(cn)
            surface  = '芝' if row['芝・ダ'] != 'ダ' else 'ダート'
            going    = row.get('馬場状態', '良')
            dist_m   = float(row['距離']) if not pd.isna(row['距離']) else 1600.0
            actual_s = (float(row['走破タイム秒'])
                        if not pd.isna(row['走破タイム秒']) else None)
            pci_v    = row.get('PCI')

            # 馬場補正
            g_adj = going_adj_sec(going, surface, dist_m) if actual_s else 0.0
            corr_s = (actual_s - g_adj) if actual_s else None

            avg_sec = np.nan
            time_dev_this = None
            used_in_dev   = False
            if ck in course_times and avg_key in course_times[ck]:
                avg_sec = parse_time_str(course_times[ck][avg_key])
                if corr_s and not np.isnan(avg_sec):
                    dev = avg_sec - corr_s
                    rw  = recency_weight(i + 1)
                    dev_vals.append(dev)
                    dev_ws.append(rw)
                    time_dev_this = round(dev, 3)
                    used_in_dev   = True

            # 脚質判定 (this race)
            leg_pos_this = None
            for p in [row['通過順4角'], row['通過順3角'],
                      row['通過順2角'], row['通過順1角']]:
                if not pd.isna(p) and p > 0:
                    leg_pos_this = int(p)
                    break

            # 日付
            try:
                y4 = to_year4(row['年'])
                d_str = f"{y4}-{int(row['月']):02d}-{int(row['日']):02d}"
            except Exception:
                d_str = '-'

            sim = course_similarity(ck, target_course)

            past_race_list.append({
                '日付':         d_str,
                '場所':         str(row['場所']),
                'コース':       ck,
                'クラス':       cn,
                '着順':         (int(row['確定着順']) if not pd.isna(row['確定着順']) else None),
                '頭数':         (int(row['頭数']) if not pd.isna(row['頭数']) else None),
                '走破タイム':   fmt_sec_to_time(actual_s),
                '走破タイム秒': round(actual_s, 2) if actual_s else None,
                '馬場':         str(going).strip(),
                '馬場補正秒':   round(g_adj, 3),
                '補正後タイム秒': round(corr_s, 2) if corr_s else None,
                'コース平均秒': round(avg_sec, 2) if not np.isnan(avg_sec) else None,
                'タイム差':     time_dev_this,
                'PCI':          (round(float(pci_v), 1) if not pd.isna(pci_v) else None),
                '上がり3F':     (round(float(row['上がり3Fタイム']), 1)
                                 if not pd.isna(row['上がり3Fタイム']) else None),
                '4角通過順':    leg_pos_this,
                '騎手':         str(row['騎手']),
                '斤量':         (float(row['斤量']) if not pd.isna(row['斤量']) else None),
                'コース類似度': round(sim, 2),
                '着順スコア':   round(class_score(row['確定着順'], row['頭数']), 3),
                'クラス倍率':   CLASS_WEIGHTS.get(cn, 0.6),
                '近接度':       recency_weight(i + 1),
                '時計使用':     used_in_dev,
            })

        past_races_map[h] = past_race_list

        time_dev   = float(np.average(dev_vals, weights=dev_ws)) if dev_ws else 0.0
        n_dev_used = len(dev_vals)

        # ── 脚質判定（改善②: 最近2〜3走に重み付け）─────────────────
        weighted_4k = weighted_avg_4kaku(sub)          # 分類用（重み付き）
        # 表示用は単純平均を保持
        legs_all = []
        for _, row in sub.iterrows():
            for p in [row['通過順4角'], row['通過順3角'],
                      row['通過順2角'], row['通過順1角']]:
                if not pd.isna(p) and p > 0:
                    legs_all.append(float(p))
                    break
        avg_4kaku   = np.mean(legs_all) if legs_all else np.nan
        kyakushitsu = classify_脚質(weighted_4k, sub['頭数'].mean())

        # ── 上がり3F ─────────────────────────────────
        avg_agari = sub['上がり3Fタイム'].mean()

        # ── A-2 斤量補正 ──────────────────────────────
        today_w = None
        if shutuba_df is not None:
            row_s = shutuba_df[shutuba_df['馬名'] == h]
            if not row_s.empty:
                v = row_s.iloc[0].get('斤量')
                if v is not None and not pd.isna(v):
                    today_w = float(v)
        kinryo_pts = calc_kinryo_pts(sub, today_weight=today_w)

        # ── A-3 距離適性補正 ─────────────────────────
        kyori_pts = calc_kyori_pts(sub, target_dist=target_dist,
                                   horse_name=h, shutuba_df=shutuba_df,
                                   target_surface=target_surface)

        # ── A-4 コース適性補正 ───────────────────────
        course_apt_pts, avg_sim = calc_course_apt_pts(sub, course_times, target_course)

        # ── A-5 臨戦過程補正 ─────────────────────────
        rinsen_pts = calc_rinsen_pts(sub, race_date=race_date)

        # A-6 PCI補正 → 廃止済み（calc_pci_pts は常に0を返すため呼び出し自体を除去）

        # ── A-7 騎手補正 ─────────────────────────────
        today_jockey = today_jockeys[horses.index(h)]
        jockey_pts   = calc_jockey_pts(
            today_jockey, jockey_scores, jockey_prior, jockey_field_avg
        )

        # ── ④ 馬体重増減補正 ──────────────────────────
        taiju_pts = calc_taiju_pts(h, shutuba_df)

        # ── ⑥ 継続騎乗補正 ──────────────────────────────
        keizoku_pts = calc_keizoku_pts(h, sub, shutuba_df)

        # ── ⑧ 前走着差補正 ──────────────────────────────
        chakusa_pts = calc_chakusa_pts(sub)

        # ── 昇級戦補正 ───────────────────────────────
        shokyu_pts = 0.0
        if today_class_rank > 0 and not sub.empty:
            try:
                prev_cn   = sub.iloc[0]['class_norm']
                prev_rank = CLASS_RANK.get(prev_cn, 0)
                steps_up  = today_class_rank - prev_rank
                if steps_up == 1:
                    shokyu_pts = -1.0
                elif steps_up == 2:
                    shokyu_pts = -2.0
                elif steps_up >= 3:
                    shokyu_pts = -3.0
            except Exception:
                pass

        # ── SmartRC 評価補正 ─────────────────────────
        # h1_fr_baba: 前走の馬場有利不利評価（h2〜h5 で前々走以前）
        #   A/B = 不利を受けた → 実力は結果より高い → 上方修正
        #   C   = 中立（補正なし）
        #   D/E = 有利を受けた → 結果が過大評価の可能性 → 下方修正
        _smartrc_hyoka      = None
        _smartrc_ten_pat    = None
        _smartrc_agari_pat  = None
        _smartrc_pts        = 0.0
        _smartrc_est_pop    = None   # 人気ランク（アルファベット: A/B/C…）
        _smartrc_pop_tan    = None   # 推定人気順（数字: 1/2/3…）
        _smartrc_ten_rank   = None   # テン速度順位 (ten_has_rank)
        _smartrc_agari_rank = None   # 上がり速度順位 (agari_has_rank)
        if smartrc_data:
            # 馬名の全角スペース/半角スペースを吸収して検索
            _src = (smartrc_data.get(h)
                    or smartrc_data.get(h.replace('　', ' '))
                    or smartrc_data.get(h.replace(' ', '　')))
            if _src:
                # h1〜h5_fr_baba を加重平均（前走を最重視）
                # 重み: 前走1.0 / 前々走0.6 / 3走前0.3 / 4走前0.15 / 5走前0.07
                _BABA_WEIGHTS = [1.0, 0.6, 0.3, 0.15, 0.07]
                _baba_fields  = ('h1_fr_baba','h2_fr_baba','h3_fr_baba','h4_fr_baba','h5_fr_baba')
                _total_w, _total_pts = 0.0, 0.0
                _smartrc_hyoka = None   # 表示用（前走の評価文字を保持）
                for _i, _fld in enumerate(_baba_fields):
                    _v = _src.get(_fld)
                    if _v not in (None, '', ' '):
                        _ev = str(_v).strip().upper()
                        if _i == 0:
                            _smartrc_hyoka = _ev   # 前走評価のみ表示用に記録
                        _w = _BABA_WEIGHTS[_i]
                        _total_pts += calc_smartrc_pts(_ev) * _w
                        _total_w   += _w
                # 有効データがない場合は0pt; ある場合は加重平均
                _smartrc_pts = round(_total_pts / _total_w, 2) if _total_w > 0 else 0.0
                _smartrc_ten_pat   = _src.get('ten_pat')   or None
                _smartrc_agari_pat = _src.get('agari_pat') or None
                # 推定人気: est_pop=SmartRC推定人気順(数字), pop_tan=オッズ人気順(数字)
                _smartrc_est_pop   = _src.get('est_pop')   or None  # SmartRC推定人気順(数字)
                _smartrc_pop_tan   = _src.get('pop_tan')   or None  # オッズ人気順(数字)
                # テン速度順位・上がり速度順位 (展開予想パネル用)
                _v = _src.get('ten_has_rank')
                _smartrc_ten_rank   = int(_v) if _v not in (None, '', ' ', '  ') else None
                _v = _src.get('agari_has_rank')
                _smartrc_agari_rank = int(_v) if _v not in (None, '', ' ', '  ') else None
                if _smartrc_hyoka:
                    print(f"    [SmartRC] {h}: 評価={_smartrc_hyoka} "
                          f"({'+' if _smartrc_pts >= 0 else ''}{_smartrc_pts:+.1f}pt)"
                          f"  推定人気={_smartrc_est_pop}({_smartrc_pop_tan}位)")

        # ── C-3 調教評価 ─────────────────────────────
        # 調教ptsとしての直接加算は廃止済み。
        # ただし長期休養×好調教の臨戦ペナルティ緩和（A-5×C-3）には引き続き活用。
        training_pt = training_pts_map.get(h, 0.0)
        t_info      = training_info_map.get(h, {})

        # ── 長期休養×好調教 補正緩和 (A-5×C-3) ────────
        # 57日以上の休養かつ調教スコアが正値のとき、臨戦ペナルティを最大70%緩和
        if rinsen_pts <= -2 and training_pt > 0:
            mitigation = min(training_pt, abs(rinsen_pts) * 0.7)
            rinsen_pts = rinsen_pts + mitigation

        # ── 出馬表フィールド初期値 ────────────────────
        no_past_data = sub.empty

        if no_past_data:
            # 過去走なし（新馬・初出走等）: 出馬表から基本情報を取得
            _srows = (shutuba_df[shutuba_df['馬名'] == h]
                      if shutuba_df is not None else pd.DataFrame())
            _sr = _srows.iloc[0] if not _srows.empty else pd.Series(dtype=object)
            def _sg(col, default=''):
                v = _sr.get(col, default)
                return default if (v is None or str(v) in ('nan', 'None', '')) else v
            _sei        = str(_sg('性別', '不明'))
            try: _age   = int(_sg('年齢', 0))
            except (ValueError, TypeError): _age = 0
            _chichi     = str(_sg('父馬名', ''))
            _hahachichi = str(_sg('母の父馬名', ''))
            _jockey_fb  = str(_sg('騎手', ''))
            _jinki      = None
            _odds       = None
        else:
            latest      = sub.iloc[0]
            _sei        = latest['性別']
            try: _age   = int(latest['年齢'])
            except (ValueError, TypeError): _age = 0
            _chichi     = str(latest['父馬名'])
            _hahachichi = str(latest['母の父馬名'])
            _jockey_fb  = str(latest['騎手'])
            _jinki      = latest.get('人気')
            _odds       = latest.get('単勝オッズ')

        results.append({
            '馬名':             h,
            '性別':             _sei,
            '年齢':             _age,
            '騎手':             today_jockey or _jockey_fb,
            '父馬名':           _chichi,
            '母の父馬名':        _hahachichi,
            '過去走なし':        no_past_data,
            '出走数':           n_races,
            '補正タイム最良':    best_hosei,
            'クラス補正着順':    class_corrected,
            'タイム偏差秒':      time_dev,
            'タイム偏差利用走数': n_dev_used,
            '平均4角通過順':     avg_4kaku,
            '平均頭数':          (float(sub['頭数'].mean()) if not sub.empty else None),
            '脚質':             kyakushitsu,
            '平均上がり3F':      avg_agari,
            '平均コース類似度':  avg_sim,
            '_kinryo_pts':     kinryo_pts,
            '_kyori_pts':      kyori_pts,
            '_course_apt_pts': course_apt_pts,
            '_rinsen_pts':     rinsen_pts,
            '_jockey_pts':     jockey_pts,
            '_taiju_pts':      taiju_pts,
            '_keizoku_pts':    keizoku_pts,
            '_chakusa_pts':    chakusa_pts,
            '_shokyu_pts':     shokyu_pts,
            '_smartrc_pts':         _smartrc_pts,
            '_smartrc_hyoka':       _smartrc_hyoka,
            '_smartrc_ten_pat':     _smartrc_ten_pat,
            '_smartrc_agari_pat':   _smartrc_agari_pat,
            '_smartrc_est_pop':     _smartrc_est_pop,
            '_smartrc_pop_tan':     _smartrc_pop_tan,
            '_smartrc_ten_rank':    _smartrc_ten_rank,
            '_smartrc_agari_rank':  _smartrc_agari_rank,
            '坂路Lap1':         t_info.get('坂路Lap1'),
            'ウッドLap1':        t_info.get('ウッドLap1'),
            '枠番':    None,
            '馬番':    None,
            '人気':    _jinki,
            '単勝オッズ': _odds,
            '複勝下限':   None,
            '複勝上限':   None,
            '今走斤量': today_w,
        })

    res = pd.DataFrame(results)

    # ── 偏差値 → 点数変換 ─────────────────────────────
    # 最高出力_dev: NaN馬は平均/σ計算から除外し、偏差50.0（平均扱い）を固定代入
    # ※ fillna(mean)方式だとNaN分がσ計算に混入してσが縮小し全馬の偏差が水増しされるため
    _tgx_raw   = res['補正タイム最良'].tolist()
    _tgx_valid = [v for v in _tgx_raw if v is not None and not (isinstance(v, float) and np.isnan(v))]
    if len(_tgx_valid) >= 2:
        _tgx_m = float(np.mean(_tgx_valid))
        _tgx_s = float(np.std(_tgx_valid))
    else:
        _tgx_m, _tgx_s = 0.0, 0.0
    if _tgx_s == 0:
        res['最高出力_dev'] = [50.0] * len(_tgx_raw)
    else:
        res['最高出力_dev'] = [
            50.0 if (v is None or (isinstance(v, float) and np.isnan(v)))
            else float((v - _tgx_m) / _tgx_s * 10 + 50)
            for v in _tgx_raw
        ]
    res['クラス_dev']   = deviation_score(res['クラス補正着順'].tolist())
    res['時計_dev']     = deviation_score(res['タイム偏差秒'].tolist())

    def to_points(devs, max_pts):
        return [max(0.0, min(max_pts, (d - 35) / 30 * max_pts)) for d in devs]

    res['最高出力pts'] = to_points(res['最高出力_dev'].tolist(), 30)
    res['クラスpts']   = to_points(res['クラス_dev'].tolist(),   25)
    res['時計pts']     = to_points(res['時計_dev'].tolist(),     20)

    # ── 展開予想（ペース判定・メタ情報用）─────────────────
    leg_count = res['脚質'].value_counts().to_dict()
    nige_cnt  = leg_count.get('逃げ', 0)
    front     = nige_cnt + leg_count.get('先行', 0)
    avg_agari_all = res['平均上がり3F'].mean()

    # SmartRCテン速度競合情報（表示用）
    _ten_ranks_final = res['SmartRCテン速度順位'].dropna().tolist()
    _ten_top3_final  = [r for r in _ten_ranks_final if r <= 3]
    _ten_fast_final  = [r for r in _ten_ranks_final if r <= 5]

    # ペース表記: SmartRC速度競合を優先、なければ脚質頭数ベース
    if _ten_top3_final and len(_ten_top3_final) >= 2:
        # テン速度上位3位以内が複数 → 速度競合でペース上昇
        _competition_note = f'（テン速度競合{len(_ten_top3_final)}頭）'
    elif _ten_fast_final and len(_ten_fast_final) >= 3:
        _competition_note = f'（速度競合あり）'
    else:
        _competition_note = ''

    # today_pace（事前計算済み）をそのまま表記に使用
    if today_pace == 'high':
        pace = f'ハイペース想定{_competition_note}'
    elif today_pace == 'low':
        pace = f'スローペース想定{_competition_note}'
    else:
        pace = f'ミドルペース想定{_competition_note}'

    # 展開pts は枠番確定後（shutuba_df 適用後）に calc_tenkai_pts_all で計算
    res['展開pts'] = 0.0

    # ── 補正項目を列名に昇格 ─────────────────────────
    res['斤量pts']      = res['_kinryo_pts']
    res['距離pts']      = res['_kyori_pts']
    res['コース適性pts'] = res['_course_apt_pts']
    res['臨戦pts']      = res['_rinsen_pts']
    res['騎手pts']      = res['_jockey_pts']
    res['馬体重pts']    = res['_taiju_pts']
    res['継続pts']      = res['_keizoku_pts']
    res['着差pts']      = res['_chakusa_pts']
    res['昇級pts']      = res['_shokyu_pts']
    res['SmartRC評価pts']      = res['_smartrc_pts']
    res['SmartRC評価']         = res['_smartrc_hyoka']
    res['SmartRCテンパターン']   = res['_smartrc_ten_pat']
    res['SmartRC上がりパターン'] = res['_smartrc_agari_pat']
    res['SmartRCテン速度順位']   = res['_smartrc_ten_rank']
    res['SmartRC上がり速度順位'] = res['_smartrc_agari_rank']
    def _est_pop_to_grade(v):
        """est_pop数値(1-10+)からSmartRC人気ランク文字を導出"""
        try:
            n = int(v)
        except (TypeError, ValueError):
            return None
        if n <= 2:   return 'B'
        if n == 3:   return 'C'
        if n <= 9:   return 'D'
        return 'E'
    res['SmartRC推定人気順']    = res['_smartrc_est_pop']   # 数字 (1/2/3…) SmartRC推定
    res['SmartRC人気ランク']    = res['_smartrc_est_pop'].map(_est_pop_to_grade)  # 文字 (B/C/D/E)

    # ── 出馬表データ上書き（馬番確定のため先に実行）──────
    if shutuba_df is not None:
        for idx, row in res.iterrows():
            h     = row['馬名']
            s_row = shutuba_df[shutuba_df['馬名'] == h]
            if s_row.empty: continue
            s = s_row.iloc[0]
            for col in ['騎手', '枠番', '馬番', '人気', '単勝オッズ', '複勝下限', '複勝上限']:
                if col in s and not pd.isna(s[col]):
                    v = s[col]
                    try:
                        if col in ('枠番', '馬番', '人気'): v = int(v)
                        if col in ('単勝オッズ', '複勝下限', '複勝上限'): v = float(v)
                    except (ValueError, TypeError):
                        continue  # '取消し' 等の非数値は無視
                    res.at[idx, col] = v

    # ⑤ 枠番確定後の計算（展開pts・枠順pts）
    num_horses = len(res)

    # 展開pts: ゾーン×ペース×混雑×内枠を総合評価（±4pt）
    res['展開pts'] = calc_tenkai_pts_all(
        res,
        target_course=target_course,
        today_pace=today_pace,
        num_horses=num_horses,
    )

    res['枠順pts'] = res.apply(
        lambda r: calc_wakuban_pts(r['馬番'], r['脚質'], target_course, num_horses),
        axis=1
    )

    # ── 総合スコア ─────────────────────────────────
    res['総合スコア'] = (
        res['最高出力pts'] + res['クラスpts'] + res['時計pts']
        + res['展開pts']
        + res['斤量pts'] + res['距離pts'] + res['コース適性pts']
        + res['臨戦pts'] + res['騎手pts']
        + res['馬体重pts'] + res['継続pts'] + res['着差pts']
        + res['枠順pts'] + res['昇級pts']
        + res['SmartRC評価pts']   # SmartRC 前走有利不利補正
    )
    # スコア下限補正: 最低スコアを1.0にシフト（マイナス表示を防ぐ）
    _min_score = res['総合スコア'].min()
    if _min_score < 1.0:
        res['総合スコア'] = res['総合スコア'] - _min_score + 1.0

    # 出馬表に単勝オッズ列がない場合、過去走から引き継いだオッズをクリア
    # （採算オッズをダッシュボード側で表示するため）
    if shutuba_df is not None and '単勝オッズ' not in shutuba_df.columns:
        res['単勝オッズ'] = None
        res['人気'] = None

    # 人気との乖離補正（出馬表データがある場合のみ）
    # 1〜3番人気馬がモデルスコア中央値を下回る場合に上方補正
    res['人気補正pts'] = 0.0
    if shutuba_df is not None and '単勝オッズ' in shutuba_df.columns:
        _shutuba_odds = shutuba_df[['馬名', '単勝オッズ']].copy()
        _shutuba_odds['単勝オッズ_num'] = pd.to_numeric(_shutuba_odds['単勝オッズ'], errors='coerce')
        _shutuba_odds = (_shutuba_odds.dropna(subset=['単勝オッズ_num'])
                                      .sort_values('単勝オッズ_num')
                                      .reset_index(drop=True))
        _score_median = res['総合スコア'].median()
        _bonus_map = {1: 3.0, 2: 2.0, 3: 1.5}
        for ninki_rank, row_s in _shutuba_odds.iterrows():
            if ninki_rank >= 3:
                break
            name = str(row_s['馬名']).strip()
            mask = res['馬名'] == name
            if mask.sum() == 0:
                continue
            idx = res[mask].index[0]
            model_score = res.at[idx, '総合スコア']
            if model_score < _score_median:
                bonus = _bonus_map.get(ninki_rank + 1, 0)  # ninki_rank は 0始まり
                res.at[idx, '人気補正pts'] = bonus
                res.at[idx, '総合スコア']  = model_score + bonus

    res['順位予想'] = res['総合スコア'].rank(ascending=False, method='min').astype(int)
    res = res.sort_values('総合スコア', ascending=False).reset_index(drop=True)

    # SmartRC 展開補完: テン/上がりパターンのサマリーを収集
    _src_ten  = {}  # ten_pat  → 馬名リスト
    _src_agari = {} # agari_pat → 馬名リスト
    for _, _r in res.iterrows():
        _tp = _r.get('SmartRCテンパターン')
        _ap = _r.get('SmartRC上がりパターン')
        if _tp:
            _src_ten.setdefault(_tp, []).append(_r['馬名'])
        if _ap:
            _src_agari.setdefault(_ap, []).append(_r['馬名'])

    meta = {
        'baba':             baba,
        'pace':             pace,
        'today_pace':       today_pace,
        'leg_count':        leg_count,
        'avg_agari_all':    (float(avg_agari_all) if not pd.isna(avg_agari_all) else None),
        'jockey_prior':     round(jockey_prior, 4),
        'jockey_field_avg': round(jockey_field_avg, 4),
        # SmartRC 展開補完情報（ダッシュボード側で参照可能）
        'smartrc_ten_summary':   _src_ten,
        'smartrc_agari_summary': _src_agari,
    }
    return res, meta, past_races_map


def build_horses_json(res: pd.DataFrame, meta: dict, past_races_map: dict = None) -> dict:
    """DataFrame → horses_data.json 用 dict"""
    horses = []
    for _, r in res.iterrows():
        h_name = r['馬名']
        entry = {
            '馬名':            h_name,
            '性別':            r['性別'],
            '年齢':            int(r['年齢']),
            '騎手':            str(r['騎手']),
            '父馬名':          str(r['父馬名']),
            '母の父馬名':       str(r['母の父馬名']),
            '出走数':          int(r['出走数']),
            '過去走なし':       bool(r.get('過去走なし', False)),
            '枠番':            (int(r['枠番'])  if r['枠番']  is not None and not pd.isna(r['枠番'])  else None),
            '馬番':            (int(r['馬番'])  if r['馬番']  is not None and not pd.isna(r['馬番'])  else None),
            '人気':            (int(r['人気'])  if r['人気']  is not None and not pd.isna(r['人気'])  else None),
            '単勝オッズ':       (float(r['単勝オッズ']) if r['単勝オッズ'] is not None and not pd.isna(r['単勝オッズ']) else None),
            '複勝下限':         (float(r['複勝下限'])   if r['複勝下限']   is not None and not pd.isna(r['複勝下限'])   else None),
            '複勝上限':         (float(r['複勝上限'])   if r['複勝上限']   is not None and not pd.isna(r['複勝上限'])   else None),
            '今走斤量':         (float(r['今走斤量']) if r['今走斤量'] is not None and not pd.isna(r['今走斤量']) else None),
            '順位予想':         int(r['順位予想']),
            '総合スコア':       round(float(r['総合スコア']), 1),
            '最高出力pts':      round(float(r['最高出力pts']), 1),
            'クラスpts':        round(float(r['クラスpts']), 1),
            '時計pts':          round(float(r['時計pts']), 1),
            '展開pts':          int(round(float(r['展開pts']))),
            '斤量pts':          round(float(r['斤量pts']), 1),
            '距離pts':          round(float(r['距離pts']), 1),
            'コース適性pts':    round(float(r['コース適性pts']), 1),
            '臨戦pts':          round(float(r['臨戦pts']), 1),
            '人気補正pts':       round(float(r.get('人気補正pts', 0)), 1),
            '騎手pts':          round(float(r['騎手pts']), 1),
            '馬体重pts':        round(float(r['馬体重pts']), 1),
            '継続pts':          round(float(r['継続pts']), 1),
            '着差pts':          round(float(r['着差pts']), 1),
            '枠順pts':          round(float(r.get('枠順pts', 0)), 1),
            '昇級pts':          round(float(r.get('昇級pts', 0)), 1),
            'SmartRC評価pts':   round(float(r.get('SmartRC評価pts', 0)), 1),
            'SmartRC評価':      r.get('SmartRC評価'),          # A/B/C/D/E or None
            'SmartRCテンパターン':   r.get('SmartRCテンパターン'),
            'SmartRC上がりパターン': r.get('SmartRC上がりパターン'),
            'SmartRC人気ランク':  r.get('SmartRC人気ランク'),   # アルファベット
            'SmartRC推定人気順':  r.get('SmartRC推定人気順'),   # 数字
            'SmartRCテン速度順位':  (int(r['SmartRCテン速度順位'])  if r.get('SmartRCテン速度順位')  is not None and not pd.isna(r['SmartRCテン速度順位'])  else None),
            'SmartRC上がり速度順位': (int(r['SmartRC上がり速度順位']) if r.get('SmartRC上がり速度順位') is not None and not pd.isna(r['SmartRC上がり速度順位']) else None),
            '脚質':             r['脚質'],
            '補正タイム最良':    (round(float(r['補正タイム最良']), 0) if not pd.isna(r['補正タイム最良']) else None),
            '平均上がり3F':     (round(float(r['平均上がり3F']), 1)  if not pd.isna(r['平均上がり3F'])  else None),
            '平均4角通過順':    (round(float(r['平均4角通過順']), 1)  if not pd.isna(r['平均4角通過順'])  else None),
            '平均コース類似度':  round(float(r['平均コース類似度']), 2),
            'タイム偏差利用走数': int(r['タイム偏差利用走数']),
            '坂路Lap1':         (round(float(r['坂路Lap1']), 2)   if r['坂路Lap1']  is not None and not pd.isna(r['坂路Lap1'])  else None),
            'ウッドLap1':       (round(float(r['ウッドLap1']), 2) if r['ウッドLap1'] is not None and not pd.isna(r['ウッドLap1']) else None),
            'past_races':       (past_races_map.get(h_name, []) if past_races_map else []),
        }
        horses.append(entry)
    return {'horses': horses, 'meta': meta}


# ─────────────────────────────────────────────────────────────────────────────
# CLI エントリーポイント
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import sys, argparse

    COLS = ['年','月','日','回次','場所','日次','レース番号','レース名',
            'クラス名','芝・ダ','トラックコード','距離','コーナー回数',
            'コース区分','馬場状態','馬名','性別','年齢','騎手',
            '斤量','頭数','枠番','馬番','確定着順','着差タイム',
            '人気','単勝オッズ','走破タイム秒','タイムS','補正タイム',
            '通過順1角','通過順2角','通過順3角','通過順4角',
            '上がり3Fタイム','馬体重','父馬名','母馬名','母の父馬名','PCI']

    ap = argparse.ArgumentParser()
    import os as _os
    _SCRIPT_DIR = _os.path.dirname(_os.path.abspath(__file__))
    ap.add_argument('--excel',   default='サンプル6.xlsx')
    ap.add_argument('--course',  default=_os.path.join(_SCRIPT_DIR, 'course_times_full_new.json'))
    ap.add_argument('--shutuba', default=None)
    ap.add_argument('--sakuro',  default=None)
    ap.add_argument('--wood',    default=None)
    ap.add_argument('--baba',    default='良',
                    choices=['良','稍重','重','不良'],
                    help='馬場状態（デフォルト:良）')
    ap.add_argument('--smartrc', default=None,
                    help='SmartRC JSON ファイルパス (smartrc_fetch.py --out で生成)')
    ap.add_argument('--outdir',  default=None,
                    help='出力ディレクトリ（省略時はスクリプトと同じディレクトリ）')
    args = ap.parse_args()
    _outdir = args.outdir if args.outdir else _SCRIPT_DIR

    # ── CSV / Excel 自動判定ヘルパー ─────────────────────────────
    def _read_df(path, **kwargs):
        """
        拡張子が .csv / .tsv なら pd.read_csv（encoding=cp932）、
        それ以外（.xlsx / .xls）なら pd.read_excel で読み込む。
        TARGETからのCSV直接出力に対応。
        ラギッドCSV（行ごとカラム数不揃い）もPythonのcsvモジュールで処理。
        """
        import csv as _csv_mod
        ext = _os.path.splitext(path)[1].lower()
        if ext in ('.csv', '.tsv'):
            sep = '\t' if ext == '.tsv' else ','
            enc = kwargs.pop('encoding', 'cp932')
            kwargs.pop('sheet_name', None)
            try:
                return pd.read_csv(path, sep=sep, encoding=enc, **kwargs)
            except UnicodeDecodeError:
                try:
                    return pd.read_csv(path, sep=sep, encoding='utf-8-sig', **kwargs)
                except pd.errors.ParserError:
                    pass
            except pd.errors.ParserError:
                pass
            # フォールバック: ラギッドCSV（行ごとにカラム数が異なる）対応
            header_arg = kwargs.get('header', 0)
            rows = []
            for enc2 in [enc, 'utf-8-sig', 'utf-8']:
                try:
                    with open(path, encoding=enc2, newline='', errors='replace') as _f:
                        rows = list(_csv_mod.reader(_f, delimiter=sep))
                    break
                except Exception:
                    continue
            if not rows:
                return pd.DataFrame()
            max_cols = max(len(r) for r in rows)
            padded = [r + [''] * (max_cols - len(r)) for r in rows]
            if header_arg is None:
                df = pd.DataFrame(padded)
            elif isinstance(header_arg, int) and header_arg < len(padded):
                cols = padded[header_arg]
                data_rows = padded[header_arg + 1:]
                df = pd.DataFrame(data_rows, columns=cols)
            else:
                df = pd.DataFrame(padded)
            # 空文字をNaNに変換し、数値カラムを推論
            df = df.replace('', float('nan'))
            for col in df.columns:
                _orig = df[col].copy()
                _converted = pd.to_numeric(df[col], errors='coerce')
                # 変換できなかったセル（NaN になったが元はNaNでなかった）は元の値を保持
                df[col] = _converted.where(_converted.notna() | _orig.isna(), _orig)
            return df
        else:
            return pd.read_excel(path, **kwargs)

    df = _read_df(args.excel, header=None, names=COLS)
    with open(args.course, encoding='utf-8') as f:
        course_times = json.load(f)

    shutuba_df = None
    sakuro_df  = None
    wood_df    = None

    if args.shutuba:
        # Excelレイアウト: 行0=列ヘッダ(年/月/日...) / 行1=レース情報値 / 行2=馬列ヘッダ / 行3+=馬データ
        _raw = _read_df(args.shutuba, sheet_name=0, header=None)
        race_info_row = _raw.iloc[1]   # ← 行1がレース情報（行0は項目名）
        _race_info = {
            '年':    str(int(race_info_row[0])),
            '月':    str(race_info_row[1]).zfill(2),
            '日':    str(int(race_info_row[2])).zfill(2),
            '場所':  str(race_info_row[3]),
            'R':     str(race_info_row[4]),
            'レース名': str(race_info_row[5]).strip(),
            'クラス名': str(race_info_row[6]).strip(),
            '芝ダ':  str(race_info_row[11]).strip(),
            '距離':  int(race_info_row[12]),
            'コーナー回数': int(race_info_row[13]) if pd.notna(race_info_row[13]) else 0,
            '頭数':  int(race_info_row[14]),
        }
        shutuba_df = _read_df(args.shutuba, sheet_name=0, header=2)
        # 列名の前後スペース・改行を除去してから処理
        shutuba_df.columns = [str(c).split('\n')[0].strip() for c in shutuba_df.columns]
        if '馬名S' in shutuba_df.columns and '馬名' not in shutuba_df.columns:
            shutuba_df = shutuba_df.rename(columns={'馬名S': '馬名'})
        if '番' in shutuba_df.columns and '馬番' not in shutuba_df.columns:
            shutuba_df = shutuba_df.rename(columns={'番': '馬番'})
        # 列名の揺れを吸収（単勝・増減など）
        col_map = {'単勝': '単勝オッズ', '増減': '馬体重増減_raw'}
        shutuba_df = shutuba_df.rename(columns={k: v for k, v in col_map.items() if k in shutuba_df.columns})
        shutuba_df = shutuba_df[shutuba_df['馬名'].notna()].copy()
        shutuba_df['馬名'] = shutuba_df['馬名'].astype(str).str.strip()

    if args.sakuro:
        sakuro_df = _read_df(args.sakuro, sheet_name=0)

    if args.wood:
        wood_df = _read_df(args.wood, sheet_name=0)

    # 出馬表から実際のレース日・コース・距離を取得
    if args.shutuba:
        _rd          = date(int(float(_race_info['年'])), int(float(_race_info['月'])), int(float(_race_info['日'])))
        _target_dist = int(float(_race_info.get('距離', TARGET_DIST)))
        _shida       = str(_race_info.get('芝ダ', '芝')).strip()
        _surface     = 'ダート' if _shida in ('ダ', 'ダート') else '芝'
        _venue       = str(_race_info.get('場所', '')).strip()
        _num_corners = int(float(_race_info.get('コーナー回数', 0) or 0))
        _target_class_tmp = _race_info.get('クラス名', '')
        if _venue:
            _io_suffix = _get_inner_outer(_venue, _surface, _target_dist,
                                          _num_corners, _target_class_tmp)
            _candidate = f"{_venue}{_surface}{_target_dist}m{_io_suffix}"
            # COURSE_FEATURESにキーがあればサフィックス付き、なければベースキーを使用
            _base_key     = f"{_venue}{_surface}{_target_dist}m"
            _target_course = _candidate if _candidate in COURSE_FEATURES else _base_key
        else:
            _target_course = f"東京芝{_target_dist}m"

        # 回りをCOURSE_FEATURESから取得してrace_infoに付加
        _mawari = COURSE_FEATURES.get(_target_course, {}).get('回り', '左')
        _race_info['回り'] = _mawari

    else:
        # 出馬表なし: デフォルト値を使用
        _rd            = RACE_DATE
        _target_dist   = TARGET_DIST
        _target_course = TARGET_COURSE
        _race_info     = {}
        _mawari = COURSE_FEATURES.get(_target_course, {}).get('回り', '左')

    _target_class = _race_info.get('クラス名', '') if args.shutuba else ''

    # SmartRC データ読み込み
    smartrc_data = None
    if args.smartrc:
        smartrc_data = load_smartrc_data(args.smartrc)

    # ── スコア計算 ─────────────────────────────────────────────────────
    res, meta, past_races_map = compute_scores(
        df, course_times,
        shutuba_df=shutuba_df,
        sakuro_df=sakuro_df,
        wood_df=wood_df,
        race_date=_rd,
        target_dist=_target_dist,
        target_course=_target_course,
        baba=args.baba,
        target_class=_target_class,
        smartrc_data=smartrc_data,
    )

    # race_info を meta に付加（build_dashboard_v3.py が参照）
    meta['race_info'] = _race_info

    # ── JSON 出力 ───────────────────────────────────────────────────────
    import os as _os2
    out_data = build_horses_json(res, meta, past_races_map)
    out_json = _os2.path.join(_outdir, 'horses_data.json')
    with open(out_json, 'w', encoding='utf-8') as _f:
        json.dump(out_data, _f, ensure_ascii=False, indent=2)
    print(f'\n[完了] {out_json} に保存しました')

    # ── スコア CSV 出力 ─────────────────────────────────────────────────
    _score_cols = [
        '馬名', '脚質', '順位予想', '総合スコア',
        '最高出力pts', 'クラスpts', '時計pts', '展開pts',
        '斤量pts', '距離pts', 'コース適性pts', '臨戦pts',
        '人気補正pts', '騎手pts', '馬体重pts', '継続pts', '着差pts',
        '枠順pts', '昇級pts', 'SmartRC評価pts',
    ]
    out_csv = _os2.path.join(_outdir, 'scores.csv')
    res[[c for c in _score_cols if c in res.columns]].to_csv(
        out_csv, index=False, encoding='utf-8-sig'
    )
    print(f'[完了] {out_csv} にスコアCSVを保存しました')

    # ── 上位表示 ────────────────────────────────────────────────────────
    print('\n=== スコア上位 ===')
    _disp_cols = ['馬名', '脚質', '順位予想', '総合スコア']
    print(res[[c for c in _disp_cols if c in res.columns]].head(10).to_string(index=False))
