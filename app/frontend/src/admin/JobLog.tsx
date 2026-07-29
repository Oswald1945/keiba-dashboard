import { useEffect, useRef, useState } from 'react'
import { adminApi, type Job } from './adminApi'

/** 実行中ジョブのログを1秒ごとに取りに行って流す。終わったら止まる。 */
export default function JobLog({
  jobId,
  onFinished,
}: {
  jobId: string | null
  onFinished?: (job: Job) => void
}) {
  const [job, setJob] = useState<Job | null>(null)
  const [lines, setLines] = useState<string[]>([])
  const boxRef = useRef<HTMLPreElement>(null)
  const finishedRef = useRef(false)

  useEffect(() => {
    setLines([])
    setJob(null)
    finishedRef.current = false
    if (!jobId) return
    let alive = true
    let after = 0
    const tick = async () => {
      try {
        const j = await adminApi.job(jobId, after)
        if (!alive) return
        setJob(j)
        if (j.lines.length) {
          after += j.lines.length
          setLines((prev) => [...prev, ...j.lines])
        }
        if (['ok', 'error', 'cancelled'].includes(j.status)) {
          if (!finishedRef.current) {
            finishedRef.current = true
            onFinished?.(j)
          }
          return
        }
      } catch {
        /* 一時的な失敗は次のtickで拾う */
      }
      if (alive) timer = window.setTimeout(tick, 1000)
    }
    let timer = window.setTimeout(tick, 200)
    return () => {
      alive = false
      window.clearTimeout(timer)
    }
  }, [jobId, onFinished])

  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight
  }, [lines])

  if (!jobId) return null

  const statusLabel: Record<string, string> = {
    queued: '待機中',
    running: '実行中',
    ok: '完了',
    error: '失敗',
    cancelled: '中断',
  }

  return (
    <div className="joblog">
      <div className="joblog-head">
        <b>{job?.name ?? '実行中'}</b>
        <span className={`job-status ${job?.status ?? 'running'}`}>
          {statusLabel[job?.status ?? 'running']}
        </span>
        {job && job.steps_total > 0 && (
          <span className="muted">
            {job.steps_done} / {job.steps_total}
          </span>
        )}
        {job && (job.status === 'running' || job.status === 'queued') && (
          <button className="btn" onClick={() => adminApi.cancel(job.id).catch(() => {})}>
            中断する
          </button>
        )}
      </div>
      {job?.error && <div className="note error">{job.error}</div>}
      {typeof job?.result?.hint === 'string' && (
        <div className="note error">{job.result.hint as string}</div>
      )}
      <pre className="joblog-body" ref={boxRef}>
        {lines.join('\n')}
      </pre>
    </div>
  )
}
