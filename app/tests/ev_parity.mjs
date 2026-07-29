// @ts-check
/**
 * EVパリティ検証。
 *
 * 既存 pred.html に埋め込まれている JavaScript **そのもの** を取り出して
 * Node 上で実行し、移植版 app/frontend/src/ev/evCore.js の結果と突き合わせる。
 *
 * これが通る限り「移植でズレた」「既存を直して移植側が置き去りになった」は起きない。
 *
 * 使い方（通常は run_tests.bat から pytest 経由で呼ばれる）:
 *   node app/tests/ev_parity.mjs <pred.htmlのパス> [...]
 * 結果は JSON で標準出力に出す。
 */
import fs from 'node:fs'
import vm from 'node:vm'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const core = await import(
  pathToFileURL(path.join(__dirname, '..', 'frontend', 'src', 'ev', 'evCore.js')).href
)

// ── 既存HTMLから関数の元ソースを切り出す ──────────────────────────
/** function NAME( ... ) { ... } を波かっこの対応で正確に切り出す。 */
function extractFunction(src, name) {
  const head = src.indexOf(`function ${name}(`)
  if (head < 0) throw new Error(`関数が見つかりません: ${name}`)
  const open = src.indexOf('{', head)
  let depth = 0
  let inStr = null
  for (let i = open; i < src.length; i++) {
    const ch = src[i]
    const prev = src[i - 1]
    if (inStr) {
      if (ch === inStr && prev !== '\\') inStr = null
      continue
    }
    if (ch === '"' || ch === "'" || ch === '`') { inStr = ch; continue }
    if (ch === '{') depth++
    else if (ch === '}') {
      depth--
      if (depth === 0) return src.slice(head, i + 1)
    }
  }
  throw new Error(`関数の終端が見つかりません: ${name}`)
}

function extractEvData(html) {
  const m = html.match(/const EV_DATA = (\[[\s\S]*?\]);/)
  if (!m) throw new Error('EV_DATA を取り出せません')
  return JSON.parse(m[1])
}

// ── DOM の代わり（値を捕まえるだけ） ──────────────────────────────
function makeDocumentStub(captured) {
  const el = (id) => {
    if (!captured.els[id]) {
      captured.els[id] = {
        id,
        innerHTML: '',
        textContent: '',
        style: {},
        classList: { toggle() {}, add() {}, remove() {} },
        dataset: {},
      }
    }
    return captured.els[id]
  }
  return {
    getElementById: el,
    querySelectorAll: () => [],
    createElement: () => ({ style: {}, appendChild() {} }),
  }
}

/** 既存実装を走らせて、比べたい値だけ取り出す。 */
function runReference(html) {
  const evData = extractEvData(html)
  const captured = { rows: null, els: {} }

  const sources = [
    extractFunction(html, 'placeProb'),
    extractFunction(html, 'computeEV'),
    extractFunction(html, '_betWinProbs'),
    extractFunction(html, '_permK'),
    extractFunction(html, '_combK'),
    extractFunction(html, '_umaChip'),
    extractFunction(html, '_colHtml'),
    extractFunction(html, '_seqHtml'),
    extractFunction(html, '_evCell'),
    extractFunction(html, 'renderBets'),
  ].join('\n')

  const sandbox = {
    EV_DATA: evData,
    WAKU_BG: { 1: '#ffffff', 2: '#555555', 3: '#ee3333', 4: '#4488ff', 5: '#dddd00', 6: '#22bb22', 7: '#ff8822', 8: '#ffaacc' },
    WAKU_FG: { 1: '#111', 2: '#eee', 3: '#fff', 4: '#fff', 5: '#111', 6: '#fff', 7: '#111', 8: '#111' },
    currentTab: 'tansho',
    _userOdds: {},
    _betOdds: {},
    _betMode: 'form',
    _UMA_WAKU: {},
    document: makeDocumentStub(captured),
    console,
    Math,
    Number,
    JSON,
    __captured: captured,
  }
  vm.createContext(sandbox)

  const prelude = `
    function renderRows(rows) { __captured.rows = rows; }
    EV_DATA.forEach(function(h){ if(h['馬番']!=null) _UMA_WAKU[h['馬番']]=h['枠番']||0; });
  `
  vm.runInContext(prelude + sources, sandbox)

  // 単勝タブ
  vm.runInContext('currentTab="tansho"; _userOdds={}; computeEV(20);', sandbox)
  const tansho = captured.rows.map((r) => ({ uma: r['馬番'], prob: r._prob, ev: r._ev }))
  const tanshoUserOdds = { ...sandbox._userOdds }

  // 複勝タブ
  vm.runInContext('currentTab="fukusho"; computeEV(20);', sandbox)
  const fukusho = captured.rows.map((r) => ({ uma: r['馬番'], prob: r._prob, ev: r._ev }))

  // 買い目（フォーメーション）
  vm.runInContext('currentTab="tansho"; _betMode="form"; renderBets();', sandbox)
  const formHtml = captured.els['betBody'] ? captured.els['betBody'].innerHTML : ''
  const anchorHtml = captured.els['betAnchorInfo'] ? captured.els['betAnchorInfo'].innerHTML : ''
  const badge = captured.els['evRecBadge'] ? captured.els['evRecBadge'].textContent : ''
  const reason = captured.els['evRecReason'] ? captured.els['evRecReason'].textContent : ''

  // 買い目（内訳）
  vm.runInContext('_betMode="detail"; renderBets();', sandbox)
  const detailHtml = captured.els['betBody'] ? captured.els['betBody'].innerHTML : ''

  return { evData, tansho, fukusho, tanshoUserOdds, formHtml, anchorHtml, badge, reason, detailHtml }
}

