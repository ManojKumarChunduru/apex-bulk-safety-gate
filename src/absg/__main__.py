"""`python -m absg` is the same as the `absg` console script."""

import sys

from absg.cli import main

sys.exit(main())
