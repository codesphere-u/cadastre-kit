"""Hash-chained neighbor-witness boundary attestation ledger for customary & titled land."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from .ladm import Parcel


@dataclass(frozen=True)
class WitnessRecord:
    """Neighbor, local council (LC1), or licensed surveyor witnessing a boundary."""

    witness_id: str
    full_name: str
    role: str  # e.g., "adjacent_north", "local_council_chair", "surveyor"
    adjacent_parcel_id: str | None = None


@dataclass(frozen=True)
class BoundaryAttestation:
    """Single immutable link in a hash-chained boundary attestation ledger."""

    sequence: int
    parcel_id: str
    event_type: str  # "INITIAL_DEMARCATION", "SUBDIVISION", "DISPUTE_RESOLUTION"
    recorded_at_utc: str
    geometry_sha256: str
    witnesses: tuple[WitnessRecord, ...]
    prev_hash: str
    entry_hash: str


def _sha256_canonical(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class WitnessAttestationLedger:
    """Append-only SHA-256 hash chain for offline boundary walk attestations."""

    GENESIS_HASH = "0" * 64

    def __init__(self, entries: Sequence[BoundaryAttestation] = ()) -> None:
        self._entries: list[BoundaryAttestation] = list(entries)

    @property
    def entries(self) -> tuple[BoundaryAttestation, ...]:
        return tuple(self._entries)

    def record(
        self,
        parcel: Parcel,
        event_type: str,
        witnesses: Sequence[WitnessRecord],
        *,
        min_witnesses: int = 2,
        recorded_at_utc: str | None = None,
    ) -> BoundaryAttestation:
        """Append a witnessed boundary attestation after verifying quorum."""
        if len(witnesses) < min_witnesses:
            raise ValueError(f"Quorum not met: received {len(witnesses)} witnesses, require >= {min_witnesses}")
        unique_ids = {w.witness_id for w in witnesses}
        if len(unique_ids) != len(witnesses):
            raise ValueError("Duplicate witness_id detected in boundary attestation")

        ts = recorded_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        geom_hash = _sha256_canonical({"crs": parcel.crs, "ring": [list(pt) for pt in parcel.ring]})
        prev_hash = self._entries[-1].entry_hash if self._entries else self.GENESIS_HASH
        seq = len(self._entries) + 1
        witness_tuple = tuple(witnesses)
        payload = {
            "sequence": seq,
            "parcel_id": parcel.parcel_id,
            "event_type": event_type,
            "recorded_at_utc": ts,
            "geometry_sha256": geom_hash,
            "witnesses": [asdict(w) for w in witness_tuple],
            "prev_hash": prev_hash,
        }
        entry_hash = _sha256_canonical(payload)
        entry = BoundaryAttestation(
            sequence=seq,
            parcel_id=parcel.parcel_id,
            event_type=event_type,
            recorded_at_utc=ts,
            geometry_sha256=geom_hash,
            witnesses=witness_tuple,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )
        self._entries.append(entry)
        return entry

    def verify_chain(self) -> bool:
        """Recompute and verify every hash link from genesis to head."""
        expected_prev = self.GENESIS_HASH
        for idx, entry in enumerate(self._entries, start=1):
            if entry.sequence != idx or entry.prev_hash != expected_prev:
                return False
            payload = {
                "sequence": entry.sequence,
                "parcel_id": entry.parcel_id,
                "event_type": entry.event_type,
                "recorded_at_utc": entry.recorded_at_utc,
                "geometry_sha256": entry.geometry_sha256,
                "witnesses": [asdict(w) for w in entry.witnesses],
                "prev_hash": entry.prev_hash,
            }
            if _sha256_canonical(payload) != entry.entry_hash:
                return False
            expected_prev = entry.entry_hash
        return True
