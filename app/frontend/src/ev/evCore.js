// @ts-check
/**
 * EV（妙味）計算の中核。
 *
 * ここは build_dashboard_v3.py が pred.html に埋め込んでいる JavaScript を
 * **計算内容を1つも変えずに** 取り出したもの。UI（DOM生成）だけを外してある。
 *
 * 重要:
 *   - 数式・定数・分岐は既存と完全に同じ。勝手に「きれいに」しないこと。
 *   - 既存HTML内の実装と結果が一致することを app/tests/ev_parity.mjs で毎回検証する。
 *   - 将来ロジックを更新するときは EV_CORE_VERSION を上げ、
 *     検証で使えるよう保存済みオッズ側にもバージョンが残るようにしてある。
 *
 * 素の JavaScript（.js）で書いてあるのは、ビルドを挟まず Node から直接
 * 読み込んで既存実装と突き合わせられるようにするため。型は evCore.d.ts。
 */

/** ロジックのバージョン。計算を変えたら必ず上げる（保存オッズに記録される）。 */
export const EV_CORE_VERSION = 'v1-2026-07-26'

/** softmax の温度。既存 pred.html は computeEV(20) / renderBets の T=20。 */
export const TEMP = 20

/** 単勝表の大穴補正: 市場確率(1/オッズ)の何倍まで許容するか。 */
export const MAX_RATIO = 3.0

/** 買い目提案の勝率cap。CLAUDE.md の MR=3.0。 */
export const MR = 3.0

/** 相手候補の偏差値差の上限 / 断層カット幅 / 列取捨のバンド。 */
export const PARTNER_DEV_MAX = 20.0
export const PARTNER_GAP = 5.0
export const COL1_BAND = 3.0
export const COL2_BAND = 10.0

// ─────────────────────────────────────────────────────────────
// Harville式 上位k着以内確率（既存 placeProb と同一）
// ─────────────────────────────────────────────────────────────
export function placeProb(probs, idx, k) {
  const pi = probs[idx]
  const n = probs.length
  if (k <= 1) return pi
  let p2 = 0
  for (let j = 0; j < n; j++) {
    if (j === idx) continue
    p2 += probs[j] * pi / Math.max(1e-9, 1 - probs[j])
  }
  if (k <= 2) return Math.min(1, pi + p2)
  let p3 = 0
  for (let j = 0; j < n; j++) {
    if (j === idx) continue
    for (let m = 0; m < n; m++) {
      if (m === idx || m === j) continue
      const d = 1 - probs[j] - probs[m]
      if (d <= 0) continue
      p3 += probs[j] * (probs[m] / Math.max(1e-9, 1 - probs[j])) * (pi / d)
    }
  }
  return Math.min(1, pi + p2 + p3)
}

// ─────────────────────────────────────────────────────────────
// 勝率（2種類ある。既存の差異をそのまま維持すること）
// ─────────────────────────────────────────────────────────────

/**
 * 期待値シミュレーター用の勝率（既存 computeEV の前半）。
 * 参考(地方実績のみ)馬は exp=0 で分布から除外する。
 */
export function tableWinProbs(evData, temp = TEMP) {
  const scores = evData.map((h) => h['スコア'])
  const maxS = Math.max(...scores)
  const exps = scores.map((s, i) => (evData[i]['地方実績のみ'] ? 0 : Math.exp((s - maxS) / temp)))
  const sumExp = exps.reduce((a, b) => a + b, 0)
  const rawProbs = exps.map((e) => e / sumExp)

  // 大穴補正: 単勝オッズoの馬の市場確率は約1/o。その MAX_RATIO 倍を超えさせない。
  const dampedProbs = rawProbs.map((p, i) => {
    const o = evData[i]['オッズ']
    if (!o || o <= 0) return p
    const marketProb = 1.0 / o
    return Math.min(p, marketProb * MAX_RATIO)
  })
  const sumDamped = dampedProbs.reduce((a, b) => a + b, 0)
  return dampedProbs.map((p) => p / sumDamped)
}

