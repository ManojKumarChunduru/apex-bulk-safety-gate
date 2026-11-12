"""Exit codes are the gate's interface to a pipeline, so each one means exactly one thing.

The distinction that matters is between "the gate did its job and the answer was no" (1) and
"the gate could not answer" (2). A pipeline that treats both as red teaches people to delete the
step; a pipeline that treats 2 as green asserts a cleanliness nobody measured.
"""

CLEAN = 0  # every trigger bounded, none breaches at the configured record count
BREACH = 1  # at least one trigger breaches a limit at the configured record count
UNDECIDABLE = 2  # no breach found, but at least one trigger could not be bounded
USAGE = 3  # bad arguments, unreadable project, invalid coverage report or policy

MEANING = {
    CLEAN: "clean: every trigger bounded and none breaches at the configured record count",
    BREACH: "breach: at least one trigger breaches a governor limit",
    UNDECIDABLE: "undecidable: no breach found but at least one trigger could not be bounded",
    USAGE: "usage: bad arguments, unreadable project, invalid coverage report or policy",
}
