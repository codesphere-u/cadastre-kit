"""ISO 19152 LADM parcel topology, overlap/sliver engine, and witness attestation ledger."""

from .attestation import BoundaryAttestation, WitnessAttestationLedger, WitnessRecord
from .geometry import (
    Point2D,
    has_self_intersection,
    polygon_area,
    polygon_intersection_area,
    polygon_perimeter,
    project_wgs84_to_local_m,
    triangulate_polygon,
)
from .ladm import (
    ConflictFinding,
    Parcel,
    Party,
    RrrEntry,
    RrrType,
    SubdivisionAudit,
    TenureType,
    audit_cadastre_topology,
    audit_subdivision,
)

__all__ = [
    "BoundaryAttestation",
    "ConflictFinding",
    "Parcel",
    "Party",
    "Point2D",
    "RrrEntry",
    "RrrType",
    "SubdivisionAudit",
    "TenureType",
    "WitnessAttestationLedger",
    "WitnessRecord",
    "audit_cadastre_topology",
    "audit_subdivision",
    "has_self_intersection",
    "polygon_area",
    "polygon_intersection_area",
    "polygon_perimeter",
    "project_wgs84_to_local_m",
    "triangulate_polygon",
]
__version__ = "0.1.0"
