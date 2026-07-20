#!/usr/bin/env python3
"""Run C5A source binding, governance binding, independent finalization, and manifest."""
from __future__ import annotations

try:
    import scripts.c5a_source_inventory as source_inventory
    import scripts.c5a_program_evidence_extension as program_evidence
    import scripts.c5a_finalizer as finalizer
    import scripts.c5a_program_finalizer_extension as program_finalizer
    import scripts.complete_c5a_manifest as complete_manifest
except ModuleNotFoundError:  # pragma: no cover
    import c5a_source_inventory as source_inventory  # type: ignore
    import c5a_program_evidence_extension as program_evidence  # type: ignore
    import c5a_finalizer as finalizer  # type: ignore
    import c5a_program_finalizer_extension as program_finalizer  # type: ignore
    import complete_c5a_manifest as complete_manifest  # type: ignore


def main() -> int:
    source_inventory.main()
    program_evidence.main()
    finalizer.main()
    program_finalizer.main()
    complete_manifest.main()
    print(
        "C5A finalization pipeline PASS: source snapshot -> program authority binding -> "
        "independent economic recomputation -> governance verification -> complete manifest"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