/**
 * 買い目提案用の勝率（既存 _betWinProbs）。
 * こちらは softmax の段階では地方馬を除外せず、勝率cap後に候補から外す。
 * 表用(tableWinProbs)との差異は既存仕様。合わせにいかないこと。
 */
export function betWinProbs(evData, temp = TEMP) {
  const scores = evData.map((h) => h['スコア'])
  const maxS = Math.max.apply(null, scores)
  const exps = scores.map((s) => Math.exp((s - maxS) / temp))
  const sum = exps.reduce((a, b) => a + b, 0)
  let probs = exps.map((e) => e / sum)
  probs = probs.map((p, i) => {
    const o = evData[i]['オッズ']
    if (!o || o <= 0) return p
    return Math.min(p, (1 / o) * MR)
  })
  const s2 = probs.reduce((a, b) => a + b, 0)
  return probs.map((p) => p / s2)
}

// ─────────────────────────────────────────────────────────────
// 期待値シミュレーターの行（既存 computeEV の後半 + renderRows の判定）
// ─────────────────────────────────────────────────────────────

/**
 * 単勝/複勝タブの行を作る。
 * userOdds は「馬番 -> 手入力オッズ」。未入力の馬は採算オッズ(1/勝率)で初期化される
 * （既存と同じ。EVが0付近から始まる）。この関数は userOdds を書き換える。
 */
export function tableRows(evData, { tab = 'tansho', userOdds = {} } = {}) {
  const winProbs = tableWinProbs(evData)
  const isFuku = tab === 'fukusho'
  return evData.map((h, i) => {
    const prob = isFuku ? placeProb(winProbs, i, 3) : winProbs[i]
    const rawOdds = isFuku ? h['複勝下限'] : h['オッズ']
    if (!isFuku && userOdds[h['馬番']] == null && prob > 0) {
      userOdds[h['馬番']] = Math.round((1 / prob) * 10) / 10
    }
    const odds = (!isFuku && userOdds[h['馬番']] != null) ? userOdds[h['馬番']] : rawOdds
    const ev = (odds !== null && odds !== undefined) ? prob * odds - 1.0 : undefined
    const isLocal = !!h['地方実績のみ']
    const isDark = !!h['is_dark']

    let judgement = '-'
    let cls = 'ev-neutral'
    if (isLocal) {
      judgement = '📎 参考'
    } else if (ev !== undefined && ev !== null) {
      if (ev > 0.05) { cls = 'ev-positive'; judgement = isDark ? '⚠ 大穴注意' : '◎ 買い' }
      else if (ev >= -0.1) { cls = 'ev-neutral'; judgement = '△ 様子見' }
      else { cls = 'ev-negative'; judgement = '✕ 見送り' }
    }
    return {
      ...h,
      _prob: prob,
      _ev: ev,
      _isDark: isDark,
      _isLocal: isLocal,
      _breakEven: (!isFuku && prob > 0) ? 1 / prob : null,
      _odds: odds,
      _judgement: judgement,
      _cls: cls,
    }
  })
}

// ─────────────────────────────────────────────────────────────
// 組み合わせ（既存 _permK / _combK）
// ─────────────────────────────────────────────────────────────
export function permK(arr, k) {
  const r = []
  function go(cur, rest) {
    if (cur.length === k) { r.push(cur.slice()); return }
    for (let i = 0; i < rest.length; i++) {
      go(cur.concat([rest[i]]), rest.slice(0, i).concat(rest.slice(i + 1)))
    }
  }
  go([], arr)
  return r
}

export function combK(arr, k) {
  const r = []
  function go(s, cur) {
    if (cur.length === k) { r.push(cur.slice()); return }
    for (let i = s; i < arr.length; i++) { cur.push(arr[i]); go(i + 1, cur); cur.pop() }
  }
  go(0, [])
  return r
}

// ─────────────────────────────────────────────────────────────
// 買い目提案（既存 renderBets の計算部分）
// ─────────────────────────────────────────────────────────────

