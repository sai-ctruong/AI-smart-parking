import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageTitle,
  Panel,
  StatusBadge,
} from '../components/ui'
import { ApiError, formatTime } from '../lib/api'
import type { Occupancy, SnapshotPage } from '../lib/api'
import { useAuth } from '../lib/auth'

export default function OverviewPage() {
  const { request } = useAuth()
  const occupancy = useQuery({
    queryKey: ['occupancy'],
    queryFn: () => request<Occupancy>('/lots/current/occupancy'),
    retry: false,
  })
  const recent = useQuery({
    queryKey: ['snapshots', 1, 5],
    queryFn: () => request<SnapshotPage>('/snapshots?page=1&page_size=5'),
    retry: false,
  })
  const counts = occupancy.data?.counts
  const missingCamera =
    occupancy.error instanceof ApiError && occupancy.error.status === 404

  return (
    <div className="space-y-8">
      <PageTitle
        title="Tổng quan"
        description="Tình trạng chỗ đỗ theo ảnh chụp gần nhất."
        action={
          <Link to="/analysis" className="primary-button">
            Phân tích ảnh mới
          </Link>
        }
      />
      <Panel
        title="Tình trạng hiện tại"
        action={
          occupancy.data && <StatusBadge value={occupancy.data.alert_state} />
        }
      >
        {occupancy.isPending ? (
          <LoadingState />
        ) : missingCamera ? (
          <EmptyState
            title="Chưa cấu hình camera"
            description="Admin cần tạo bãi đỗ và camera trước khi hệ thống có thể phân tích ảnh."
            action={
              <Link to="/configuration" className="text-link">
                Xem cấu hình
              </Link>
            }
          />
        ) : occupancy.isError ? (
          <ErrorState retry={() => occupancy.refetch()} />
        ) : !counts ? (
          <EmptyState
            title="Chưa có ảnh chụp"
            description="Sau lần tải ảnh đầu tiên, số chỗ trống và cảnh báo sẽ xuất hiện tại đây."
            action={
              <Link to="/analysis" className="text-link">
                Tải ảnh để phân tích
              </Link>
            }
          />
        ) : (
          <div className="px-5 py-5">
            <div className="grid gap-0 divide-y divide-[var(--border)] sm:grid-cols-2 sm:divide-x sm:divide-y-0 xl:grid-cols-4">
              <Metric label="Tổng chỗ đỗ" value={counts.total} />
              <Metric
                label="Còn trống"
                value={counts.empty}
                tone="text-emerald-800"
              />
              <Metric label="Đã chiếm" value={counts.occupied} />
              <Metric
                label="Chưa xác định"
                value={counts.unknown}
                tone="text-amber-800"
              />
            </div>
            <div className="mt-6 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--rule)] pt-4 text-sm text-[var(--muted)]">
              <span>
                Ảnh gần nhất: {formatTime(occupancy.data.captured_at)}
              </span>
              <span>
                Tỷ lệ lấp đầy:{' '}
                {counts.occupancy_percent === null
                  ? 'Chưa thể tính'
                  : `${counts.occupancy_percent.toFixed(1)}%`}
              </span>
            </div>
          </div>
        )}
      </Panel>
      <Panel
        title="Ảnh chụp gần đây"
        action={
          <Link to="/history" className="text-link">
            Xem tất cả
          </Link>
        }
      >
        {recent.isPending ? (
          <LoadingState />
        ) : recent.isError ? (
          <ErrorState retry={() => recent.refetch()} />
        ) : recent.data.items.length === 0 ? (
          <EmptyState
            title="Chưa có lịch sử ảnh chụp"
            description="Mỗi lần phân tích thành công sẽ được lưu trong lịch sử."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Thời điểm</th>
                  <th scope="col">Camera</th>
                  <th scope="col" className="text-right">
                    Trống
                  </th>
                  <th scope="col" className="text-right">
                    Đã chiếm
                  </th>
                  <th scope="col">Cảnh báo</th>
                  <th scope="col">
                    <span className="sr-only">Mở</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {recent.data.items.map((item) => (
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
                    <td>
                      <StatusBadge value={item.alert_state} />
                    </td>
                    <td className="text-right">
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
        )}
      </Panel>
    </div>
  )
}

function Metric({
  label,
  value,
  tone = '',
}: {
  label: string
  value: number
  tone?: string
}) {
  return (
    <div className="px-5 py-3 first:pl-0">
      <p className="text-sm text-[var(--muted)]">{label}</p>
      <p className={`mt-2 text-[28px] font-normal tabular-nums ${tone}`}>
        {value}
      </p>
    </div>
  )
}
