import type { ReactNode } from 'react'
import type { AlertState, Status } from '../lib/api'

export function StatusBadge({ value }: { value: Status | AlertState }) {
  const labels: Record<Status | AlertState, string> = {
    empty: 'Trống',
    occupied: 'Đã chiếm',
    unknown: 'Chưa xác định',
    NONE: 'Bình thường',
    FULL: 'Đã đầy',
    STALE: 'Dữ liệu cũ',
  }
  const tones: Record<Status | AlertState, string> = {
    empty: 'bg-emerald-50 text-emerald-800',
    occupied: 'bg-rose-50 text-rose-800',
    unknown: 'bg-amber-50 text-amber-800',
    NONE: 'bg-emerald-50 text-emerald-800',
    FULL: 'bg-rose-50 text-rose-800',
    STALE: 'bg-amber-50 text-amber-800',
  }
  return (
    <span
      className={`inline-flex items-center gap-2 rounded px-2 py-1 text-xs font-medium ${tones[value]}`}
    >
      <span
        className="h-1.5 w-1.5 rounded-full bg-current"
        aria-hidden="true"
      />
      {labels[value]}
    </span>
  )
}

export function PageTitle({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight text-[var(--text)]">
          {title}
        </h1>
        <p className="mt-1 text-sm text-[var(--muted)]">{description}</p>
      </div>
      {action}
    </div>
  )
}

export function Panel({
  title,
  action,
  children,
}: {
  title: string
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="rounded-lg border border-[var(--border)] bg-white">
      <div className="flex items-center justify-between gap-4 border-b border-[var(--rule)] px-5 py-4">
        <h2 className="text-base font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="px-5 py-12 text-center">
      <p className="font-medium">{title}</p>
      <p className="mx-auto mt-2 max-w-md text-sm text-[var(--muted)]">
        {description}
      </p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function ErrorState({
  message,
  retry,
}: {
  message?: string
  retry?: () => void
}) {
  return (
    <div
      role="alert"
      className="m-5 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900"
    >
      <p>{message || 'Không thể tải dữ liệu. Vui lòng thử lại.'}</p>
      {retry && (
        <button
          type="button"
          className="mt-2 font-semibold underline underline-offset-2"
          onClick={retry}
        >
          Thử lại
        </button>
      )}
    </div>
  )
}

export function LoadingState({
  label = 'Đang tải dữ liệu…',
}: {
  label?: string
}) {
  return (
    <p role="status" className="px-5 py-10 text-sm text-[var(--muted)]">
      {label}
    </p>
  )
}
