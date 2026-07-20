#!/usr/bin/env python3
"""Run C4A source binding, independent checks, postprocessing, and final manifest.

This explicit order is part of the evidence contract:
1. snapshot exact source;
2. independently verify primitive production evidence;
3. complete universe and rebalance-ledger views;
4. independently verify those completed views;
5. build and self-verify the final complete manifest.
"""
from __future__ import annotations

try:
    import scripts.c4a_evidence_postprocess as postprocess
    import scripts.c4a_finalizer_extensions as extensions
    import scripts.c4a_source_inventory as source_inventory
    import scripts.complete_c4a_manifest as complete_manifest
    import scripts.finalize_c4a_evidence as base_finalizer
except ModuleNotFoundError:  # pragma: no cover
    import c4a_evidence_postprocess as postprocess  # type: ignore
    import c4a_finalizer_extensions as extensions  # type: ignore
    import c4a_source_inventory as source_inventory  # type: ignore
    import complete_c4a_manifest as complete_manifest  # type: ignore
    import finalize_c4a_evidence as base_finalizer  # type: ignore


def main() -> int:
    source_inventory.main()
    base_finalizer.main()
    postprocess.main()
    extensions.main()
    complete_manifest.main()
    print(
        "C4A finalization pipeline PASS: source snapshot -> base independent "
        "verification -> evidence completion -> extension verification -> complete manifest"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
