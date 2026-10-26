import { useQuery } from '@tanstack/react-query'
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageTitle,
  Panel,
} from '../components/ui'
import { ApiError } from '../lib/api'
import type { Camera, Spot } from '../lib/api'
import { useAuth } from '../lib/auth'

export default function ConfigurationPage() {
  const { request, session } = useAuth()
  const camera = useQuery({
    queryKey: ['camera', 'current'],
    queryFn: () => request<Camera>('/cameras/current'),
  })
  const spots = useQuery({
    queryKey: ['spots', camera.data?.id],
    queryFn: () =>
      request<{ items: Spot[] }>(`/cameras/${camera.data!.id}/spots`),
    enabled: !!camera.data,
  })
  const noCamera =
    camera.error instanceof ApiError && camera.error.status === 404

  return (
    <div className="space-y-8">
      <PageTitle
        title="Cấu hình bãi đỗ"
        description="Camera cố định và các vùng đỗ đang được sử dụng để phân tích."
      />
      <Panel title="Camera hiện tại">
        {camera.isPending ? (
          <LoadingState />
        ) : noCamera ? (
          <EmptyState
            title="Chưa có camera"
            description="Admin cần cấu hình bãi đỗ, ảnh tham chiếu và camera qua API trước khi phân tích ảnh."
          />
        ) : camera.isError ? (
          <ErrorState retry={() => camera.refetch()} />
        ) : (
          <div className="grid gap-5 p-5 sm:grid-cols-3">
            <Detail label="Tên camera" value={camera.data.name} />
            <Detail
              label="Trạng thái"
              value={camera.data.is_active ? 'Đang hoạt động' : 'Tạm ngừng'}
            />
            <Detail
              label="Phiên bản góc nhìn"
              value={String(camera.data.viewpoint_version)}
            />
            <Detail
              label="Ảnh tham chiếu"
              value={
                camera.data.reference_image
                  ? `${camera.data.reference_image.width} × ${camera.data.reference_image.height} px`
                  : 'Chưa thiết lập'
              }
            />
          </div>
        )}
      </Panel>
      {camera.data && (
        <Panel
          title="Vùng đỗ"
          action={
            <span className="text-xs text-[var(--muted)]">
              {session?.user.role === 'admin'
                ? 'Chỉnh sửa hình học qua API quản trị'
                : 'Chỉ xem'}
            </span>
          }
        >
          {spots.isPending ? (
            <LoadingState />
          ) : spots.isError ? (
            <ErrorState retry={() => spots.refetch()} />
          ) : spots.data.items.length === 0 ? (
            <EmptyState
              title="Chưa có vùng đỗ"
              description="Các đa giác cần được gắn với ảnh tham chiếu của camera."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">Mã vùng</th>
                    <th scope="col">Trạng thái</th>
                    <th scope="col">Hình học</th>
                    <th scope="col">Đỉnh</th>
                  </tr>
                </thead>
                <tbody>
                  {spots.data.items.map((spot) => (
                    <tr key={spot.id}>
                      <td className="font-semibold">{spot.code}</td>
                      <td>{spot.is_active ? 'Hoạt động' : 'Tạm ngừng'}</td>
                      <td>
                        {spot.geometry_status === 'current'
                          ? 'Sẵn sàng'
                          : 'Cần hiệu chỉnh'}
                      </td>
                      <td>{spot.polygon?.points.length ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      )}
    </div>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-[var(--muted)]">{label}</p>
      <p className="mt-1 text-sm font-medium">{value}</p>
    </div>
  )
}
