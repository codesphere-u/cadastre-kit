"""CLI entrypoint for cadastre-kit."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .ladm import Parcel, RrrEntry, RrrType, TenureType, audit_cadastre_topology


def _parse_parcel(raw: dict[str, Any]) -> Parcel:
    rrrs = tuple(
        RrrEntry(
            party_id=str(r["party_id"]),
            rrr_type=RrrType(str(r["rrr_type"])),
            share_fraction=float(r.get("share_fraction", 1.0)),
            notes=str(r.get("notes", "")),
        )
        for r in raw.get("rrrs", [])
    )
    ring = tuple((float(pt[0]), float(pt[1])) for pt in raw["ring"])
    return Parcel(
        parcel_id=str(raw["parcel_id"]),
        tenure=TenureType(str(raw.get("tenure", "customary"))),
        ring=ring,
        crs=str(raw.get("crs", "local_m")),
        rrrs=rrrs,
        parent_parcel_id=str(raw["parent_parcel_id"]) if raw.get("parent_parcel_id") else None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cadastre-kit",
        description="Audit ISO 19152 LADM parcel geometry, overlaps, slivers, and RRR ownership shares.",
    )
    parser.add_argument("parcels_json", type=Path, help="Path to JSON file containing a 'parcels' array.")
    parser.add_argument("--sliver-m2", type=float, default=5.0, help="Max area (m2) classified as GPS sliver.")
    args = parser.parse_args(argv)

    data = json.loads(args.parcels_json.read_text(encoding="utf-8"))
    parcels = [_parse_parcel(p) for p in data["parcels"]]
    findings = audit_cadastre_topology(parcels, sliver_threshold_m2=args.sliver_m2)
    print(json.dumps({"parcel_count": len(parcels), "findings": [asdict(f) for f in findings]}, indent=2))
    return 1 if any(f.severity == "error" for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
