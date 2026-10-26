import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageTitle,
  Panel,
  StatusBadge,
} from '../components/ui'
import { formatTime } from '../lib/api'
import type {
  Prediction,
  SnapshotDetail,
  SnapshotPage,
  Status,
} from '../lib/api'
import { useAuth } from '../lib/auth'

export default function ReviewPage() {
  const { snapshotId } = useParams()
  const { request } = useAuth()
  const snapshots = useQuery({
    queryKey: ['snapshots', 'review'],
    queryFn: () => request<SnapshotPage>('/snapshots?page=1&page_size=20'),
    enabled: !snapshotId,
  })
  const detail = useQuery({
    queryKey: ['snapshot', snapshotId],
    queryFn: () => request<SnapshotDetail>(`/snapshots/${snapshotId}`),
    enabled: !!snapshotId,
  })
  return (
    <div className="space-y-8">
      <PageTitle
        title="Duyệt kết quả"
        description="Đối chiếu nhãn AI gốc và chỉnh sửa của người vận hành. Mỗi lần duyệt được lưu riêng."
        action={
          snapshotId ? (
            <Link to="/review" className="secondary-button">
              Danh sách ảnh
            </Link>
          ) : undefined
        }
      />
      {!snapshotId ? (
        <Panel title="Ảnh cần xem">
          {snapshots.isPending ? (
            <LoadingState />
          ) : snapshots.isError ? (
            <ErrorState retry={() => snapshots.refetch()} />
          ) : snapshots.data.items.length === 0 ? (
            <EmptyState
              title="Chưa có kết quả để duyệt"
              description="Chạy phân tích ảnh để tạo dự đoán trước khi duyệt."
              action={
                <Link to="/analysis" className="text-link">
                  Phân tích ảnh
                </Link>
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Thời điểm chụp</th>
                    <th scope="col">Đã duyệt</th>
                    <th scope="col">Cảnh báo</th>
                    <th scope="col">
                      <span className="sr-only">Mở</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {snapshots.data.items.map((item) => (
                    <tr key={item.snapshot_id}>
                      <td>{formatTime(item.captured_at)}</td>
                      <td>
                        {item.reviewed_spots}/{item.total_spots} vùng
                      </td>
                      <td>
                        <StatusBadge value={item.alert_state} />
                      </td>
                      <td>
                        <Link
                          className="text-link"
                          to={`/review/${item.snapshot_id}`}
                        >
                          Xem chi tiết
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      ) : (
        <Panel
          title="Dự đoán theo vùng"
          action={
            detail.data && <StatusBadge value={detail.data.alert_state} />
          }
        >
          {detail.isPending ? (
            <LoadingState />
          ) : detail.isError ? (
            <ErrorState retry={() => detail.refetch()} />
          ) : (
            <>
              <div className="flex flex-wrap gap-x-8 gap-y-2 border-b border-[var(--rule)] px-5 py-4 text-sm">
                <span>
                  Chụp: <strong>{formatTime(detail.data.timestamp)}</strong>
                </span>
                <span>
                  Tổng: <strong>{detail.data.total_spots}</strong>
                </span>
                <span>
                  Trống: <strong>{detail.data.empty_count}</strong>
                </span>
                <span>
                  Đã chiếm: <strong>{detail.data.occupied_count}</strong>
                </span>
                <span>
                  Không rõ: <strong>{detail.data.unknown_count}</strong>
                </span>
              </div>
              {detail.data.predictions.length === 0 ? (
                <EmptyState
                  title="Không có dự đoán"
                  description="Ảnh này chưa có vùng đỗ được phân tích."
                />
              ) : (
                <div className="divide-y divide-[var(--rule)]">
                  {detail.data.predictions.map((item) => (
                    <PredictionRow
                      key={item.prediction_id}
                      item={item}
                      snapshotId={snapshotId}
                    />
                  ))}
                </div>
              )}
            </>
          )}
        </Panel>
      )}
    </div>
  )
}

function PredictionRow({
  item,
  snapshotId,
}: {
  item: Prediction
  snapshotId: string
}) {
  const { request } = useAuth()
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<Status>(item.effective_status)
  const [note, setNote] = useState('')
  const review = useMutation({
    mutationFn: () =>
      request(`/predictions/${item.prediction_id}/reviews`, {
        method: 'POST',
        headers: { 'If-Match': `"${item.review_version}"` },
        body: JSON.stringify({
          reviewed_status: status,
          note: note.trim() || null,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['snapshot', snapshotId] })
      queryClient.invalidateQueries({ queryKey: ['snapshots'] })
      queryClient.invalidateQueries({ queryKey: ['occupancy'] })
      setNote('')
    },
  })
  return (
    <div className="grid gap-4 px-5 py-5 lg:grid-cols-[minmax(120px,1fr)_130px_130px_minmax(220px,1.5fr)] lg:items-center">
      <div>
        <p className="text-sm font-semibold">Vùng {item.spot_id.slice(0, 8)}</p>
        <p className="mt-1 text-xs text-[var(--muted)]">
          Độ tin cậy:{' '}
          {item.confidence === null
            ? 'Không có'
            : `${Math.round(item.confidence * 100)}%`}
        </p>
      </div>
      <div>
        <p className="mb-1 text-xs text-[var(--muted)]">AI gốc</p>
        <StatusBadge value={item.predicted_status} />
      </div>
      <div>
        <p className="mb-1 text-xs text-[var(--muted)]">Hiện hành</p>
        <StatusBadge value={item.effective_status} />
      </div>
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          review.mutate()
        }}
      >
        <label className="sr-only" htmlFor={`status-${item.prediction_id}`}>
          Trạng thái duyệt
        </label>
        <select
          id={`status-${item.prediction_id}`}
          className="input"
          value={status}
          onChange={(event) => setStatus(event.target.value as Status)}
        >
          <option value="empty">Trống</option>
          <option value="occupied">Đã chiếm</option>
          <option value="unknown">Chưa xác định</option>
        </select>
        <label className="sr-only" htmlFor={`note-${item.prediction_id}`}>
          Ghi chú
        </label>
        <input
          id={`note-${item.prediction_id}`}
          className="input min-w-0 flex-1"
          placeholder="Ghi chú (tuỳ chọn)"
          maxLength={1000}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
        <button
          type="submit"
          className="secondary-button"
          disabled={review.isPending}
        >
          {review.isPending ? 'Đang lưu…' : 'Lưu duyệt'}
        </button>
        {review.isError && (
          <p role="alert" className="w-full text-xs text-rose-800">
            Không thể lưu duyệt. Kết quả có thể đã được người khác thay đổi; tải
            lại trang rồi thử lại.
          </p>
        )}
      </form>
    </div>
  )
}
