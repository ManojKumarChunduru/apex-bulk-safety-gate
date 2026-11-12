"""The limit policy and the breach-size arithmetic.

This file exists so that every number the gate compares against is written down once, with the
documented value, the context it applies to and the reason it is in the policy, and so that a
team can override a value (a sandbox with raised limits, a stricter internal budget) without
touching code. `absg limits` prints this table. The arithmetic is deliberately small: a trigger's
cost at R records is the sum over chunks of 200 of its per-invocation polynomial, and the breach
size is the smallest R at which that sum exceeds the limit (ADR-003).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from absg.provenance import Poly


@dataclass(frozen=True)
class Limit:
    name: str
    sync: int
    async_: int
    unit: str
    reason: str


DEFAULT_LIMITS: tuple[Limit, ...] = (
    Limit(
        "soql_queries",
        100,
        200,
        "queries",
        "Total number of SOQL queries issued per transaction. The commonest breach: one query "
        "per record reaches it at the 101st record.",
    ),
    Limit(
        "sosl_queries",
        20,
        20,
        "searches",
        "Total number of SOSL queries issued per transaction. Five times tighter than SOQL, "
        "so a search per record breaches at the 21st record.",
    ),
    Limit(
        "dml_statements",
        150,
        150,
        "statements",
        "Total number of DML statements issued per transaction. One statement per record "
        "breaches at the 151st record even when each statement carries one row.",
    ),
    Limit(
        "dml_rows",
        10000,
        10000,
        "rows",
        "Total number of records processed as a result of DML statements per transaction. "
        "A correctly bulkified trigger that inserts one child per record still has a breach "
        "size here: the 10,001st record.",
    ),
)


@dataclass
class Policy:
    """Limit values plus the two record counts the arithmetic depends on."""

    limits: dict[str, Limit] = field(
        default_factory=lambda: {limit.name: limit for limit in DEFAULT_LIMITS}
    )
    context: str = "sync"
    chunk_size: int = 200
    horizon: int = 10000
    records: int = 200

    CHUNK_REASON = (
        "Apex trigger batch size: a DML of more than 200 records invokes a trigger once per "
        "chunk of 200. The gate assumes those chunks share one transaction's limits, which the "
        "documentation states only as 'limits are per transaction'; ADR-005 lists it as declared."
    )
    HORIZON_REASON = (
        "Verdict horizon: breach sizes are reported up to one Bulk API batch of 10,000 records. "
        "A breach above the horizon is reported as 'none within the horizon', not as clean."
    )
    RECORDS_REASON = (
        "The record count the verdict is taken at. 200 is the trigger batch size and the "
        "count a bulk test is conventionally written for; raise it to a Bulk API batch to see "
        "the chunk arithmetic."
    )

    def value(self, name: str) -> int:
        limit = self.limits[name]
        return limit.sync if self.context == "sync" else limit.async_

    def apply_overrides(self, overrides: dict) -> None:
        """Apply a policy file: {"limits": {"soql_queries": {"sync": 90}}, "chunk_size": 200}."""
        if not isinstance(overrides, dict):
            raise PolicyError("policy file must be a JSON object")
        for key in overrides:
            if key not in {"limits", "chunk_size", "horizon", "records", "context"}:
                raise PolicyError(f"unknown policy key {key!r}")
        for name, values in overrides.get("limits", {}).items():
            if name not in self.limits:
                raise PolicyError(
                    f"unknown limit {name!r}; known limits: {', '.join(sorted(self.limits))}"
                )
            if not isinstance(values, dict):
                raise PolicyError(f"limit {name!r} must map to an object with sync and/or async")
            current = self.limits[name]
            sync = values.get("sync", current.sync)
            async_ = values.get("async", current.async_)
            for label, value in (("sync", sync), ("async", async_)):
                if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                    raise PolicyError(f"limit {name!r} {label} value must be a positive integer")
            self.limits[name] = Limit(name, sync, async_, current.unit, current.reason)
        for key in ("chunk_size", "horizon", "records"):
            if key in overrides:
                value = overrides[key]
                if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                    raise PolicyError(f"{key} must be a positive integer")
                setattr(self, key, value)
        if "context" in overrides:
            if overrides["context"] not in {"sync", "async"}:
                raise PolicyError("context must be 'sync' or 'async'")
            self.context = overrides["context"]

    def describe(self) -> list[dict]:
        rows = [
            {
                "name": limit.name,
                "value": self.value(limit.name),
                "sync": limit.sync,
                "async": limit.async_,
                "unit": limit.unit,
                "reason": limit.reason,
            }
            for limit in self.limits.values()
        ]
        rows.append(
            {
                "name": "chunk_size",
                "value": self.chunk_size,
                "unit": "records",
                "reason": self.CHUNK_REASON,
            }
        )
        rows.append(
            {
                "name": "horizon",
                "value": self.horizon,
                "unit": "records",
                "reason": self.HORIZON_REASON,
            }
        )
        rows.append(
            {
                "name": "records",
                "value": self.records,
                "unit": "records",
                "reason": self.RECORDS_REASON,
            }
        )
        return rows


class PolicyError(ValueError):
    pass


def load_policy(path: str | Path | None, context: str, records: int | None) -> Policy:
    policy = Policy()
    if path is not None:
        try:
            overrides = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PolicyError(f"cannot read policy file {path}: {exc}") from exc
        policy.apply_overrides(overrides)
    if context not in {"sync", "async"}:
        raise PolicyError("context must be 'sync' or 'async'")
    policy.context = context
    if records is not None:
        if records <= 0:
            raise PolicyError("records must be a positive integer")
        policy.records = records
    return policy


def cost_at(poly: Poly, records: int, chunk_size: int) -> int:
    """Total cost of a trigger whose per-invocation cost is poly, for one DML of `records`.

    Records arrive in chunks of chunk_size; each chunk is one invocation with its own r, and the
    chunks share the transaction's limits, so the costs add.
    """
    if records <= 0:
        return 0
    full, last = divmod(records, chunk_size)
    total = full * poly.evaluate(chunk_size)
    if last:
        total += poly.evaluate(last)
    return total


def breach_size(poly: Poly, limit: int, chunk_size: int, horizon: int) -> int | None:
    """The smallest record count at which cost_at(poly, R) exceeds the limit, or None if no
    count up to the horizon does. Scans R upward: the horizon is small and the scan is exact,
    which matters more than a closed form that has to special-case the chunk boundary.
    """
    if poly.is_zero:
        return None
    for records in range(1, horizon + 1):
        if cost_at(poly, records, chunk_size) > limit:
            return records
    return None