/**
 * 軸・相手・列取捨・購入推奨ゲートを決める。
 * 軸は「勝率cap後の1位」であってスコア1位ではない（CLAUDE.md の仕様）。
 */
export function buildBetPlan(evData, temp = TEMP) {
  const wp = betWinProbs(evData, temp)
  const allSc = evData.map((h) => h['スコア'])
  const mean = allSc.reduce((a, b) => a + b, 0) / (allSc.length || 1)
  const sd = Math.sqrt(allSc.reduce((a, b) => a + (b - mean) * (b - mean), 0) / (allSc.length || 1)) || 1

  let arr = evData.map((h, i) => ({
    name: h['馬名'],
    uma: h['馬番'],
    idx: i,
    p: wp[i],
    rank: h['順位予想'],
    src: h['SmartRC推定人気順'],
    local: !!h['地方実績のみ'],
    dev: 50 + 10 * (h['スコア'] - mean) / sd,
  })).filter((x) => x.p > 0 && x.uma != null && !x.local)
  arr.sort((a, b) => b.p - a.p)
  arr = arr.slice(0, 8)

  if (arr.length < 2) {
    return { ok: false, reason: 'データ不足', wp }
  }

  const names = arr.map((x) => x.name)
  const pv = {}, um = {}, dv = {}, sc = {}, gi = {}, ro = {}
  arr.forEach((x) => { pv[x.name] = x.p; um[x.name] = x.uma; dv[x.name] = x.dev; sc[x.name] = x.src; gi[x.name] = x.idx; ro[x.name] = x.rank })

  // 三連単の順序付き確率（Harville）
  const o3 = {}
  permK(names, 3).forEach((seq) => {
    let rem = 1, pr = 1
    for (let i = 0; i < seq.length; i++) {
      if (rem <= 1e-9) { pr = 0; break }
      pr *= pv[seq[i]] / rem
      rem -= pv[seq[i]]
    }
    o3[seq.join('|')] = pr
  })

  const A = arr[0].name
  const wA = pv[A]
  const srcA = (sc[A] != null) ? Number(sc[A]) : 99

  const n_run = evData.filter((h) => h['馬番'] != null).length
  const cand = names.filter((n) => n !== A && (dv[A] - dv[n]) <= PARTNER_DEV_MAX)
  cand.sort((a, b) => dv[b] - dv[a])
  const cap = Math.min(6, Math.floor(n_run / 3))

  const partners = []
  let prev = null
  for (let pi = 0; pi < cand.length; pi++) {
    if (partners.length >= cap) break
    const pn = cand[pi]
    if (partners.length > 0 && (prev - dv[pn]) > PARTNER_GAP) break
    partners.push(pn)
    prev = dv[pn]
  }
  const contend = [A].concat(partners)

  let col1 = [A].concat(partners.filter((n) => (dv[A] - dv[n]) <= COL1_BAND)).slice(0, 3)
  const headFixed = (col1.length === 1)
  let col2 = (headFixed ? [] : [A]).concat(partners.filter((n) => (dv[A] - dv[n]) <= COL2_BAND))
  let col3 = (headFixed ? [] : [A]).concat(partners.slice())

  // 購入推奨ゲート（全条件AND / 推定人気ベース）
  const pop = (n) => (sc[n] != null ? Number(sc[n]) : 99)
  const ktAxis = (evData[gi[A]] || {})['コース特徴pts']
  const top3 = contend.filter((n) => { const p = pop(n); return p === 1 || p === 2 || p === 3 }).length
  const c1 = top3 <= 2
  const c2 = (pop(A) !== 1 && pop(A) !== 2) || partners.every((n) => { const p = pop(n); return !(p === 1 || p === 2 || p === 3 || p === 4) })
  const c3 = (ktAxis != null && Number(ktAxis) > 0)
  const popsCt = contend.map(pop)
  const only123 = popsCt.every((p) => p === 1 || p === 2 || p === 3)
  const all123in = [1, 2, 3].every((r) => popsCt.indexOf(r) >= 0)
  const c4 = !(only123 || all123in)
  const buy = (partners.length >= 1 && c1 && c2 && c3 && c4)

  const ktStr = (ktAxis != null ? ((Number(ktAxis) > 0 ? '+' : '') + Number(ktAxis).toFixed(1)) : '-')
  const reason = buy
    ? `軸${um[A]}番(推定${srcA < 99 ? srcA + '番人気' : '-'}/コース特徴pts${ktStr})・相手${partners.length}頭。`
      + `①1-3番人気${top3}頭(≤2) ②${(pop(A) <= 2) ? '軸が人気で相手に1-4番人気なし' : '軸は3番人気以下'}`
      + ` ③コース特徴pts>0 ④1-3番人気のみ/総取りでない を全て満たす＝妙味あり`
    : `軸${um[A]}番。` + ((partners.length < 1) ? '相手不在'
      : ((!c3) ? '軸のコース特徴pts≤0'
        : ((!c1) ? '1-3番人気が3頭以上'
          : ((!c2) ? '軸1/2番人気なのに相手に1-4番人気を含む'
            : ((!c4) ? 'フォーメーションが1-3番人気のみ/1-3番人気を総取り' : '条件不成立')))))
      + '＝妙味の条件を満たさず'

  // 表示は各列とも馬番の若い順
  const byUma = (a, b) => um[a] - um[b]
  col1 = col1.slice().sort(byUma)
  col2 = col2.slice().sort(byUma)
  col3 = col3.slice().sort(byUma)

  // スコア1位と軸がずれた場合の注記材料（既存と同じ条件）
  const scArr = evData.filter((h) => h['馬番'] != null && !h['地方実績のみ'])
  const scTop = scArr.length ? scArr.reduce((a, b) => (b['スコア'] > a['スコア'] ? b : a)) : null
  const axisDiffersFromScoreTop = !!(scTop && scTop['馬名'] !== A)

  return {
    ok: true,
    wp, o3, pv, um, dv, sc, gi, ro,
    axis: A,
    axisUma: um[A],
    axisWin: wA,
    axisDev: dv[A],
    axisPop: srcA,
    partners, contend, col1, col2, col3,
    buy, reason,
    axisDiffersFromScoreTop,
    scoreTop: scTop,
    names,
  }
}

