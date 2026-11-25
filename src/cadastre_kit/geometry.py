"""Zero-dependency 2D & WGS84 computational geometry for parcel topology validation.

Includes WGS84 local tangent-plane projection, exact self-intersection detection,
ear-clipping triangulation for arbitrary simple concave/convex polygons, and
exact Sutherland-Hodgman triangle-triangle overlap area calculation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

Point2D = tuple[float, float]

_WGS84_A = 6378137.0
_WGS84_F = 1.0 / 298.257223563
_WGS84_E2 = _WGS84_F * (2.0 - _WGS84_F)


def _strip_closing_vertex(ring: Sequence[Point2D]) -> list[Point2D]:
    pts = list(ring)
    if len(pts) >= 2 and math.isclose(pts[0][0], pts[-1][0], abs_tol=1e-11) and math.isclose(
        pts[0][1], pts[-1][1], abs_tol=1e-11
    ):
        pts.pop()
    return pts


def project_wgs84_to_local_m(
    ring_lon_lat: Sequence[Point2D],
    *,
    origin_lon_lat: Point2D | None = None,
) -> list[Point2D]:
    """Project WGS84 (lon, lat) degrees onto a local metric tangent plane (easting_m, northing_m)."""
    pts = _strip_closing_vertex(ring_lon_lat)
    if not pts:
        return []
    if origin_lon_lat is None:
        lon0 = sum(p[0] for p in pts) / len(pts)
        lat0 = sum(p[1] for p in pts) / len(pts)
    else:
        lon0, lat0 = origin_lon_lat

    lat_rad = math.radians(lat0)
    sin_lat = math.sin(lat_rad)
    cos_lat = math.cos(lat_rad)
    denom = math.sqrt(1.0 - _WGS84_E2 * sin_lat * sin_lat)
    r_n = _WGS84_A / denom
    r_m = _WGS84_A * (1.0 - _WGS84_E2) / (denom**3)

    m_per_deg_lat = math.radians(1.0) * r_m
    m_per_deg_lon = math.radians(1.0) * r_n * cos_lat
    return [((lon - lon0) * m_per_deg_lon, (lat - lat0) * m_per_deg_lat) for lon, lat in pts]


def signed_polygon_area(ring: Sequence[Point2D]) -> float:
    """Shoelace signed area (positive for counter-clockwise winding)."""
    pts = _strip_closing_vertex(ring)
    n = len(pts)
    if n < 3:
        return 0.0
    acc = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        acc += x1 * y2 - x2 * y1
    return 0.5 * acc


def polygon_area(ring: Sequence[Point2D]) -> float:
    """Unsigned area of a simple 2D polygon."""
    return abs(signed_polygon_area(ring))


def polygon_perimeter(ring: Sequence[Point2D]) -> float:
    """Perimeter length of a closed 2D polygon."""
    pts = _strip_closing_vertex(ring)
    n = len(pts)
    if n < 2:
        return 0.0
    total = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        total += math.hypot(x2 - x1, y2 - y1)
    return total


def _cross(o: Point2D, a: Point2D, b: Point2D) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _on_segment(a: Point2D, b: Point2D, p: Point2D, eps: float = 1e-9) -> bool:
    return (
        min(a[0], b[0]) - eps <= p[0] <= max(a[0], b[0]) + eps
        and min(a[1], b[1]) - eps <= p[1] <= max(a[1], b[1]) + eps
    )


def _segments_intersect(p1: Point2D, p2: Point2D, q1: Point2D, q2: Point2D, eps: float = 1e-9) -> bool:
    d1 = _cross(q1, q2, p1)
    d2 = _cross(q1, q2, p2)
    d3 = _cross(p1, p2, q1)
    d4 = _cross(p1, p2, q2)

    if ((d1 > eps and d2 < -eps) or (d1 < -eps and d2 > eps)) and (
        (d3 > eps and d4 < -eps) or (d3 < -eps and d4 > eps)
    ):
        return True
    if abs(d1) <= eps and _on_segment(q1, q2, p1, eps):
        return True
    if abs(d2) <= eps and _on_segment(q1, q2, p2, eps):
        return True
    if abs(d3) <= eps and _on_segment(p1, p2, q1, eps):
        return True
    return abs(d4) <= eps and _on_segment(p1, p2, q2, eps)


def has_self_intersection(ring: Sequence[Point2D]) -> bool:
    """Return True if any two non-adjacent edges of the polygon intersect (bow-tie / figure-8)."""
    pts = _strip_closing_vertex(ring)
    n = len(pts)
    if n < 4:
        return False
    for i in range(n):
        a1 = pts[i]
        a2 = pts[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            b1 = pts[j]
            b2 = pts[(j + 1) % n]
            if _segments_intersect(a1, a2, b1, b2):
                return True
    return False


def _ensure_ccw(ring: Sequence[Point2D]) -> list[Point2D]:
    pts = _strip_closing_vertex(ring)
    if signed_polygon_area(pts) < 0.0:
        pts.reverse()
    return pts


def _point_in_triangle(p: Point2D, a: Point2D, b: Point2D, c: Point2D, eps: float = 1e-9) -> bool:
    c1 = _cross(a, b, p)
    c2 = _cross(b, c, p)
    c3 = _cross(c, a, p)
    return c1 >= -eps and c2 >= -eps and c3 >= -eps


def triangulate_polygon(ring: Sequence[Point2D]) -> list[tuple[Point2D, Point2D, Point2D]]:
    """Triangulate any simple (convex or concave) polygon via ear clipping."""
    pts = _ensure_ccw(ring)
    if len(pts) < 3:
        return []
    if has_self_intersection(pts):
        raise ValueError("Cannot triangulate a self-intersecting polygon")

    remaining = list(pts)
    triangles: list[tuple[Point2D, Point2D, Point2D]] = []
    guard = 0
    max_iters = len(remaining) * len(remaining) + 10

    while len(remaining) > 3 and guard < max_iters:
        guard += 1
        n = len(remaining)
        ear_found = False
        for i in range(n):
            prev_p = remaining[(i - 1) % n]
            curr_p = remaining[i]
            next_p = remaining[(i + 1) % n]
            area2 = _cross(prev_p, curr_p, next_p)
            if area2 <= 1e-12:
                # Reflex or collinear vertex
                continue
            contains_other = False
            for j in range(n):
                if j in ((i - 1) % n, i, (i + 1) % n):
                    continue
                if _point_in_triangle(remaining[j], prev_p, curr_p, next_p):
                    contains_other = True
                    break
            if not contains_other:
                triangles.append((prev_p, curr_p, next_p))
                remaining.pop(i)
                ear_found = True
                break
        if not ear_found:
            # Remove collinear vertex if present to keep progress
            removed = False
            for i in range(len(remaining)):
                p0 = remaining[(i - 1) % len(remaining)]
                p1 = remaining[i]
                p2 = remaining[(i + 1) % len(remaining)]
                if abs(_cross(p0, p1, p2)) <= 1e-10:
                    remaining.pop(i)
                    removed = True
                    break
            if not removed:
                break

    if len(remaining) == 3 and _cross(remaining[0], remaining[1], remaining[2]) > 1e-12:
        triangles.append((remaining[0], remaining[1], remaining[2]))
    return triangles


def _clip_polygon_against_edge(
    subject: list[Point2D],
    edge_start: Point2D,
    edge_end: Point2D,
) -> list[Point2D]:
    """Sutherland-Hodgman half-plane clipping against a directed CCW edge."""
    if not subject:
        return []
    output: list[Point2D] = []
    n = len(subject)
    for i in range(n):
        curr = subject[i]
        prev = subject[(i - 1) % n]
        curr_in = _cross(edge_start, edge_end, curr) >= -1e-11
        prev_in = _cross(edge_start, edge_end, prev) >= -1e-11
        if curr_in:
            if not prev_in:
                inter = _line_intersection(prev, curr, edge_start, edge_end)
                if inter is not None:
                    output.append(inter)
            output.append(curr)
        elif prev_in:
            inter = _line_intersection(prev, curr, edge_start, edge_end)
            if inter is not None:
                output.append(inter)
    return output


def _line_intersection(p1: Point2D, p2: Point2D, p3: Point2D, p4: Point2D) -> Point2D | None:
    x1, y1 = p1
    x2, y2 = p2
    x3, y3 = p3
    x4, y4 = p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-15:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))


def _triangle_intersection_area(
    tri_a: tuple[Point2D, Point2D, Point2D],
    tri_b: tuple[Point2D, Point2D, Point2D],
) -> float:
    poly: list[Point2D] = list(tri_a)
    for i in range(3):
        poly = _clip_polygon_against_edge(poly, tri_b[i], tri_b[(i + 1) % 3])
        if len(poly) < 3:
            return 0.0
    return polygon_area(poly)


def _bbox(ring: Sequence[Point2D]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def polygon_intersection_area(ring_a: Sequence[Point2D], ring_b: Sequence[Point2D]) -> float:
    """Compute exact intersection area between any two simple (convex or concave) 2D polygons."""
    pts_a = _ensure_ccw(ring_a)
    pts_b = _ensure_ccw(ring_b)
    if len(pts_a) < 3 or len(pts_b) < 3:
        return 0.0
    ax0, ay0, ax1, ay1 = _bbox(pts_a)
    bx0, by0, bx1, by1 = _bbox(pts_b)
    if ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0:
        return 0.0

    tris_a = triangulate_polygon(pts_a)
    tris_b = triangulate_polygon(pts_b)
    total = 0.0
    for ta in tris_a:
        for tb in tris_b:
            total += _triangle_intersection_area(ta, tb)
    return total
