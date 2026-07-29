/** 馬名を50音の行に振り分ける（メモ馬の折り畳み用）。 */

// 馬名はカタカナなので見出しもカタカナにする
export const KANA_ROWS = ['ア', 'カ', 'サ', 'タ', 'ナ', 'ハ', 'マ', 'ヤ', 'ラ', 'ワ', 'その他'] as const
export type KanaRow = (typeof KANA_ROWS)[number]

// 濁点・半濁点・小書き・ヴも同じ行に入れる（バ→は行、ヴ→あ行 など）
const ROW_CHARS: Record<Exclude<KanaRow, 'その他'>, string> = {
  ア: 'アイウエオァィゥェォヴ',
  カ: 'カキクケコガギグゲゴヵヶ',
  サ: 'サシスセソザジズゼゾ',
  タ: 'タチツテトダヂヅデドッ',
  ナ: 'ナニヌネノ',
  ハ: 'ハヒフヘホバビブベボパピプペポ',
  マ: 'マミムメモ',
  ヤ: 'ヤユヨャュョ',
  ラ: 'ラリルレロ',
  ワ: 'ワヲンヮ',
}

const CHAR_TO_ROW = new Map<string, KanaRow>()
for (const [row, chars] of Object.entries(ROW_CHARS)) {
  for (const c of chars) CHAR_TO_ROW.set(c, row as KanaRow)
}

/** ひらがな → カタカナ。全角化もしておく。 */
function toKatakana(s: string): string {
  return s
    .normalize('NFKC')
    .replace(/[ぁ-ゖ]/g, (c) => String.fromCharCode(c.charCodeAt(0) + 0x60))
}

/** 馬名の先頭文字から行を決める。判定できないものは「その他」。 */
export function kanaRowOf(name: string): KanaRow {
  const head = toKatakana((name || '').trim()).charAt(0)
  return CHAR_TO_ROW.get(head) ?? 'その他'
}

/** 50音順（行→名前）で並べ替えるための比較関数。 */
export function compareByKana(a: string, b: string): number {
  return toKatakana(a).localeCompare(toKatakana(b), 'ja')
}

/** 名前つきの配列を行ごとにまとめる。行の並びは KANA_ROWS の順。 */
export function groupByKanaRow<T>(items: T[], nameOf: (x: T) => string) {
  const map = new Map<KanaRow, T[]>()
  for (const item of items) {
    const row = kanaRowOf(nameOf(item))
    const list = map.get(row)
    if (list) list.push(item)
    else map.set(row, [item])
  }
  return KANA_ROWS.filter((r) => map.has(r)).map((row) => ({
    row,
    items: (map.get(row) as T[]).sort((x, y) => compareByKana(nameOf(x), nameOf(y))),
  }))
}
