import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import type { ChangeEvent } from 'react'
import PolygonEditor from '../components/PolygonEditor'
import type { EditableSpot } from '../components/PolygonEditor'
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
  const { request, blob, session } = useAuth()
  const queryClient = useQueryClient()
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [saveNotice, setSaveNotice] = useState<string | null>(null)
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const camera = useQuery({
    queryKey: ['camera', 'current'],
    queryFn: () => request<Camera>('/cameras/current'),
  })
  const spots = useQuery({
    queryKey: ['spots', camera.data?.id],
    queryFn: () =>
      request<{ items: Spot[] }>(`/cameras/${camera.data!.id}/spots`),
    enabled: !!camera.data,
    refetchOnWindowFocus: false,
  })
  const reference = useQuery({
    queryKey: [
      'reference-image',
      camera.data?.id,
      camera.data?.reference_image?.sha256,
    ],
    queryFn: async () => {
      try {
        return await blob(`/cameras/${camera.data!.id}/reference-image`)
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null
        throw error
      }
    },
    enabled: !!camera.data?.reference_image,
    refetchOnWindowFocus: false,
  })

  useEffect(() => {
    if (!reference.data) {
      setImageUrl(null)
      return
    }
    const url = URL.createObjectURL(reference.data)
    setImageUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [reference.data])

  const noCamera =
    camera.error instanceof ApiError && camera.error.status === 404
  const canEdit =
    session?.user.role === 'admin' && camera.data?.is_active === true

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file || !camera.data) return
    setUploading(true)
    setUploadError(null)
    const form = new FormData()
    form.append('file', file)
    try {
      await request(`/cameras/${camera.data.id}/reference-image`, {
        method: 'PUT',
        body: form,
      })
      await queryClient.invalidateQueries({
        queryKey: ['reference-image', camera.data.id],
      })
    } catch (error) {
      setUploadError(
        error instanceof Error
          ? error.message
          : 'Không thể tải ảnh tham chiếu.',
      )
    } finally {
      setUploading(false)
      event.target.value = ''
    }
  }

  async function save(items: EditableSpot[]) {
    if (!camera.data) return
    setSaveNotice(null)
    const result = await request<{
      warnings: Array<{ code: string; spot_ids: string[] }>
    }>(`/cameras/${camera.data.id}/spots/bulk`, {
      method: 'PUT',
      body: JSON.stringify({ items }),
    })
    setSaveNotice(
      result.warnings.length
        ? `Đã lưu. Có ${result.warnings.length} cặp vùng chồng lấn cần kiểm tra.`
        : 'Đã lưu vùng đỗ.',
    )
    await queryClient.invalidateQueries({ queryKey: ['spots', camera.data.id] })
    return result
  }

  async function remove(id: string) {
    setSaveNotice(null)
    await request(`/spots/${id}`, { method: 'DELETE' })
    await queryClient.invalidateQueries({
      queryKey: ['spots', camera.data?.id],
    })
  }

  return (
    <div className="space-y-8">
      <PageTitle
        title="Cấu hình bãi đỗ"
        description="Hiệu chỉnh các vùng đỗ theo ảnh tham chiếu của camera cố định."
      />
      <Panel title="Camera hiện tại">
        {camera.isPending ? (
          <LoadingState />
        ) : noCamera ? (
          <EmptyState
            title="Chưa có camera"
            description="Admin cần tạo bãi đỗ và camera với ảnh tham chiếu qua API trước khi vẽ vùng đỗ."
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
            <Detail label="Camera ID" value={camera.data.id} />
          </div>
        )}
      </Panel>
      {camera.data && (
        <Panel
          title="Biên tập vùng đỗ"
          action={
            <span className="text-xs text-[var(--muted)]">
              {canEdit ? 'Quyền Admin' : 'Chỉ xem'}
            </span>
          }
        >
          {!camera.data.reference_image ? (
            <EmptyState
              title="Chưa có ảnh tham chiếu"
              description="Cần khai báo fingerprint và kích thước ảnh cho camera qua API trước khi vẽ."
            />
          ) : reference.isPending ? (
            <LoadingState />
          ) : reference.isError ? (
            <ErrorState retry={() => reference.refetch()} />
          ) : !imageUrl ? (
            <div className="reference-empty">
              <p className="font-medium">Ảnh tham chiếu chưa được tải lên</p>
              <p className="mt-2 text-sm text-[var(--muted)]">
                Chọn đúng tệp JPEG/PNG đã dùng để khai báo SHA-256 và kích thước
                cho camera này. Ảnh được lưu riêng tư trên backend.
              </p>
              {canEdit && (
                <label className="secondary-button mt-4 inline-flex cursor-pointer">
                  Tải ảnh tham chiếu
                  <input
                    aria-label="Tải ảnh tham chiếu"
                    type="file"
                    accept="image/jpeg,image/png"
                    className="sr-only"
                    onChange={upload}
                    disabled={uploading}
                  />
                </label>
              )}
              {uploading && <p className="mt-3 text-sm">Đang tải ảnh...</p>}
              {uploadError && (
                <p role="alert" className="polygon-error">
                  {uploadError}
                </p>
              )}
            </div>
          ) : spots.isPending ? (
            <LoadingState />
          ) : spots.isError ? (
            <ErrorState retry={() => spots.refetch()} />
          ) : (
            <PolygonEditor
              key={`${camera.data.id}:${spots.dataUpdatedAt}`}
              imageUrl={imageUrl}
              image={camera.data.reference_image}
              spots={spots.data.items}
              canEdit={canEdit}
              onSave={save}
              onDelete={remove}
            />
          )}
          {saveNotice && (
            <p className="polygon-success" role="status">
              {saveNotice}
            </p>
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
      <p className="mt-1 break-all text-sm font-medium">{value}</p>
    </div>
  )
}