// ── 既存HTMLの出力から比較用の値を拾う ────────────────────────────
function parseBetRows(html) {
  // <tr><td ...>券種</td> ... <td ...>N点</td><td>P%</td><td ...>be倍</td>
  const rows = []
  const trRe = /<tr>([\s\S]*?)<\/tr>/g
  let m
  while ((m = trRe.exec(html)) !== null) {
    const tds = [...m[1].matchAll(/<td[^>]*>([\s\S]*?)<\/td>/g)].map((x) => x[1])
    if (!tds.length) continue
    const bt = tds[0].replace(/<[^>]+>/g, '').trim()
    const joined = m[1].replace(/<[^>]+>/g, '')
    if (/相手不足/.test(joined)) { rows.push({ bt, status: 'no_partner' }); continue }
    if (/多点数のため非推奨/.test(joined)) { rows.push({ bt, status: 'too_many' }); continue }
    const pts = (tds[2] || '').replace(/<[^>]+>/g, '').trim()
    const hit = (tds[3] || '').replace(/<[^>]+>/g, '').trim()
    const be = (tds[4] || '').replace(/<[^>]+>/g, '').trim()
    const uma = [...(tds[1] || '').matchAll(/>(\d+)<\/span>/g)].map((x) => Number(x[1]))
    rows.push({ bt, status: 'ok', pts, hit, be, uma })
  }
  return rows
}

function parseAxisUma(anchorHtml) {
  // 軸: <span ...>7</span> <b ...>馬名</b>
  const m = anchorHtml.match(/軸:\s*<span[^>]*>(\d+)<\/span>/)
  return m ? Number(m[1]) : null
}

// ── 移植版を同じ形にそろえる ──────────────────────────────────────
function runPort(evData) {
  const userOdds = {}
  const tansho = core.tableRows(evData, { tab: 'tansho', userOdds })
    .map((r) => ({ uma: r['馬番'], prob: r._prob, ev: r._ev }))
  const fukusho = core.tableRows(evData, { tab: 'fukusho', userOdds })
    .map((r) => ({ uma: r['馬番'], prob: r._prob, ev: r._ev }))

  const plan = core.buildBetPlan(evData)
  const form = core.formationBets(plan).map((f) => {
    if (f.status === 'no_partner') return { bt: f.bt, status: 'no_partner' }
    if (f.status === 'too_many') return { bt: f.bt, status: 'too_many' }
    const c = core.evCell(f.P, null)
    return {
      bt: f.bt,
      status: 'ok',
      pts: `${f.M}点`,
      hit: `${(Math.min(f.P, 1) * 100).toFixed(1)}%`,
      be: c.breakEven > 0 ? `${c.breakEven.toFixed(1)}倍` : '-',
      uma: f.cols.flat(),
    }
  })
  const detail = core.detailBets(plan).map((d) => {
    const c = core.evCell(d.P, null)
    return {
      bt: d.bt,
      status: 'ok',
      pts: '1点',
      hit: `${(Math.min(d.P, 1) * 100).toFixed(1)}%`,
      be: c.breakEven > 0 ? `${c.breakEven.toFixed(1)}倍` : '-',
      uma: d.uma,
    }
  })
  return { tansho, fukusho, plan, form, detail, userOdds }
}

// ── 比較 ──────────────────────────────────────────────────────────
const EPS = 1e-9

