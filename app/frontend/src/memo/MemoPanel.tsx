import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiError,
  addMemo,
  archiveMemo,
  checkMemoName,
  fetchArchivedMemo,
  fetchMemo,
  restoreMemo,
  updateMemo,
  type MemoEntry,
  type MemoHorse,
  type MemoList,
  type SourceRace,
} from '../api'
import Collapsible from '../ui/Collapsible'
import { groupByKanaRow } from '../ui/kana'

const EMPTY_SOURCE: SourceRace = { 日付: '', 場所: '', R: '', レース名: '', クラス: '' }

/** 「2026/07/25」「2026-07-25」→「2026年7月25日」。 */
function jpDate(v: string | undefined | null): string {
  const m = String(v ?? '').match(/^(\d{4})[/-](\d{1,2})[/-](\d{1,2})$/)
  if (!m) return String(v ?? '')
  return `${Number(m[1])}年${Number(m[2])}月${Number(m[3])}日`
}

/** レース日は先頭に出す。登録日はメモの下に出すのでここには入れない。 */
function srcLabel(s: SourceRace): string {
  const parts = [jpDate(s.日付), s.場所 ? `${s.場所}${s.R || ''}R` : '', s.レース名, s.クラス]
  return parts.filter(Boolean).join(' ')
}

/** メモ本文はまとめて少し遅らせて保存する（1文字ごとにPOSTしない）。 */
function useMemoSaver(onConflict: () => void, onSaved: (hash: string) => void) {
  const timers = useRef<Record<string, number>>({})
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [message, setMessage] = useState<string | null>(null)

  const save = useCallback(
    (key: string, memo: string, hash: string | null) => {
      if (timers.current[key]) window.clearTimeout(timers.current[key])
      timers.current[key] = window.setTimeout(() => {
        setState('saving')
        setMessage(null)
        updateMemo({ key, メモ: memo, expected_hash: hash })
          .then((r) => {
            setState('saved')
            onSaved(r.file_hash)
          })
          .catch((e: unknown) => {
            setState('error')
            if (e instanceof ApiError && e.status === 409) {
              setMessage(typeof e.detail === 'string' ? e.detail : '他の処理がメモを更新しました。')
              onConflict()
            } else {
              setMessage(e instanceof Error ? e.message : '保存に失敗しました')
            }
          })
      }, 700)
    },
    [onConflict, onSaved],
  )

  useEffect(
    () => () => Object.values(timers.current).forEach((t) => window.clearTimeout(t)),
    [],
  )
  return { save, state, message }
}

