export interface Point {
  x: number
  y: number
}

export interface ImageSize {
  width: number
  height: number
}

export interface ViewBox extends ImageSize {
  x: number
  y: number
}

export interface ScreenRect {
  left: number
  top: number
  width: number
  height: number
}

export function imageToScreen(
  point: Point,
  image: ImageSize,
  view: ViewBox,
  rect: ScreenRect,
): Point {
  return {
    x: rect.left + ((point.x * image.width - view.x) / view.width) * rect.width,
    y:
      rect.top +
      ((point.y * image.height - view.y) / view.height) * rect.height,
  }
}

export function screenToNormalized(
  clientX: number,
  clientY: number,
  image: ImageSize,
  view: ViewBox,
  rect: ScreenRect,
): Point {
  return {
    x:
      (view.x + ((clientX - rect.left) / rect.width) * view.width) /
      image.width,
    y:
      (view.y + ((clientY - rect.top) / rect.height) * view.height) /
      image.height,
  }
}

export function zoomView(
  view: ViewBox,
  image: ImageSize,
  factor: number,
  center: Point,
): ViewBox {
  const width = Math.max(
    image.width / 8,
    Math.min(image.width, view.width / factor),
  )
  const height = (width / image.width) * image.height
  return {
    x: Math.max(
      0,
      Math.min(image.width - width, center.x * image.width - width / 2),
    ),
    y: Math.max(
      0,
      Math.min(image.height - height, center.y * image.height - height / 2),
    ),
    width,
    height,
  }
}

export function panView(
  view: ViewBox,
  image: ImageSize,
  dx: number,
  dy: number,
): ViewBox {
  return {
    ...view,
    x: Math.max(0, Math.min(image.width - view.width, view.x + dx)),
    y: Math.max(0, Math.min(image.height - view.height, view.y + dy)),
  }
}

function cross(a: Point, b: Point, c: Point): number {
  return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x)
}

function onSegment(a: Point, b: Point, c: Point): boolean {
  return (
    Math.min(a.x, b.x) <= c.x &&
    c.x <= Math.max(a.x, b.x) &&
    Math.min(a.y, b.y) <= c.y &&
    c.y <= Math.max(a.y, b.y)
  )
}

function intersects(a: Point, b: Point, c: Point, d: Point): boolean {
  const abC = cross(a, b, c)
  const abD = cross(a, b, d)
  const cdA = cross(c, d, a)
  const cdB = cross(c, d, b)
  return (
    (abC * abD < 0 && cdA * cdB < 0) ||
    (abC === 0 && onSegment(a, b, c)) ||
    (abD === 0 && onSegment(a, b, d)) ||
    (cdA === 0 && onSegment(c, d, a)) ||
    (cdB === 0 && onSegment(c, d, b))
  )
}

export function validatePolygon(
  points: Point[],
  image: ImageSize,
): string | null {
  if (points.length < 3) return 'Cần ít nhất 3 đỉnh.'
  if (
    points.some(
      (point) =>
        !Number.isFinite(point.x) ||
        !Number.isFinite(point.y) ||
        point.x < 0 ||
        point.x > 1 ||
        point.y < 0 ||
        point.y > 1,
    )
  )
    return 'Có đỉnh nằm ngoài ảnh tham chiếu.'
  if (
    new Set(points.map((point) => `${point.x},${point.y}`)).size !==
    points.length
  )
    return 'Các đỉnh không được trùng nhau.'
  for (let first = 0; first < points.length; first++) {
    for (let second = first + 1; second < points.length; second++) {
      if (second === first + 1 || (first === 0 && second === points.length - 1))
        continue
      if (
        intersects(
          points[first],
          points[(first + 1) % points.length],
          points[second],
          points[(second + 1) % points.length],
        )
      )
        return 'Các cạnh đa giác cắt nhau.'
    }
  }
  const doubleArea = Math.abs(
    points.reduce((area, point, index) => {
      const next = points[(index + 1) % points.length]
      return area + point.x * next.y - next.x * point.y
    }, 0),
  )
  if ((doubleArea * image.width * image.height) / 2 < 4)
    return 'Đa giác quá nhỏ (dưới 4 pixel vuông).'
  return null
}