/** フォーメーション（券種ごと）。既存 renderBets の _betMode='form'。 */
export function formationBets(plan) {
  if (!plan.ok) return []
  const { pv, um, o3, col1, col2, col3, axis: A } = plan
  const uren = col2.filter((n) => n !== A)
  const wd = col3.filter((n) => n !== A)

  let P_uren = 0
  uren.forEach((o) => { P_uren += pv[A] * pv[o] / (1 - pv[A]) + pv[o] * pv[A] / (1 - pv[o]) })

  let P_wide = 0
  for (const kw in o3) {
    const ss = kw.split('|')
    if (ss.indexOf(A) >= 0 && wd.some((o) => ss.indexOf(o) >= 0)) P_wide += o3[kw]
  }

  const trios = combK(wd, 2)
  let P_3p = 0
  trios.forEach((c) => { permK([A, c[0], c[1]], 3).forEach((seq) => { P_3p += o3[seq.join('|')] || 0 }) })

  let utanCnt = 0, P_utan = 0
  col1.forEach((i) => { col2.forEach((j) => { if (i !== j) { utanCnt++; P_utan += pv[i] * pv[j] / (1 - pv[i]) } }) })

  let stanCnt = 0, P_3t = 0
  col1.forEach((i) => {
    col2.forEach((j) => {
      col3.forEach((k) => {
        if (i !== j && j !== k && i !== k) { stanCnt++; P_3t += o3[[i, j, k].join('|')] || 0 }
      })
    })
  })

  const uma = (ns) => ns.map((n) => um[n])
  return [
    { bt: '馬連', cols: [[um[A]], uma(uren)], sep: '-', M: uren.length, P: P_uren },
    { bt: 'ワイド', cols: [[um[A]], uma(wd)], sep: '-', M: wd.length, P: P_wide },
    { bt: '馬単', cols: [uma(col1), uma(col2)], sep: '→', M: utanCnt, P: P_utan },
    { bt: '三連複', cols: [[um[A]], uma(wd)], sep: '-', M: trios.length, P: P_3p },
    { bt: '三連単', cols: [uma(col1), uma(col2), uma(col3)], sep: '→', M: stanCnt, P: P_3t },
  ].map((f) => ({ ...f, key: betKeyFormation(f), status: f.M < 1 ? 'no_partner' : (f.M > 30 ? 'too_many' : 'ok') }))
}

