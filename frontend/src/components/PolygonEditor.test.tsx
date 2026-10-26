import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import PolygonEditor from './PolygonEditor'
import type { EditableSpot } from './PolygonEditor'
import type { Spot } from '../lib/api'

const spots: Spot[] = Array.from({ length: 10 }, (_, index) => ({
  id: `spot-${index}`,
  code: `S${String(index + 1).padStart(2, '0')}`,
  is_active: true,
  geometry_status: 'current',
  polygon: {
    points: [
      { x: index * 0.09, y: 0.1 },
      { x: index * 0.09 + 0.05, y: 0.1 },
      { x: index * 0.09 + 0.05, y: 0.2 },
      { x: index * 0.09, y: 0.2 },
    ],
  },
}))

afterEach(() => cleanup())

test('creates an eleventh spot, saves stable IDs and preserves coordinates after zoom', async () => {
  const user = userEvent.setup()
  const onSave = vi.fn(async (items: EditableSpot[]) => {
    void items
  })
  render(
    <PolygonEditor
      imageUrl="blob:reference"
      image={{ width: 1200, height: 800 }}
      spots={spots}
      canEdit
      onSave={onSave}
      onDelete={vi.fn(async () => {})}
    />,
  )
  const canvas = screen.getByLabelText('Ảnh tham chiếu và vùng đỗ')
  expect(canvas.querySelectorAll('polygon')).toHaveLength(10)
  const originalPoints = canvas.querySelector('polygon')?.getAttribute('points')
  expect(originalPoints).toBe('0,80 60,80 60,160 0,160')
  vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
    left: 0,
    top: 0,
    width: 900,
    height: 600,
    right: 900,
    bottom: 600,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })
  await user.click(screen.getByRole('button', { name: 'Vẽ vùng mới' }))
  for (const [x, y] of [
    [810, 300],
    [855, 300],
    [855, 360],
    [810, 360],
  ]) {
    fireEvent.pointerDown(canvas, { clientX: x, clientY: y, pointerId: 1 })
  }
  await user.click(screen.getByRole('button', { name: 'Hoàn tất đa giác' }))
  expect(screen.getByDisplayValue('S11')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Phóng to' }))
  expect(canvas.querySelector('polygon')?.getAttribute('points')).toBe(
    originalPoints,
  )
  await user.click(screen.getByRole('button', { name: 'Lưu vùng đỗ' }))
  expect(onSave).toHaveBeenCalledTimes(1)
  const saved = onSave.mock.calls[0]![0]
  expect(saved).toHaveLength(11)
  expect(saved[0].id).toBe('spot-0')
  expect(saved[10]).toEqual({
    code: 'S11',
    points: [
      { x: 0.9, y: 0.5 },
      { x: 0.95, y: 0.5 },
      { x: 0.95, y: 0.6 },
      { x: 0.9, y: 0.6 },
    ],
  })
})

test('can cancel unfinished drawing without saving an unchanged set', async () => {
  const user = userEvent.setup()
  const onSave = vi.fn(async () => {})
  render(
    <PolygonEditor
      imageUrl="blob:reference"
      image={{ width: 1200, height: 800 }}
      spots={spots}
      canEdit
      onSave={onSave}
      onDelete={vi.fn(async () => {})}
    />,
  )
  await user.click(screen.getByRole('button', { name: 'Vẽ vùng mới' }))
  await user.click(screen.getByRole('button', { name: 'Hủy vẽ' }))
  expect(
    screen.queryByRole('button', { name: 'Hoàn tất đa giác' }),
  ).not.toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Lưu vùng đỗ' }))
  expect(onSave).not.toHaveBeenCalled()
})