// ── 追加フォーム ────────────────────────────────────────────────
function AddForm({
  fileHash,
  onDone,
  onCancel,
}: {
  fileHash: string
  onDone: () => void
  onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [src, setSrc] = useState<SourceRace>({ ...EMPTY_SOURCE })
  const [memo, setMemo] = useState('')
  const [author, setAuthor] = useState('')
  const [existing, setExisting] = useState<MemoEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const nameRef = useRef<HTMLInputElement>(null)

  const sameKeyEntry = useMemo(() => {
    if (!existing) return null
    const key = `${name.trim()}|${src.日付}|${src.R}`
    return existing.find((e) => e.key === key) ?? null
  }, [existing, name, src])

  const submit = async (overwrite: boolean, skipCheck: boolean) => {
    setError(null)
    if (!name.trim()) return setError('馬名を入力してください')
    if (!src.日付.trim()) return setError('元レースの日付を入力してください（空だと全レースにメモが出ます）')
    setBusy(true)
    try {
      if (!skipCheck && !overwrite) {
        // まず同じ馬名の登録がないか確認する
        const found = await checkMemoName(name.trim())
        if (found.exists) {
          setExisting(found.entries)
          setBusy(false)
          return
        }
      }
      await addMemo({
        馬名: name.trim(),
        元レース: { ...src, R: src.R === '' ? '' : Number(src.R) },
        メモ: memo,
        追加者: author,
        expected_hash: fileHash,
        overwrite,
      })
      onDone()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '登録に失敗しました')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="memo-form">
      <h3 className="ev-h3">メモ馬を追加</h3>
      <div className="form-grid">
        <label>
          馬名<span className="req">必須</span>
          <input ref={nameRef} className="input" value={name}
                 onChange={(e) => { setName(e.target.value); setExisting(null) }} />
        </label>
        <label>
          元レースの日付<span className="req">必須</span>
          <input className="input" placeholder="2026/07/25" value={src.日付}
                 onChange={(e) => { setSrc({ ...src, 日付: e.target.value }); setExisting(null) }} />
        </label>
        <label>
          場所
          <input className="input" placeholder="新潟" value={src.場所}
                 onChange={(e) => setSrc({ ...src, 場所: e.target.value })} />
        </label>
        <label>
          R
          <input className="input" type="number" min="1" max="12" value={src.R}
                 onChange={(e) => { setSrc({ ...src, R: e.target.value }); setExisting(null) }} />
        </label>
        <label>
          レース名
          <input className="input" value={src.レース名}
                 onChange={(e) => setSrc({ ...src, レース名: e.target.value })} />
        </label>
        <label>
          クラス
          <input className="input" placeholder="3勝 / Ｇ３ など" value={src.クラス}
                 onChange={(e) => setSrc({ ...src, クラス: e.target.value })} />
        </label>
        <label className="wide">
          メモ
          <textarea className="input" rows={3} value={memo} onChange={(e) => setMemo(e.target.value)} />
        </label>
        <label>
          追加者
          <input className="input" value={author} onChange={(e) => setAuthor(e.target.value)} />
        </label>
      </div>

      {error && <div className="note error">{error}</div>}

      {existing && (
        <div className="dup-box">
          <div className="dup-title">
            同じ馬名「{name.trim()}」の登録が {existing.length} 件あります
          </div>
          <ul className="dup-list">
            {existing.map((e) => (
              <li key={e.key} className={sameKeyEntry?.key === e.key ? 'dup-item same' : 'dup-item'}>
                <div className="dup-src">
                  {srcLabel(e.元レース)}
                  {sameKeyEntry?.key === e.key && <span className="badge badge-note">同じ元レース</span>}
                </div>
                <div className="dup-memo">{e.メモ?.trim() ? e.メモ : '（メモ未記入）'}</div>
                <div className="dup-meta">登録日 {e.登録日}</div>
              </li>
            ))}
          </ul>
          <div className="dup-actions">
            {sameKeyEntry ? (
              <button className="btn primary" disabled={busy} onClick={() => submit(true, true)}>
                この登録を上書きする
              </button>
            ) : (
              <button className="btn primary" disabled={busy} onClick={() => submit(false, true)}>
                別レースとして新規登録する
              </button>
            )}
            <button
              className="btn"
              disabled={busy}
              onClick={() => { setExisting(null); nameRef.current?.focus() }}
            >
              馬名を修正して新規登録
            </button>
          </div>
        </div>
      )}

      {!existing && (
        <div className="form-actions">
          <button className="btn primary" disabled={busy} onClick={() => submit(false, false)}>
            登録する
          </button>
          <button className="btn" disabled={busy} onClick={onCancel}>キャンセル</button>
        </div>
      )}
    </div>
  )
}

// ── 一覧 ────────────────────────────────────────────────────────
export default function MemoPanel() {
  const [data, setData] = useState<MemoList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [onlyEmpty, setOnlyEmpty] = useState(false)
  const [adding, setAdding] = useState(false)
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [hash, setHash] = useState<string | null>(null)

  const [archived, setArchived] = useState<MemoEntry[]>([])

  const reload = useCallback(() => {
    fetchMemo()
      .then((d) => { setData(d); setHash(d.file_hash); setError(null) })
      .catch((e: Error) => setError(e.message))
    fetchArchivedMemo()
      .then((d) => setArchived(d.entries))
      .catch(() => setArchived([]))
  }, [])

  useEffect(() => { reload() }, [reload])

  const saver = useMemoSaver(reload, (h) => setHash(h))

  const shown: MemoHorse[] = useMemo(() => {
    if (!data) return []
    const needle = q.trim().toLowerCase()
    return data.horses.filter((h) => {
      if (onlyEmpty && h.has_memo) return false
      if (!needle) return true
      return (
        h.name.toLowerCase().includes(needle) ||
        h.entries.some((e) => srcLabel(e.元レース).toLowerCase().includes(needle))
      )
    })
  }, [data, q, onlyEmpty])

  const groups = useMemo(() => groupByKanaRow(shown, (h) => h.name), [shown])
  // 検索語を入れたときだけ平坦に出す。チェックボックスは折り畳みを保ったまま絞り込む。
  const searching = q.trim().length > 0

  const renderHorse = (h: MemoHorse) => (
    <li key={h.name} className="memo-horse">
      <div className="memo-head">
        <span className="memo-name">{h.name}</span>
        {h.entry_count > 1 && (
          <span className="badge badge-note">{h.entry_count}レースで登録</span>
        )}
        {!h.has_memo && <span className="badge badge-todo">メモ未記入</span>}
      </div>
      {h.entries.map((e) => (
        <div key={e.key} className="memo-entry">
          <div className="memo-src">
            <span className="memo-racedate">{srcLabel(e.元レース)}</span>
            <button className="link-btn danger" onClick={() => onArchive(e)}>
              削除
            </button>
          </div>
          <textarea
            className="input memo-text"
            rows={2}
            placeholder="次走の狙いどころ、敗因、条件など"
            value={drafts[e.key] ?? e.メモ ?? ''}
            onChange={(ev) => {
              const v = ev.target.value
              setDrafts((d) => ({ ...d, [e.key]: v }))
              saver.save(e.key, v, hash)
            }}
          />
          <div className="memo-registered">登録日 {jpDate(e.登録日)}</div>
        </div>
      ))}
    </li>
  )

  const onRestore = async (e: MemoEntry) => {
    try {
      await restoreMemo({ key: e.key, expected_hash: hash })
      reload()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '戻せませんでした')
    }
  }

  const onArchive = async (e: MemoEntry) => {
    if (!window.confirm(
      `「${e.馬名}」（${srcLabel(e.元レース)}）を削除しますか？\n`
      + 'すぐには消えません。7日間は「削除予定」から元に戻せます。',
    )) return
    try {
      await archiveMemo({ key: e.key, expected_hash: hash })
      reload()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'アーカイブに失敗しました')
    }
  }

  if (error && !data) return <div className="note error">メモ馬を読み込めません: {error}</div>
  if (!data) return <div className="note">読み込み中...</div>

  return (
    <div className="app">
      <header className="header">
        <h1>メモ馬</h1>
        <div className="sub">
          次走注目として登録した馬。回顧を作ると自動でも追加されます。
        </div>
      </header>

      <div className="filters memo-filters">
        <input className="input" placeholder="馬名・レースで検索" value={q}
               onChange={(e) => setQ(e.target.value)} />
        <label className="check">
          <input type="checkbox" checked={onlyEmpty} onChange={(e) => setOnlyEmpty(e.target.checked)} />
          メモ未記入のみ
        </label>
        <button className="btn primary" onClick={() => setAdding((v) => !v)}>
          {adding ? '追加をとじる' : '＋ 追加'}
        </button>
      </div>

      {adding && (
        <AddForm
          fileHash={hash ?? ''}
          onDone={() => { setAdding(false); reload() }}
          onCancel={() => setAdding(false)}
        />
      )}

      <div className="note">
        {shown.length} 頭 / 全 {data.total_horses} 頭（登録 {data.total_entries} 件）
        {saver.state === 'saving' && <span className="save-state">保存中...</span>}
        {saver.state === 'saved' && <span className="save-state">保存しました</span>}
      </div>
      {saver.message && <div className="note error">{saver.message}</div>}
      {error && <div className="note error">{error}</div>}

      {searching ? (
        <ul className="memo-list">
          {shown.map((h) => renderHorse(h))}
        </ul>
      ) : (
        groups.map((g) => (
          <Collapsible
            key={g.row}
            id={`memo.kana.${g.row}`}
            title={`${g.row}行`}
            sub={`${g.items.length}頭${g.items.filter((x) => !x.has_memo).length ? `（未記入 ${g.items.filter((x) => !x.has_memo).length}）` : ''}`}
          >
            <ul className="memo-list">{g.items.map((h) => renderHorse(h))}</ul>
          </Collapsible>
        ))
      )}

      <Collapsible id="memo.archived" title="削除予定" sub={`${archived.length}件`}>
        <div className="ev-note">
          削除したメモ馬は7日間ここに残り、期限を過ぎると完全に消えます（消える前に控えを保存します）。
        </div>
        {archived.length === 0 ? (
          <div className="note">削除予定のメモ馬はありません。</div>
        ) : (
          <ul className="memo-list">
            {archived.map((e) => (
              <li key={e.key} className="memo-horse">
                <div className="memo-head">
                  <span className="memo-name">{e.馬名}</span>
                  <span className="memo-meta">{srcLabel(e.元レース)}</span>
                  {typeof e.days_left === 'number' && (
                    <span className="badge badge-todo">あと{Math.max(0, e.days_left)}日で完全削除</span>
                  )}
                  <button className="btn" onClick={() => onRestore(e)}>元に戻す</button>
                </div>
                {e.メモ?.trim() && <div className="muted">{e.メモ}</div>}
              </li>
            ))}
          </ul>
        )}
      </Collapsible>
    </div>
  )
}
