"""Where a loop's elements come from decides whether a query inside it costs 1 or costs r.

This file exists because the question "is there a SOQL inside a loop" is the wrong question. A
loop over three picklist values costs three queries per transaction no matter how many records
arrive; a loop over Trigger.new costs one query per record. The reader therefore tracks, for
every collection it meets, whether its size is bounded by the trigger's record count, bounded by
a constant, or not bounded by anything in the source. Costs are polynomials in r, the record
count of one trigger invocation, so a nested per-record loop is r squared rather than "a loop".
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class Poly:
    """A polynomial in r with non-negative integer coefficients, keyed by degree."""

    coeffs: tuple[tuple[int, int], ...] = ()

    @staticmethod
    def of(**by_degree: int) -> Poly:
        return Poly.from_dict({int(k[1:]): v for k, v in by_degree.items()})

    @staticmethod
    def from_dict(d: dict[int, int]) -> Poly:
        return Poly(tuple(sorted((k, v) for k, v in d.items() if v)))

    @staticmethod
    def const(k: int) -> Poly:
        return Poly.from_dict({0: k})

    @staticmethod
    def record() -> Poly:
        return Poly.from_dict({1: 1})

    def as_dict(self) -> dict[int, int]:
        return dict(self.coeffs)

    def __add__(self, other: Poly) -> Poly:
        d = self.as_dict()
        for k, v in other.coeffs:
            d[k] = d.get(k, 0) + v
        return Poly.from_dict(d)

    def __mul__(self, other: Poly) -> Poly:
        d: dict[int, int] = {}
        for k1, v1 in self.coeffs:
            for k2, v2 in other.coeffs:
                d[k1 + k2] = d.get(k1 + k2, 0) + v1 * v2
        return Poly.from_dict(d)

    def compose(self, inner: Poly) -> Poly:
        """self(inner): substitute another polynomial for r."""
        result = Poly()
        for k, v in self.coeffs:
            term = Poly.const(v)
            for _ in range(k):
                term = term * inner
            result = result + term
        return result

    def evaluate(self, r: int) -> int:
        return sum(v * r**k for k, v in self.coeffs)

    def coefficient(self, degree: int) -> int:
        return self.as_dict().get(degree, 0)

    @property
    def is_zero(self) -> bool:
        return not self.coeffs

    @property
    def degree(self) -> int:
        return max((k for k, _ in self.coeffs), default=0)

    def describe(self) -> str:
        """Human form such as `1 + 2r` or `r^2`, used by `absg explain` and the report."""
        if self.is_zero:
            return "0"
        parts = []
        for k, v in self.coeffs:
            if k == 0:
                parts.append(str(v))
            elif k == 1:
                parts.append(f"{v}r" if v != 1 else "r")
            else:
                parts.append(f"{v}r^{k}" if v != 1 else f"r^{k}")
        return " + ".join(parts)


@dataclass(frozen=True)
class Provenance:
    """How large a collection (or loop) is, in terms of the record count r.

    kind is one of:
      record     size is bounded by r (Trigger.new, a filtered copy of it, a set of its ids)
      const      size is a constant known from the source (a literal list, a loop to 3)
      element    a single item, not a collection (a loop variable, one record)
      unbounded  size depends on data or on code the reader cannot see (a query result,
                 a method return value, a variable it never saw assigned)
    size is the Poly for record and const kinds; None otherwise.
    """

    kind: str
    size: Poly | None = None
    note: str = ""

    @staticmethod
    def record(note: str = "") -> Provenance:
        return Provenance("record", Poly.record(), note)

    @staticmethod
    def const(k: int, note: str = "") -> Provenance:
        return Provenance("const", Poly.const(k), note)

    @staticmethod
    def element(note: str = "") -> Provenance:
        return Provenance("element", Poly.const(1), note)

    @staticmethod
    def unbounded(note: str) -> Provenance:
        return Provenance("unbounded", None, note)

    @property
    def is_bounded(self) -> bool:
        return self.size is not None

    def grow(self, by: Poly | None) -> Provenance:
        """Adding elements inside a loop grows a collection by the loop's multiplier."""
        if by is None:
            return Provenance.unbounded(self.note or "grown inside an unbounded loop")
        if not self.is_bounded:
            return self
        new_size = (self.size or Poly()) + by
        kind = "record" if new_size.degree >= 1 else "const"
        note = "grown inside a per-record loop" if by.degree >= 1 else "grown by a constant"
        return Provenance(kind, new_size, note)


def ratio(numerator: int, denominator: int) -> Fraction:
    return Fraction(numerator, denominator)
