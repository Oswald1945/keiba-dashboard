import { useCallback, useEffect, useState } from 'react'

/** 画面の状態（折り畳みの開閉・モードなど）をブラウザに覚えさせる。 */
const PREFIX = 'keiba.'

export function readStored<T>(key: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(PREFIX + key)
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

export function writeStored<T>(key: string, value: T): void {
  try {
    window.localStorage.setItem(PREFIX + key, JSON.stringify(value))
  } catch {
    /* 保存できなくても動作は続ける */
  }
}

/** localStorage に覚える useState。 */
export function usePersistentState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => readStored(key, initial))
  useEffect(() => { writeStored(key, value) }, [key, value])
  const reset = useCallback(() => setValue(initial), [initial])
  return [value, setValue, reset] as const
}