function cmpNum(a, b) {
  if (a == null && b == null) return true
  if (a == null || b == null) return false
  return Math.abs(a - b) <= EPS * Math.max(1, Math.abs(a), Math.abs(b))
}

function compare(raceId, ref, port) {
  const diffs = []

  const cmpTable = (label, refRows, portRows) => {
    if (refRows.length !== portRows.length) {
      diffs.push(`${label}: 行数 既存${refRows.length} / 移植${portRows.length}`)
      return
    }
    refRows.forEach((r, i) => {
      const p = portRows[i]
      if (r.uma !== p.uma) diffs.push(`${label}[${i}]: 馬番 既存${r.uma} / 移植${p.uma}`)
      if (!cmpNum(r.prob, p.prob)) diffs.push(`${label}[馬番${r.uma}]: 勝率 既存${r.prob} / 移植${p.prob}`)
      if (!cmpNum(r.ev ?? null, p.ev ?? null)) diffs.push(`${label}[馬番${r.uma}]: EV 既存${r.ev} / 移植${p.ev}`)
    })
  }
  cmpTable('単勝表', ref.tansho, port.tansho)
  cmpTable('複勝表', ref.fukusho, port.fukusho)

  // 採算オッズによる初期化値（手入力欄の初期値）
  for (const uma of Object.keys(ref.tanshoUserOdds)) {
    if (!cmpNum(ref.tanshoUserOdds[uma], port.userOdds[uma])) {
      diffs.push(`オッズ初期値[馬番${uma}]: 既存${ref.tanshoUserOdds[uma]} / 移植${port.userOdds[uma]}`)
    }
  }

  // 軸
  const refAxis = parseAxisUma(ref.anchorHtml)
  const portAxis = port.plan.ok ? port.plan.axisUma : null
  if (refAxis !== portAxis) diffs.push(`買い目軸: 既存${refAxis}番 / 移植${portAxis}番`)

  // 購入推奨
  const refBuy = ref.badge.includes('購入推奨') && !ref.badge.includes('非推奨')
  const portBuy = port.plan.ok ? port.plan.buy : false
  if (refBuy !== portBuy) diffs.push(`購入判定: 既存${ref.badge} / 移植${portBuy ? '購入推奨' : '購入非推奨'}`)
  if (port.plan.ok && ref.reason !== port.plan.reason) {
    diffs.push(`購入理由の文言:\n    既存: ${ref.reason}\n    移植: ${port.plan.reason}`)
  }

  // 券種ごとの点数・的中率・採算オッズ
  const cmpBets = (label, refRows, portRows) => {
    if (refRows.length !== portRows.length) {
      diffs.push(`${label}: 件数 既存${refRows.length} / 移植${portRows.length}`)
      return
    }
    refRows.forEach((r, i) => {
      const p = portRows[i]
      for (const k of ['bt', 'status', 'pts', 'hit', 'be']) {
        if ((r[k] ?? null) !== (p[k] ?? null)) {
          diffs.push(`${label}[${i}] ${r.bt || ''} の ${k}: 既存${r[k]} / 移植${p[k]}`)
        }
      }
      if (r.status === 'ok' && JSON.stringify(r.uma) !== JSON.stringify(p.uma)) {
        diffs.push(`${label}[${i}] ${r.bt} の買い目: 既存${JSON.stringify(r.uma)} / 移植${JSON.stringify(p.uma)}`)
      }
    })
  }
  cmpBets('フォーメーション', parseBetRows(ref.formHtml), port.form)
  cmpBets('内訳', parseBetRows(ref.detailHtml), port.detail)

  return { race_id: raceId, ok: diffs.length === 0, diffs }
}

// ── 実行 ─────────────────────────────────────────────────────────
const files = process.argv.slice(2)
if (!files.length) {
  console.error('使い方: node app/tests/ev_parity.mjs <pred.htmlのパス> [...]')
  process.exit(2)
}

const results = []
for (const f of files) {
  const raceId = path.basename(f).replace(/_pred\.html$/, '')
  try {
    const html = fs.readFileSync(f, 'utf8')
    const ref = runReference(html)
    const port = runPort(ref.evData)
    results.push(compare(raceId, ref, port))
  } catch (e) {
    results.push({ race_id: raceId, ok: false, diffs: [`検証を実行できません: ${e.message}`] })
  }
}

console.log(JSON.stringify({
  ev_core_version: core.EV_CORE_VERSION,
  total: results.length,
  failed: results.filter((r) => !r.ok).length,
  results,
}, null, 2))
process.exit(results.every((r) => r.ok) ? 0 : 1)
