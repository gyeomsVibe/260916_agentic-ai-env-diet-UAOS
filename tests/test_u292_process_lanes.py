"""U292: Test suite alias for 3-Tool Card & 5-Lane Parallel Window OS."""
from __future__ import annotations

import unittest

from tests.test_u287_process_lane_parallel_windows import TestU287ProcessLaneParallelWindows


class TestU292ProcessLanes(TestU287ProcessLaneParallelWindows):
    """Alias test case so `python -m unittest tests.test_u292_process_lanes -v` runs the full U287+U292 suite."""


if __name__ == "__main__":
    unittest.main()
