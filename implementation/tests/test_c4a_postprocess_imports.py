from scripts import c4a_evidence_postprocess
from scripts import c4a_finalizer_extensions


def test_c4a_postprocess_modules_import() -> None:
    assert c4a_evidence_postprocess.RESULTS == c4a_finalizer_extensions.RESULTS
