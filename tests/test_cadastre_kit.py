"""Tests for cadastre-kit."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from cadastre_kit import (
    Parcel,
    RrrEntry,
    RrrType,
    TenureType,
    WitnessAttestationLedger,
    WitnessRecord,
    audit_cadastre_topology,
    audit_subdivision,
    has_self_intersection,
    polygon_area,
    polygon_intersection_area,
    project_wgs84_to_local_m,
)
from cadastre_kit.cli import main as cli_main


def test_concave_l_shape_exact_area_and_overlap() -> None:
    # L-shaped parcel: 100x100 minus top-right 50x50 => area = 7500 m2
    l_shape = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0), (50.0, 50.0), (50.0, 100.0), (0.0, 100.0)]
    assert polygon_area(l_shape) == pytest.approx(7500.0)
    assert has_self_intersection(l_shape) is False

    # Square inside the empty notch (50..100, 50..100) should have 0 overlap!
    notch_square = [(50.0, 50.0), (100.0, 50.0), (100.0, 100.0), (50.0, 100.0)]
    assert polygon_intersection_area(l_shape, notch_square) == pytest.approx(0.0, abs=1e-6)

    # Overlapping parcel encroaching 10m into L-shape (40..60, 40..60): 3/4 of 20x20 = 300 m2
    encroacher = [(40.0, 40.0), (60.0, 40.0), (60.0, 60.0), (40.0, 60.0)]
    assert polygon_intersection_area(l_shape, encroacher) == pytest.approx(300.0, abs=1e-4)


def test_self_intersection_and_sliver_vs_encroachment() -> None:
    bowtie = Parcel(
        parcel_id="P-BOW",
        tenure=TenureType.CUSTOMARY,
        ring=((0.0, 0.0), (100.0, 100.0), (100.0, 0.0), (0.0, 100.0)),
    )
    p1 = Parcel(
        parcel_id="P-1",
        tenure=TenureType.FREEHOLD,
        ring=((0.0, 0.0), (50.0, 0.0), (50.0, 40.0), (0.0, 40.0)),
        rrrs=(RrrEntry("U1", RrrType.OWNERSHIP, 0.6), RrrEntry("U2", RrrType.OWNERSHIP, 0.4)),
    )
    # 0.05m overlap along 40m edge => 2.0 m2 GPS sliver (< 5 m2)
    p2_sliver = Parcel(
        parcel_id="P-2",
        tenure=TenureType.FREEHOLD,
        ring=((49.95, 0.0), (100.0, 0.0), (100.0, 40.0), (49.95, 40.0)),
    )
    # 5m encroachment along 40m edge => 200 m2 error
    p3_encroach = Parcel(
        parcel_id="P-3",
        tenure=TenureType.CUSTOMARY,
        ring=((0.0, 35.0), (50.0, 35.0), (50.0, 80.0), (0.0, 80.0)),
        rrrs=(RrrEntry("U3", RrrType.OWNERSHIP, 0.5),),  # Invalid sum != 1.0
    )

    findings = audit_cadastre_topology([bowtie, p1, p2_sliver, p3_encroach], sliver_threshold_m2=5.0)
    codes = {f.code for f in findings}
    assert "SELF_INTERSECTION" in codes
    assert "GPS_SLIVER_OVERLAP" in codes
    assert "BOUNDARY_ENCROACHMENT" in codes
    assert "OWNERSHIP_SHARE_MISMATCH" in codes


def test_wgs84_projection_near_equator_area_accuracy() -> None:
    # ~0.001 deg x 0.001 deg square near Kampala (0.3136N, 32.5811E) ~ 111.3m x 110.6m ~ 12,310 m2
    ring = ((32.5810, 0.3130), (32.5820, 0.3130), (32.5820, 0.3140), (32.5810, 0.3140))
    local = project_wgs84_to_local_m(ring)
    area = polygon_area(local)
    assert 12200.0 < area < 12450.0


def test_subdivision_conservation_valid_and_inflated() -> None:
    parent = Parcel("PAR-10", TenureType.MAILO, ((0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)))
    c1 = Parcel("PAR-10A", TenureType.MAILO, ((0.0, 0.0), (50.0, 0.0), (50.0, 100.0), (0.0, 100.0)))
    c2 = Parcel("PAR-10B", TenureType.MAILO, ((50.0, 0.0), (100.0, 0.0), (100.0, 100.0), (50.0, 100.0)))
    ok = audit_subdivision(parent, [c1, c2])
    assert ok.valid is True
    assert ok.area_discrepancy_m2 == pytest.approx(0.0)

    # Child 2 fraudulently extends 10m outside parent
    c2_bad = Parcel("PAR-10B", TenureType.MAILO, ((50.0, 0.0), (110.0, 0.0), (110.0, 100.0), (50.0, 100.0)))
    bad = audit_subdivision(parent, [c1, c2_bad])
    assert bad.valid is False
    assert bad.outside_parent_area_m2 == pytest.approx(1000.0)


def test_witness_attestation_ledger_tamper_detection() -> None:
    parcel = Parcel("UG-KLA-001", TenureType.CUSTOMARY, ((0.0, 0.0), (60.0, 0.0), (60.0, 50.0), (0.0, 50.0)))
    ledger = WitnessAttestationLedger()
    w1 = WitnessRecord("W1", "Nakato Grace", "adjacent_north", "UG-KLA-002")
    w2 = WitnessRecord("W2", "Okello Samuel", "local_council_chair")
    e1 = ledger.record(parcel, "INITIAL_DEMARCATION", [w1, w2], recorded_at_utc="2026-11-25T10:00:00Z")
    e2 = ledger.record(parcel, "BOUNDARY_CONFIRMED", [w1, w2], recorded_at_utc="2026-11-25T11:00:00Z")
    assert ledger.verify_chain() is True
    assert e2.prev_hash == e1.entry_hash

    tampered = WitnessAttestationLedger([replace(e1, parcel_id="FORGED"), e2])
    assert tampered.verify_chain() is False


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clean_file = tmp_path / "clean.json"
    clean_file.write_text(
        json.dumps(
            {
                "parcels": [
                    {"parcel_id": "A", "ring": [[0, 0], [50, 0], [50, 50], [0, 50]]},
                    {"parcel_id": "B", "ring": [[50, 0], [100, 0], [100, 50], [50, 50]]},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert cli_main([str(clean_file)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["findings"] == []
