import { describe, expect, test } from 'vitest'
import {
  imageToScreen,
  panView,
  screenToNormalized,
  validatePolygon,
  zoomView,
} from './polygonGeometry'

const image = { width: 1200, height: 800 }

describe('reference image geometry', () => {
  test('round-trips normalized vertices across viewport resizing and zoom', () => {
    const point = { x: 0.625, y: 0.375 }
    const full = { x: 0, y: 0, width: 1200, height: 800 }
    const zoomed = zoomView(full, image, 2, { x: 0.5, y: 0.5 })
    for (const [view, rect] of [
      [full, { left: 20, top: 30, width: 900, height: 600 }],
      [zoomed, { left: 50, top: 70, width: 450, height: 300 }],
    ] as const) {
      const screen = imageToScreen(point, image, view, rect)
      expect(screenToNormalized(screen.x, screen.y, image, view, rect)).toEqual(
        {
          x: point.x,
          y: point.y,
        },
      )
    }
    expect(zoomed).toEqual({ x: 300, y: 200, width: 600, height: 400 })
    expect(panView(zoomed, image, 1000, -1000)).toEqual({
      x: 600,
      y: 0,
      width: 600,
      height: 400,
    })
  })

  test('rejects tiny, crossed, duplicate and out-of-bounds polygons', () => {
    expect(
      validatePolygon(
        [
          { x: 0.1, y: 0.1 },
          { x: 0.1001, y: 0.1 },
          { x: 0.1001, y: 0.1001 },
        ],
        image,
      ),
    ).toMatch(/quá nhỏ/)
    expect(
      validatePolygon(
        [
          { x: 0.1, y: 0.1 },
          { x: 0.9, y: 0.9 },
          { x: 0.1, y: 0.9 },
          { x: 0.9, y: 0.1 },
        ],
        image,
      ),
    ).toMatch(/cắt nhau/)
    expect(
      validatePolygon(
        [
          { x: 0.1, y: 0.1 },
          { x: 0.1, y: 0.1 },
          { x: 0.2, y: 0.2 },
        ],
        image,
      ),
    ).not.toBeNull()
    expect(
      validatePolygon(
        [
          { x: -0.01, y: 0.1 },
          { x: 0.2, y: 0.1 },
          { x: 0.2, y: 0.2 },
        ],
        image,
      ),
    ).toMatch(/ngoài ảnh/)
  })
})
