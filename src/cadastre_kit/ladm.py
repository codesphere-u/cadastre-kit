"""ISO 19152 LADM parcel model, topology conflict auditor, and subdivision verifier."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .geometry import (
    Point2D,
    has_self_intersection,
    polygon_area,
    polygon_intersection_area,
    polygon_perimeter,
    project_wgs84_to_local_m,
)


class TenureType(StrEnum):
    CUSTOMARY = "customary"
    FREEHOLD = "freehold"
    LEASEHOLD = "leasehold"
    MAILO = "mailo"
    COMMUNAL = "communal"
    PUBLIC = "public"


class RrrType(StrEnum):
    OWNERSHIP = "ownership"
    OCCUPANCY = "occupancy"
    RIGHT_OF_WAY = "right_of_way"
    SPOUSAL_CONSENT_RESTRICTION = "spousal_consent_restriction"
    MORTGAGE = "mortgage"
    WETLAND_BUFFER_RESTRICTION = "wetland_buffer_restriction"


@dataclass(frozen=True)
class Party:
    """ISO 19152 LA_Party (individual, spouse, family, clan, or cooperative)."""

    party_id: str
    full_name: str
    role: str = "natural_person"


@dataclass(frozen=True)
class RrrEntry:
    """ISO 19152 LA_RRR (Right, Restriction, or Responsibility) attached to a parcel."""

    party_id: str
    rrr_type: RrrType
    share_fraction: float = 1.0
    notes: str = ""

    def __post_init__(self) -> None:
        if not (0.0 < self.share_fraction <= 1.0 + 1e-6):
            raise ValueError(f"share_fraction must be in (0, 1], got {self.share_fraction}")


@dataclass(frozen=True)
class Parcel:
    """ISO 19152 LA_SpatialUnit parcel with either metric or WGS84 coordinates."""

    parcel_id: str
    tenure: TenureType
    ring: tuple[Point2D, ...]
    crs: str = "local_m"  # "local_m" or "wgs84"
    rrrs: tuple[RrrEntry, ...] = ()
    parent_parcel_id: str | None = None


@dataclass(frozen=True)
class ConflictFinding:
    """Topology, geometry, or RRR integrity finding across parcels."""

    code: str
    severity: str  # "error" or "warning"
    parcel_ids: tuple[str, ...]
    overlap_area_m2: float
    message: str


def _parcel_rings_metric(parcels: Sequence[Parcel]) -> dict[str, list[Point2D]]:
    if not parcels:
        return {}
    crs_set = {p.crs for p in parcels}
    if len(crs_set) > 1:
        raise ValueError(f"Mixed CRS in cadastre audit: {sorted(crs_set)}")
    crs = next(iter(crs_set))
    if crs == "local_m":
        return {p.parcel_id: list(p.ring) for p in parcels}
    if crs == "wgs84":
        all_pts = [pt for p in parcels for pt in p.ring]
        origin = (
            sum(pt[0] for pt in all_pts) / len(all_pts),
            sum(pt[1] for pt in all_pts) / len(all_pts),
        )
        return {p.parcel_id: project_wgs84_to_local_m(p.ring, origin_lon_lat=origin) for p in parcels}
    raise ValueError(f"Unsupported CRS '{crs}'; expected 'local_m' or 'wgs84'")


def audit_cadastre_topology(
    parcels: Sequence[Parcel],
    *,
    sliver_threshold_m2: float = 5.0,
    min_parcel_area_m2: float = 25.0,
) -> list[ConflictFinding]:
    """Audit parcels for self-intersections, degenerate area, RRR share sums, and overlaps."""
    findings: list[ConflictFinding] = []
    metric = _parcel_rings_metric(parcels)
    valid_ids: list[str] = []

    for parcel in parcels:
        ring = metric[parcel.parcel_id]
        if len(ring) < 3:
            findings.append(
                ConflictFinding(
                    code="DEGENERATE_POLYGON",
                    severity="error",
                    parcel_ids=(parcel.parcel_id,),
                    overlap_area_m2=0.0,
                    message=f"Parcel {parcel.parcel_id} has fewer than 3 vertices.",
                )
            )
            continue

        if has_self_intersection(ring):
            findings.append(
                ConflictFinding(
                    code="SELF_INTERSECTION",
                    severity="error",
                    parcel_ids=(parcel.parcel_id,),
                    overlap_area_m2=0.0,
                    message=f"Parcel {parcel.parcel_id} has a self-intersecting (bow-tie) boundary.",
                )
            )
            continue

        area = polygon_area(ring)
        if area < min_parcel_area_m2:
            findings.append(
                ConflictFinding(
                    code="UNDERSIZED_PARCEL",
                    severity="warning",
                    parcel_ids=(parcel.parcel_id,),
                    overlap_area_m2=round(area, 2),
                    message=(
                        f"Parcel {parcel.parcel_id} area {area:.2f} m2 is below minimum {min_parcel_area_m2:.1f} m2."
                    ),
                )
            )

        # Ownership share sum check (ISO 19152 LA_Right conservation)
        ownership_shares = [r.share_fraction for r in parcel.rrrs if r.rrr_type == RrrType.OWNERSHIP]
        if ownership_shares and abs(sum(ownership_shares) - 1.0) > 1e-4:
            findings.append(
                ConflictFinding(
                    code="OWNERSHIP_SHARE_MISMATCH",
                    severity="error",
                    parcel_ids=(parcel.parcel_id,),
                    overlap_area_m2=0.0,
                    message=(
                        f"Parcel {parcel.parcel_id} ownership shares sum to {sum(ownership_shares):.4f} "
                        "(expected 1.0000)."
                    ),
                )
            )
        valid_ids.append(parcel.parcel_id)

    # Pairwise overlap & sliver checks
    for i in range(len(valid_ids)):
        id_a = valid_ids[i]
        ring_a = metric[id_a]
        for j in range(i + 1, len(valid_ids)):
            id_b = valid_ids[j]
            ring_b = metric[id_b]
            overlap = polygon_intersection_area(ring_a, ring_b)
            if overlap <= 1e-4:
                continue
            if overlap <= sliver_threshold_m2:
                findings.append(
                    ConflictFinding(
                        code="GPS_SLIVER_OVERLAP",
                        severity="warning",
                        parcel_ids=(id_a, id_b),
                        overlap_area_m2=round(overlap, 3),
                        message=(
                            f"Micro-sliver overlap of {overlap:.2f} m2 between {id_a} and {id_b} (likely GPS drift)."
                        ),
                    )
                )
            else:
                findings.append(
                    ConflictFinding(
                        code="BOUNDARY_ENCROACHMENT",
                        severity="error",
                        parcel_ids=(id_a, id_b),
                        overlap_area_m2=round(overlap, 3),
                        message=f"Material boundary encroachment of {overlap:.2f} m2 between {id_a} and {id_b}.",
                    )
                )

    return findings


@dataclass(frozen=True)
class SubdivisionAudit:
    """Area-conservation and containment verification for a parcel subdivision."""

    parent_parcel_id: str
    parent_area_m2: float
    parent_perimeter_m: float
    children_total_area_m2: float
    area_discrepancy_m2: float
    area_discrepancy_pct: float
    child_overlap_area_m2: float
    outside_parent_area_m2: float
    valid: bool
    issues: tuple[str, ...]


def audit_subdivision(
    parent: Parcel,
    children: Sequence[Parcel],
    *,
    area_tolerance_pct: float = 1.0,
) -> SubdivisionAudit:
    """Verify a parcel subdivision conserves area, stays inside parent, and has no child overlaps."""
    if not children:
        raise ValueError("Subdivision must contain at least one child parcel")

    metric = _parcel_rings_metric([parent, *children])
    parent_ring = metric[parent.parcel_id]
    parent_area = polygon_area(parent_ring)
    parent_perim = polygon_perimeter(parent_ring)

    issues: list[str] = []
    if has_self_intersection(parent_ring) or parent_area <= 0.0:
        issues.append(f"Parent parcel {parent.parcel_id} geometry is invalid.")

    child_areas = 0.0
    outside_total = 0.0
    for child in children:
        c_ring = metric[child.parcel_id]
        if has_self_intersection(c_ring):
            issues.append(f"Child parcel {child.parcel_id} self-intersects.")
            continue
        c_area = polygon_area(c_ring)
        child_areas += c_area
        inside = polygon_intersection_area(c_ring, parent_ring)
        outside = max(0.0, c_area - inside)
        outside_total += outside
        if outside > max(1.0, parent_area * (area_tolerance_pct / 100.0)):
            issues.append(
                f"Child parcel {child.parcel_id} extends {outside:.2f} m2 outside parent {parent.parcel_id}."
            )

    overlap_total = 0.0
    for i in range(len(children)):
        for j in range(i + 1, len(children)):
            ov = polygon_intersection_area(metric[children[i].parcel_id], metric[children[j].parcel_id])
            if ov > 1e-2:
                overlap_total += ov
                issues.append(
                    f"Child parcels {children[i].parcel_id} and {children[j].parcel_id} overlap by {ov:.2f} m2."
                )

    discrepancy_m2 = child_areas - parent_area
    discrepancy_pct = (abs(discrepancy_m2) / parent_area * 100.0) if parent_area > 0 else 100.0
    if discrepancy_pct > area_tolerance_pct:
        issues.append(
            f"Area conservation violated: children sum to {child_areas:.2f} m2 vs parent {parent_area:.2f} m2 "
            f"({discrepancy_pct:.2f}% discrepancy > {area_tolerance_pct:.2f}%)."
        )

    return SubdivisionAudit(
        parent_parcel_id=parent.parcel_id,
        parent_area_m2=round(parent_area, 3),
        parent_perimeter_m=round(parent_perim, 3),
        children_total_area_m2=round(child_areas, 3),
        area_discrepancy_m2=round(discrepancy_m2, 3),
        area_discrepancy_pct=round(discrepancy_pct, 3),
        child_overlap_area_m2=round(overlap_total, 3),
        outside_parent_area_m2=round(outside_total, 3),
        valid=len(issues) == 0,
        issues=tuple(issues),
    )
