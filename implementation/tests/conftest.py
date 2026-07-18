"""Shared test bootstrap for source-bound compatibility runtimes."""

# Importing this module replaces only the C2A trade-target executor with the
# source-bound normalized implementation before C2A test modules are imported.
import atos.c2a_allocation_runtime  # noqa: F401,E402
