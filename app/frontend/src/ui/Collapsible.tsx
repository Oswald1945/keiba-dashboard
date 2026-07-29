import { useState, type ReactNode } from 'react'
import { readStored, writeStored } from './store'

/**
 * 折り畳み。開いたときだけ中身を描画する。
 *
 * 単に隠すのではなく **描画しない** のが肝心。メモ馬は586頭・入力欄627個あり、
 * 全部作ると画面の高さが14万px（スマホ145画面分）になって重くなる。
 *
 * 開閉の状態は localStorage に覚えるので、次に開いたときも同じ状態になる。
 */
export default function Collapsible({
  id,
  title,
  sub,
  defaultOpen = false,
  className = '',
  children,
}: {
  id: string
  title: ReactNode
  sub?: ReactNode
  defaultOpen?: boolean
  className?: string
  children: ReactNode
}) {
  const key = `open.${id}`
  const [open, setOpen] = useState<boolean>(() => readStored(key, defaultOpen))

  const toggle = () => {
    const next = !open
    setOpen(next)
    writeStored(key, next)
  }

  return (
    <section className={`collapsible${open ? ' open' : ''} ${className}`}>
      <button className="collapsible-head" onClick={toggle} aria-expanded={open}>
        <span className="collapsible-caret" aria-hidden="true">{open ? '▾' : '▸'}</span>
        <span className="collapsible-title">{title}</span>
        {sub && <span className="collapsible-sub">{sub}</span>}
      </button>
      {open && <div className="collapsible-body">{children}</div>}
    </section>
  )
}