/** 内訳（1点ずつ）。既存 renderBets の _betMode='detail'。 */
export function detailBets(plan) {
  if (!plan.ok) return []
  const { pv, um, o3, col1, col2, col3, axis: A } = plan
  const rows = []
  const uren2 = col2.filter((n) => n !== A)
  const wd2 = col3.filter((n) => n !== A)

  uren2.map((o) => ({ o, p: pv[A] * pv[o] / (1 - pv[A]) + pv[o] * pv[A] / (1 - pv[o]) }))
    .sort((a, b) => b.p - a.p)
    .forEach((x) => { rows.push(['馬連', [um[A], um[x.o]].sort((p, q) => p - q), '-', x.p]) })

  col1.forEach((i) => { col2.forEach((j) => { if (i !== j) rows.push(['馬単', [um[i], um[j]], '→', pv[i] * pv[j] / (1 - pv[i])]) }) })

  wd2.map((o) => {
    let t = 0
    for (const k in o3) { const ss = k.split('|'); if (ss.indexOf(A) >= 0 && ss.indexOf(o) >= 0) t += o3[k] }
    return { o, p: t }
  }).sort((a, b) => b.p - a.p)
    .forEach((x) => { rows.push(['ワイド', [um[A], um[x.o]].sort((p, q) => p - q), '-', x.p]) })

  combK(wd2, 2).map((c) => {
    let t = 0
    permK([A, c[0], c[1]], 3).forEach((seq) => { t += o3[seq.join('|')] || 0 })
    return { c: [um[A], um[c[0]], um[c[1]]].sort((p, q) => p - q), p: t }
  }).sort((a, b) => b.p - a.p)
    .forEach((x) => { rows.push(['三連複', x.c, '-', x.p]) })

  const st = []
  col1.forEach((i) => {
    col2.forEach((j) => {
      col3.forEach((k) => { if (i !== j && j !== k && i !== k) st.push({ c: [um[i], um[j], um[k]], p: o3[[i, j, k].join('|')] || 0 }) })
    })
  })
  st.sort((a, b) => b.p - a.p)
  st.forEach((x) => { rows.push(['三連単', x.c, '→', x.p]) })

  return rows.map((r) => ({ bt: r[0], uma: r[1], sep: r[2], P: r[3], M: 1, key: `${r[0]}|${r[1].join(r[2])}` }))
}

/** 買い目キー（既存と同じ文字列。保存したオッズを将来の検証で突き合わせるため変えないこと）。 */
export function betKeyFormation(f) {
  return f.bt + '|' + f.cols.map((c) => c.join(',')).join(f.sep)
}

/** 的中率と入力オッズから採算オッズ・EV・判定を出す（既存 _evCell）。 */
export function evCell(P, odds) {
  const Pc = (P > 1 ? 1 : P)   // 的中率は100%上限
  const be = Pc > 0 ? (1 / Pc) : 0
  let ev = null, cls = '', judge = ''
  if (odds != null && odds > 0 && Pc > 0) {
    const e = odds * Pc - 1
    ev = e
    if (e > 0.05) { cls = 'ev-positive'; judge = '◎ 妙味' }
    else if (e >= -0.1) { cls = 'ev-neutral'; judge = '△' }
    else { cls = 'ev-negative'; judge = '✕' }
  }
  return { hitRate: Pc, breakEven: be, ev, cls, judge }
}
