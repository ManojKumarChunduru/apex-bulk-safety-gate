"""apex-bulk-safety-gate: the record count at which a trigger breaches a governor limit.

A line coverage percentage is a property of lines; a governor limit is a property of counts.
This package computes, from the Apex source alone, how many records it takes to breach each
limit, and places that number next to the largest record count any test actually exercised.
"""

__version__ = "0.1.0"
