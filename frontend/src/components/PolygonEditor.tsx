import { useEffect, useMemo, useRef, useState } from 'react'
import type { PointerEvent as ReactPointerEvent } from 'react'
import type { Spot } from '../lib/api'
import {
  panView,
  screenToNormalized,
  validatePolygon,
  zoomView,
} from '../lib/polygonGeometry'
import type { ImageSize, Point, ViewBox } from '../lib/polygonGeometry'

export interface EditableSpot {
  id?: string
  code: string
  points: Point[]
}
interface Draft extends EditableSpot {
  key: string
}
interface Props {
  imageUrl: string
  image: ImageSize
  spots: Spot[]
  canEdit: boolean
  onSave: (
    items: EditableSpot[],
  ) => Promise<{ warnings: Array<{ code: string; spot_ids: string[] }> } | void>
  onDelete: (id: string) => Promise<void>
}

function nextCode(spots: Spot[], drafts: Draft[]): string {
  const used = new Set([
    ...spots.map((spot) => spot.code),
    ...drafts.map((spot) => spot.code),
  ])
  let number = 1
  while (used.has(`S${String(number).padStart(2, '0')}`)) number += 1
  return `S${String(number).padStart(2, '0')}`
}

export default function PolygonEditor({
  imageUrl,
  image,
  spots,
  canEdit,
  onSave,
  onDelete,
}: Props) {
  const [drafts, setDrafts] = useState<Draft[]>(() =>
    spots
      .filter((spot) => spot.is_active && spot.polygon)
      .map((spot) => ({
        key: spot.id,
        id: spot.id,
        code: spot.code,
        points: spot.polygon!.points,
      })),
  )
  const [selected, setSelected] = useState<string | null>(null)
  const [selectedVertex, setSelectedVertex] = useState(0)
  const [drawing, setDrawing] = useState<Point[] | null>(null)
  const [panMode, setPanMode] = useState(false)
  const [view, setView] = useState<ViewBox>({ x: 0, y: 0, ...image })
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const drag = useRef<{ key: string; index: number } | null>(null)
  const pan = useRef<{
    clientX: number
    clientY: number
    view: ViewBox
  } | null>(null)

  const issues = useMemo(() => {
    const result = new Map<string, string>()
    const codes = drafts.map((spot) => spot.code.trim().toUpperCase())
    const inactive = new Set(
      spots.filter((spot) => !spot.is_active).map((spot) => spot.code),
    )
    for (const spot of drafts) {
      const code = spot.code.trim().toUpperCase()
      const geometryError = validatePolygon(spot.points, image)
      if (geometryError) result.set(spot.key, geometryError)
      else if (!code || code.length > 40)
        result.set(spot.key, 'Mã vùng phải có từ 1 đến 40 ký tự.')
      else if (
        codes.filter((item) => item === code).length > 1 ||
        inactive.has(code)
      )
        result.set(spot.key, 'Mã vùng đã tồn tại trong camera này.')
    }
    return result
  }, [drafts, image, spots])
  const selectedDraft = drafts.find((spot) => spot.key === selected)

  useEffect(() => {
    if (drawing === null) return
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDrawing(null)
      if (
        event.key === 'Backspace' &&
        !(event.target instanceof HTMLInputElement)
      ) {
        event.preventDefault()
        setDrawing((current) => current?.slice(0, -1) ?? null)
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [drawing])

  useEffect(() => {
    if (!dirty && drawing === null) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty, drawing])

  function position(event: ReactPointerEvent<SVGSVGElement>): Point | null {
    const rect = event.currentTarget.getBoundingClientRect()
    if (!rect.width || !rect.height) return null
    return screenToNormalized(event.clientX, event.clientY, image, view, rect)
  }

  function pointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (panMode || event.button === 1) {
      pan.current = { clientX: event.clientX, clientY: event.clientY, view }
      event.currentTarget.setPointerCapture?.(event.pointerId)
      return
    }
    if (!canEdit || drawing === null) return
    const point = position(event)
    if (point && point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1)
      setDrawing((current) => [...(current ?? []), point])
  }

  function pointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    if (pan.current) {
      const rect = event.currentTarget.getBoundingClientRect()
      if (!rect.width || !rect.height) return
      setView(
        panView(
          pan.current.view,
          image,
          ((pan.current.clientX - event.clientX) / rect.width) *
            pan.current.view.width,
          ((pan.current.clientY - event.clientY) / rect.height) *
            pan.current.view.height,
        ),
      )
    } else if (drag.current) {
      const point = position(event)
      if (!point) return
      const bounded = {
        x: Math.max(0, Math.min(1, point.x)),
        y: Math.max(0, Math.min(1, point.y)),
      }
      const { key, index } = drag.current
      setDrafts((current) =>
        current.map((spot) =>
          spot.key === key
            ? {
                ...spot,
                points: spot.points.map((vertex, offset) =>
                  offset === index ? bounded : vertex,
                ),
              }
            : spot,
        ),
      )
      setDirty(true)
    }
  }

  function finishDrawing() {
    if (drawing === null) return
    const error = validatePolygon(drawing, image)
    if (error) {
      setMessage(error)
      return
    }
    const key = `new-${crypto.randomUUID()}`
    setDrafts((current) => [
      ...current,
      { key, code: nextCode(spots, current), points: drawing },
    ])
    setSelected(key)
    setSelectedVertex(0)
    setDrawing(null)
    setDirty(true)
    setMessage(null)
  }

  function updateCoordinate(axis: 'x' | 'y', value: string) {
    if (!selectedDraft) return
    const index = Math.min(selectedVertex, selectedDraft.points.length - 1)
    const number = value === '' ? 0 : Number(value)
    setDrafts((current) =>
      current.map((spot) =>
        spot.key === selectedDraft.key
          ? {
              ...spot,
              points: spot.points.map((point, offset) =>
                offset === index ? { ...point, [axis]: number } : point,
              ),
            }
          : spot,
      ),
    )
    setDirty(true)
  }

  async function save() {
    if (!dirty || issues.size) return
    setBusy(true)
    setMessage(null)
    try {
      const result = await onSave(
        drafts.map(({ id, code, points }) => ({
          ...(id ? { id } : {}),
          code: code.trim().toUpperCase(),
          points,
        })),
      )
      setDirty(false)
      setMessage(
        result?.warnings.length
          ? `Đã lưu. Có ${result.warnings.length} cặp vùng chồng lấn cần kiểm tra.`
          : 'Đã lưu vùng đỗ.',
      )
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : 'Không thể lưu vùng đỗ.',
      )
    } finally {
      setBusy(false)
    }
  }

  async function removeSelected() {
    if (!selectedDraft || !window.confirm(`Xóa vùng ${selectedDraft.code}?`))
      return
    setBusy(true)
    setMessage(null)
    try {
      if (selectedDraft.id) await onDelete(selectedDraft.id)
      setDrafts((current) =>
        current.filter((spot) => spot.key !== selectedDraft.key),
      )
      if (!selectedDraft.id) setDirty(true)
      setSelected(null)
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : 'Không thể xóa vùng đỗ.',
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="polygon-editor">
      <div className="polygon-toolbar">
        <span className="text-xs text-[var(--muted)]">
          Ảnh tham chiếu · {image.width} × {image.height} px · {drafts.length}{' '}
          vùng
        </span>
        <div className="polygon-tools">
          {canEdit && drawing === null && (
            <button
              type="button"
              className="secondary-button"
              onClick={() => {
                setDrawing([])
                setPanMode(false)
                setMessage(null)
              }}
            >
              Vẽ vùng mới
            </button>
          )}
          {drawing !== null && (
            <>
              <button
                type="button"
                className="secondary-button"
                onClick={() =>
                  setDrawing((current) => current?.slice(0, -1) ?? null)
                }
                disabled={!drawing.length}
              >
                Hoàn tác đỉnh
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={() => {
                  setDrawing(null)
                  setMessage(null)
                }}
              >
                Hủy vẽ
              </button>
              <button
                type="button"
                className="primary-button"
                onClick={finishDrawing}
                disabled={drawing.length < 3}
              >
                Hoàn tất đa giác
              </button>
            </>
          )}
          <button
            type="button"
            className="secondary-button"
            aria-pressed={panMode}
            onClick={() => {
              setPanMode(!panMode)
              setDrawing(null)
            }}
          >
            Di chuyển ảnh
          </button>
          <button
            type="button"
            className="secondary-button"
            aria-label="Phóng to"
            onClick={() =>
              setView((current) =>
                zoomView(current, image, 1.5, {
                  x: (current.x + current.width / 2) / image.width,
                  y: (current.y + current.height / 2) / image.height,
                }),
              )
            }
          >
            +
          </button>
          <button
            type="button"
            className="secondary-button"
            aria-label="Thu nhỏ"
            onClick={() =>
              setView((current) =>
                zoomView(current, image, 1 / 1.5, {
                  x: (current.x + current.width / 2) / image.width,
                  y: (current.y + current.height / 2) / image.height,
                }),
              )
            }
          >
            −
          </button>
          <button
            type="button"
            className="secondary-button"
            onClick={() => setView({ x: 0, y: 0, ...image })}
          >
            Vừa ảnh
          </button>
        </div>
      </div>
      <div className="polygon-workspace">
        <div className="polygon-canvas-wrap">
          <svg
            aria-label="Ảnh tham chiếu và vùng đỗ"
            role="img"
            viewBox={`${view.x} ${view.y} ${view.width} ${view.height}`}
            style={{
              aspectRatio: `${image.width} / ${image.height}`,
              cursor:
                drawing !== null ? 'crosshair' : panMode ? 'grab' : 'default',
            }}
            onPointerDown={pointerDown}
            onPointerMove={pointerMove}
            onPointerUp={() => {
              pan.current = null
              drag.current = null
            }}
            onPointerCancel={() => {
              pan.current = null
              drag.current = null
            }}
          >
            <image
              href={imageUrl}
              x="0"
              y="0"
              width={image.width}
              height={image.height}
            />
            {drafts.map((spot) => {
              const invalid = issues.has(spot.key)
              const active = selected === spot.key
              const points = spot.points
                .map(
                  (point) =>
                    `${point.x * image.width},${point.y * image.height}`,
                )
                .join(' ')
              const center = spot.points.reduce(
                (sum, point) => ({ x: sum.x + point.x, y: sum.y + point.y }),
                { x: 0, y: 0 },
              )
              return (
                <g key={spot.key}>
                  <polygon
                    points={points}
                    className={`spot-polygon ${invalid ? 'spot-invalid' : active ? 'spot-selected' : ''}`}
                    onPointerDown={(event) => {
                      if (drawing === null && !panMode) {
                        event.stopPropagation()
                        setSelected(spot.key)
                        setSelectedVertex(0)
                      }
                    }}
                  />
                  <text
                    x={(center.x / spot.points.length) * image.width}
                    y={(center.y / spot.points.length) * image.height}
                    className="spot-label"
                    textAnchor="middle"
                    dominantBaseline="middle"
                    pointerEvents="none"
                  >
                    {spot.code}
                  </text>
                  {canEdit &&
                    active &&
                    drawing === null &&
                    spot.points.map((point, index) => (
                      <circle
                        key={index}
                        cx={point.x * image.width}
                        cy={point.y * image.height}
                        r={Math.max(14, view.width / 50)}
                        className="spot-vertex"
                        aria-label={`Đỉnh ${index + 1} của ${spot.code}`}
                        onPointerDown={(event) => {
                          event.stopPropagation()
                          drag.current = { key: spot.key, index }
                          event.currentTarget.setPointerCapture?.(
                            event.pointerId,
                          )
                        }}
                      />
                    ))}
                </g>
              )
            })}
            {drawing !== null && (
              <polyline
                points={drawing
                  .map(
                    (point) =>
                      `${point.x * image.width},${point.y * image.height}`,
                  )
                  .join(' ')}
                className="spot-drawing"
              />
            )}
          </svg>
        </div>
        <aside className="polygon-list" aria-label="Danh sách vùng đỗ">
          <div className="polygon-list-heading">Vùng đỗ trên ảnh</div>
          {drafts.length === 0 ? (
            <p className="polygon-list-empty">
              Chưa có vùng nào. Chọn “Vẽ vùng mới” rồi bấm các đỉnh trên ảnh.
            </p>
          ) : (
            <div className="polygon-rows">
              {drafts.map((spot) => (
                <button
                  key={spot.key}
                  type="button"
                  className={`polygon-row ${selected === spot.key ? 'polygon-row-selected' : ''}`}
                  onClick={() => {
                    setSelected(spot.key)
                    setSelectedVertex(0)
                  }}
                >
                  <span
                    className={`polygon-row-dot ${issues.has(spot.key) ? 'polygon-row-error' : ''}`}
                    aria-hidden="true"
                  />
                  <span>{spot.code}</span>
                  <span className="polygon-row-meta">
                    {issues.has(spot.key)
                      ? 'Cần sửa'
                      : `${spot.points.length} đỉnh`}
                  </span>
                </button>
              ))}
            </div>
          )}
          {selectedDraft && canEdit && (
            <div className="polygon-inspector">
              <label
                htmlFor="spot-code"
                className="text-xs text-[var(--muted)]"
              >
                Mã vùng đỗ
              </label>
              <input
                id="spot-code"
                name="spot-code"
                autoComplete="off"
                spellCheck={false}
                className="input mt-2 w-full"
                value={selectedDraft.code}
                maxLength={40}
                onChange={(event) => {
                  const value = event.target.value
                  setDrafts((current) =>
                    current.map((spot) =>
                      spot.key === selected ? { ...spot, code: value } : spot,
                    ),
                  )
                  setDirty(true)
                }}
              />
              <label
                htmlFor="spot-vertex"
                className="mt-4 block text-xs text-[var(--muted)]"
              >
                Đỉnh đang sửa
              </label>
              <select
                id="spot-vertex"
                className="input mt-2 w-full"
                value={Math.min(
                  selectedVertex,
                  selectedDraft.points.length - 1,
                )}
                onChange={(event) =>
                  setSelectedVertex(Number(event.target.value))
                }
              >
                {selectedDraft.points.map((_, index) => (
                  <option key={index} value={index}>
                    Đỉnh {index + 1}
                  </option>
                ))}
              </select>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <label className="text-xs text-[var(--muted)]">
                  Tọa độ X
                  <input
                    type="number"
                    name="vertex-x"
                    min="0"
                    max="1"
                    step="0.001"
                    inputMode="decimal"
                    className="input mt-1 w-full"
                    value={
                      selectedDraft.points[
                        Math.min(
                          selectedVertex,
                          selectedDraft.points.length - 1,
                        )
                      ].x
                    }
                    onChange={(event) =>
                      updateCoordinate('x', event.target.value)
                    }
                  />
                </label>
                <label className="text-xs text-[var(--muted)]">
                  Tọa độ Y
                  <input
                    type="number"
                    name="vertex-y"
                    min="0"
                    max="1"
                    step="0.001"
                    inputMode="decimal"
                    className="input mt-1 w-full"
                    value={
                      selectedDraft.points[
                        Math.min(
                          selectedVertex,
                          selectedDraft.points.length - 1,
                        )
                      ].y
                    }
                    onChange={(event) =>
                      updateCoordinate('y', event.target.value)
                    }
                  />
                </label>
              </div>
              {issues.get(selectedDraft.key) && (
                <p className="polygon-error" role="alert">
                  {issues.get(selectedDraft.key)}
                </p>
              )}
              <p className="mt-3 text-xs text-[var(--muted)]">
                Kéo các điểm tròn để sửa. Tọa độ được lưu theo ảnh gốc.
              </p>
              <button
                type="button"
                className="text-link mt-4"
                onClick={removeSelected}
                disabled={busy}
              >
                Xóa vùng đỗ
              </button>
            </div>
          )}
        </aside>
      </div>
      <div className="polygon-footer">
        <p className="text-xs text-[var(--muted)]">
          {drawing !== null
            ? 'Bấm lần lượt các đỉnh; Esc để hủy, Backspace để hoàn tác.'
            : 'Chọn vùng để sửa. Di chuyển và phóng to không đổi tọa độ đã lưu.'}
        </p>
        {canEdit && (
          <button
            type="button"
            className="primary-button"
            onClick={save}
            disabled={!dirty || busy || issues.size > 0 || drawing !== null}
          >
            Lưu vùng đỗ
          </button>
        )}
      </div>
      {message && (
        <p
          className={
            message.startsWith('Đã lưu') ? 'polygon-success' : 'polygon-error'
          }
          role="status"
        >
          {message}
        </p>
      )}
    </div>
  )
}