test('dragging a vertex stores normalized image coordinates and rejects a duplicate code', async () => {
  const user = userEvent.setup()
  const onSave = vi.fn(async (items: EditableSpot[]) => {
    void items
  })
  render(
    <PolygonEditor
      imageUrl="blob:reference"
      image={{ width: 1200, height: 800 }}
      spots={spots}
      canEdit
      onSave={onSave}
      onDelete={vi.fn(async () => {})}
    />,
  )
  const canvas = screen.getByLabelText('Ảnh tham chiếu và vùng đỗ')
  vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({
    left: 0,
    top: 0,
    width: 900,
    height: 600,
    right: 900,
    bottom: 600,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })
  await user.click(screen.getByRole('button', { name: /S01/ }))
  fireEvent.pointerDown(screen.getByLabelText('Đỉnh 2 của S01'), {
    pointerId: 1,
  })
  fireEvent.pointerMove(canvas, { clientX: 54, clientY: 60, pointerId: 1 })
  fireEvent.pointerUp(canvas, { pointerId: 1 })
  await user.click(screen.getByRole('button', { name: 'Lưu vùng đỗ' }))
  expect(onSave.mock.calls[0]![0][0].points[1]).toEqual({ x: 0.06, y: 0.1 })

  await user.clear(screen.getByLabelText('Mã vùng đỗ'))
  await user.type(screen.getByLabelText('Mã vùng đỗ'), 'S02')
  expect(screen.getByRole('alert')).toHaveTextContent('Mã vùng đã tồn tại')
  expect(screen.getByRole('button', { name: 'Lưu vùng đỗ' })).toBeDisabled()
})

test('shows server overlap warnings after a bulk save', async () => {
  const user = userEvent.setup()
  render(
    <PolygonEditor
      imageUrl="blob:reference"
      image={{ width: 1200, height: 800 }}
      spots={spots}
      canEdit
      onSave={async () => ({
        warnings: [{ code: 'POLYGON_OVERLAP', spot_ids: ['spot-0', 'spot-1'] }],
      })}
      onDelete={async () => {}}
    />,
  )
  await user.click(screen.getByRole('button', { name: /S01/ }))
  await user.clear(screen.getByLabelText('Mã vùng đỗ'))
  await user.type(screen.getByLabelText('Mã vùng đỗ'), 'A01')
  await user.click(screen.getByRole('button', { name: 'Lưu vùng đỗ' }))
  expect(await screen.findByRole('status')).toHaveTextContent('chồng lấn')
})

test('lets Admin adjust a vertex with keyboard-accessible coordinate inputs', async () => {
  const user = userEvent.setup()
  const onSave = vi.fn(async (items: EditableSpot[]) => {
    void items
  })
  render(
    <PolygonEditor
      imageUrl="blob:reference"
      image={{ width: 1200, height: 800 }}
      spots={spots}
      canEdit
      onSave={onSave}
      onDelete={async () => {}}
    />,
  )
  await user.click(screen.getByRole('button', { name: /S01/ }))
  await user.clear(screen.getByLabelText('Tọa độ X'))
  await user.type(screen.getByLabelText('Tọa độ X'), '0.01')
  await user.click(screen.getByRole('button', { name: 'Lưu vùng đỗ' }))
  expect(onSave.mock.calls[0]![0][0].points[0]).toEqual({ x: 0.01, y: 0.1 })
})

test('warns before leaving with unsaved polygon edits', async () => {
  const user = userEvent.setup()
  render(
    <PolygonEditor
      imageUrl="blob:reference"
      image={{ width: 1200, height: 800 }}
      spots={spots}
      canEdit
      onSave={async () => {}}
      onDelete={async () => {}}
    />,
  )
  await user.click(screen.getByRole('button', { name: /S01/ }))
  await user.clear(screen.getByLabelText('Mã vùng đỗ'))
  await user.type(screen.getByLabelText('Mã vùng đỗ'), 'A01')
  const event = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(true)
})

test('Operator can inspect polygons but has no editing controls', () => {
  render(
    <PolygonEditor
      imageUrl="blob:reference"
      image={{ width: 1200, height: 800 }}
      spots={spots}
      canEdit={false}
      onSave={async () => {}}
      onDelete={async () => {}}
    />,
  )
  expect(
    screen
      .getByLabelText('Ảnh tham chiếu và vùng đỗ')
      .querySelectorAll('polygon'),
  ).toHaveLength(10)
  expect(
    screen.queryByRole('button', { name: 'Vẽ vùng mới' }),
  ).not.toBeInTheDocument()
  expect(
    screen.queryByRole('button', { name: 'Lưu vùng đỗ' }),
  ).not.toBeInTheDocument()
})
