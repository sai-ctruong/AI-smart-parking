import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { Link } from 'react-router'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageTitle,
  Panel,
  StatusBadge,
} from '../components/ui'
import type { Camera, SnapshotDetail } from '../lib/api'
import { useAuth } from '../lib/auth'

export default function AnalysisPage() {
  const { request } = useAuth()
  const queryClient = useQueryClient()
  const camera = useQuery({
    queryKey: ['camera', 'current'],
    queryFn: () => request<Camera>('/cameras/current'),
  })
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  useEffect(() => {
    if (!file) {
      setPreview(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])
  const prediction = useMutation({
    mutationFn: async () => {
      if (!file || !camera.data)
        throw new Error('Chọn ảnh và camera trước khi phân tích.')
      const body = new FormData()
      body.append('camera_id', camera.data.id)
      body.append('file', file)
      return request<SnapshotDetail>('/snapshots/predict', {
        method: 'POST',
        body,
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['occupancy'] })
      queryClient.invalidateQueries({ queryKey: ['snapshots'] })
    },
  })
  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    prediction.reset()
    setFile(event.target.files?.[0] ?? null)
  }
  function submit(event: FormEvent) {
    event.preventDefault()
    prediction.mutate()
  }

  return (
    <div className="space-y-8">
      <PageTitle
        title="Phân tích ảnh"
        description="Tải ảnh JPEG hoặc PNG từ camera cố định để dự đoán trạng thái từng vùng đỗ."
      />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Panel title="Ảnh chụp">
          <form className="space-y-5 p-5" onSubmit={submit}>
            {camera.isPending ? (
              <LoadingState />
            ) : camera.isError ? (
              <ErrorState
                message="Không có camera khả dụng. Kiểm tra cấu hình hoặc kết nối API."
                retry={() => camera.refetch()}
              />
            ) : (
              <p className="text-sm text-[var(--muted)]">
                Camera:{' '}
                <strong className="text-[var(--text)]">
                  {camera.data.name}
                </strong>
              </p>
            )}
            <div>
              <label
                className="mb-2 block text-sm font-medium"
                htmlFor="snapshot-file"
              >
                Chọn ảnh chụp
              </label>
              <input
                id="snapshot-file"
                type="file"
                accept="image/jpeg,image/png,.jpg,.jpeg,.png"
                onChange={chooseFile}
                className="input w-full file:mr-4 file:cursor-pointer file:border-0 file:bg-transparent file:font-semibold"
              />
              <p className="mt-2 text-xs text-[var(--muted)]">
                Ảnh phải khớp với góc nhìn camera đã cấu hình.
              </p>
            </div>
            {preview && (
              <div className="relative overflow-hidden rounded-md border border-[var(--border)] bg-[#e7eeea]">
                <img
                  src={preview}
                  alt="Ảnh chụp đã chọn"
                  className="block h-auto w-full"
                />
                {prediction.data && (
                  <svg
                    className="pointer-events-none absolute inset-0 h-full w-full"
                    viewBox="0 0 100 100"
                    preserveAspectRatio="none"
                    aria-label="Các vùng đỗ và trạng thái dự đoán"
                  >
                    {prediction.data.predictions.map((item) => (
                      <polygon
                        key={item.spot_id}
                        points={item.polygon
                          .map((point) => `${point.x * 100},${point.y * 100}`)
                          .join(' ')}
                        fill={
                          item.predicted_status === 'empty'
                            ? '#13a77733'
                            : item.predicted_status === 'occupied'
                              ? '#dc555533'
                              : '#df9a3033'
                        }
                        stroke={
                          item.predicted_status === 'empty'
                            ? '#148467'
                            : item.predicted_status === 'occupied'
                              ? '#c24444'
                              : '#ab741c'
                        }
                        strokeWidth=".45"
                        vectorEffect="non-scaling-stroke"
                      />
                    ))}
                  </svg>
                )}
              </div>
            )}
            <button
              className="primary-button"
              type="submit"
              disabled={!file || !camera.data || prediction.isPending}
            >
              {prediction.isPending ? 'Đang phân tích…' : 'Phân tích ảnh'}
            </button>
            {prediction.isError && (
              <ErrorState message={prediction.error.message} />
            )}
          </form>
        </Panel>
        <Panel title="Kết quả">
          {!prediction.data ? (
            <EmptyState
              title="Chưa có kết quả"
              description="Chọn ảnh chụp rồi chạy phân tích. Dự đoán cần có mô hình đã được cấu hình trên backend."
            />
          ) : (
            <div className="space-y-5 p-5">
              <div className="flex items-center justify-between">
                <span className="text-sm text-[var(--muted)]">Cảnh báo</span>
                <StatusBadge value={prediction.data.alert_state} />
              </div>
              <div className="grid grid-cols-3 gap-3 border-y border-[var(--rule)] py-5 text-center">
                <Count label="Trống" value={prediction.data.empty_count} />
                <Count
                  label="Đã chiếm"
                  value={prediction.data.occupied_count}
                />
                <Count label="Không rõ" value={prediction.data.unknown_count} />
              </div>
              <p className="text-xs text-[var(--muted)]">
                Tổng {prediction.data.total_spots} vùng · Mô hình{' '}
                {prediction.data.model_version || 'Chưa rõ'}
              </p>
              <Link
                to={`/review/${prediction.data.snapshot_id}`}
                className="text-link"
              >
                Xem và duyệt dự đoán →
              </Link>
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <p className="text-2xl tabular-nums">{value}</p>
      <p className="mt-1 text-xs text-[var(--muted)]">{label}</p>
    </div>
  )
}
