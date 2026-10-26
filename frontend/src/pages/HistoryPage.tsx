import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageTitle,
  Panel,
  StatusBadge,
} from '../components/ui'
import { formatTime } from '../lib/api'
import type { SnapshotPage } from '../lib/api'
import { useAuth } from '../lib/auth'

export default function HistoryPage() {
  const { request, blob } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedPage = Number(searchParams.get('page') || '1')
  const page =
    Number.isSafeInteger(requestedPage) && requestedPage > 0 ? requestedPage : 1
  const setPage = (next: number) =>
    setSearchParams(next === 1 ? {} : { page: String(next) })
  const [exportError, setExportError] = useState<string | null>(null)
  const history = useQuery({
    queryKey: ['snapshots', page, 20],
    queryFn: () =>
      request<SnapshotPage>(`/snapshots?page=${page}&page_size=20`),
  })
  const pages = history.data
    ? Math.max(1, Math.ceil(history.data.total_items / history.data.page_size))
    : 1
  async function exportCsv() {
    setExportError(null)
    try {
      const data = await blob('/snapshots/export.csv')
      const url = URL.createObjectURL(data)
      const link = document.createElement('a')
      link.href = url
      link.download = 'smart-parking-history.csv'
      document.body.append(link)
      link.click()
      link.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch {
      setExportError('Không thể xuất CSV. Vui lòng thử lại.')
    }
  }
  return (
    <div className="space-y-8">
      <PageTitle
        title="Lịch sử ảnh chụp"
        description="Tra cứu các lần phân tích đã lưu và mở từng ảnh để xem dự đoán gốc cùng kết quả duyệt."
        action={
          <button
            type="button"
            className="secondary-button"
            onClick={exportCsv}
          >
            Xuất CSV
          </button>
        }
      />
      {exportError && <ErrorState message={exportError} />}
      <Panel title="Danh sách ảnh">
        {history.isPending ? (
          <LoadingState />
        ) : history.isError ? (
          <ErrorState retry={() => history.refetch()} />
        ) : history.data.items.length === 0 ? (
          <EmptyState
            title="Chưa có ảnh chụp"
            description="Ảnh phân tích thành công sẽ xuất hiện trong lịch sử."
            action={
              <Link to="/analysis" className="text-link">
                Phân tích ảnh đầu tiên
              </Link>
            }
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Thời điểm chụp</th>
                    <th scope="col">Camera</th>
                    <th scope="col" className="text-right">
                      Trống
                    </th>
                    <th scope="col" className="text-right">
                      Đã chiếm
                    </th>
                    <th scope="col" className="text-right">
                      Không rõ
                    </th>
                    <th scope="col">Cảnh báo</th>
                    <th scope="col">
                      <span className="sr-only">Chi tiết</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {history.data.items.map((item) => (
                    <tr key={item.snapshot_id}>
                      <td>{formatTime(item.captured_at)}</td>
                      <td className="tabular-nums text-xs">
                        {item.camera_id.slice(0, 8)}
                      </td>
                      <td className="text-right tabular-nums">
                        {item.empty_count}
                      </td>
                      <td className="text-right tabular-nums">
                        {item.occupied_count}
                      </td>
                      <td className="text-right tabular-nums">
                        {item.unknown_count}
                      </td>
                      <td>
                        <StatusBadge value={item.alert_state} />
                      </td>
                      <td>
                        <Link
                          to={`/review/${item.snapshot_id}`}
                          className="text-link"
                        >
                          Xem
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="flex items-center justify-between gap-4 border-t border-[var(--rule)] px-5 py-4 text-sm">
              <span className="text-[var(--muted)]">
                {history.data.total_items} ảnh · Trang {page}/{pages}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="secondary-button"
                  disabled={page <= 1}
                  onClick={() => setPage(page - 1)}
                >
                  Trước
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={page >= pages}
                  onClick={() => setPage(page + 1)}
                >
                  Sau
                </button>
              </div>
            </div>
          </>
        )}
      </Panel>
    </div>
  )
}
