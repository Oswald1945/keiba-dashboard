/** evCore.js の型定義。計算の実体は evCore.js（既存JSからの移植）にある。 */

export type EvHorse = {
  馬名: string
  馬番: number | null
  枠番: number | null
  スコア: number
  表示スコア: number
  順位予想: number
  オッズ: number | null
  'コース特徴pts': number | null
  複勝下限: number | null
  複勝上限: number | null
  人気: number | null
  脚質: string
  SmartRC推定人気順: string | number | null
  乖離度: number | null
  is_memo: boolean
  is_ana: boolean
  is_dark: boolean
  地方実績のみ: boolean
}

export type EvRow = EvHorse & {
  _prob: number
  _ev: number | undefined
  _isDark: boolean
  _isLocal: boolean
  _breakEven: number | null
  _odds: number | null | undefined
  _judgement: string
  _cls: 'ev-positive' | 'ev-neutral' | 'ev-negative'
}

export type BetPlan =
  | { ok: false; reason: string; wp: number[] }
  | {
      ok: true
      wp: number[]
      o3: Record<string, number>
      pv: Record<string, number>
      um: Record<string, number>
      dv: Record<string, number>
      sc: Record<string, string | number | null>
      gi: Record<string, number>
      ro: Record<string, number>
      axis: string
      axisUma: number
      axisWin: number
      axisDev: number
      axisPop: number
      partners: string[]
      contend: string[]
      col1: string[]
      col2: string[]
      col3: string[]
      buy: boolean
      reason: string
      axisDiffersFromScoreTop: boolean
      scoreTop: EvHorse | null
      names: string[]
    }

export type FormationBet = {
  bt: string
  cols: number[][]
  sep: '-' | '→'
  M: number
  P: number
  key: string
  status: 'ok' | 'no_partner' | 'too_many'
}

export type DetailBet = {
  bt: string
  uma: number[]
  sep: '-' | '→'
  P: number
  M: number
  key: string
}

export type EvCell = {
  hitRate: number
  breakEven: number
  ev: number | null
  cls: '' | 'ev-positive' | 'ev-neutral' | 'ev-negative'
  judge: string
}

export const EV_CORE_VERSION: string
export const TEMP: number
export const MAX_RATIO: number
export const MR: number
export const PARTNER_DEV_MAX: number
export const PARTNER_GAP: number
export const COL1_BAND: number
export const COL2_BAND: number

export function placeProb(probs: number[], idx: number, k: number): number
export function tableWinProbs(evData: EvHorse[], temp?: number): number[]
export function betWinProbs(evData: EvHorse[], temp?: number): number[]
export function tableRows(
  evData: EvHorse[],
  opts?: { tab?: 'tansho' | 'fukusho'; userOdds?: Record<string, number> },
): EvRow[]
export function permK<T>(arr: T[], k: number): T[][]
export function combK<T>(arr: T[], k: number): T[][]
export function buildBetPlan(evData: EvHorse[], temp?: number): BetPlan
export function formationBets(plan: BetPlan): FormationBet[]
export function detailBets(plan: BetPlan): DetailBet[]
export function betKeyFormation(f: { bt: string; cols: number[][]; sep: string }): string
export function evCell(P: number, odds: number | null | undefined): EvCell
