"""Shared test bootstrap for source-bound compatibility runtimes."""

# Importing these modules installs only frozen, source-bound compatibility
# layers before their corresponding test modules are imported.
import atos.c2a_allocation_runtime  # noqa: F401,E402
import scripts.c4a_reference_runtime  # noqa: F401,E402
