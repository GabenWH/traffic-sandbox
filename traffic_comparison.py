"""Historical comparison API for frozen test-reference engines.

The application driver is exclusively C++; this compatibility import preserves
existing diagnostic scripts without restoring production Python driving modes.
"""
from tests.reference_comparison import compare_traffic_engines
