import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "implementation" / "pyproject.toml"
REVIEWED_FREQTRADE_VERSION = "2026.6"


def _freqtrade_requirement(extra: str) -> str:
    project = tomllib.loads(PYPROJECT.read_text())["project"]
    requirements = project["optional-dependencies"][extra]
    matches = [item for item in requirements if item.lower().startswith("freqtrade")]
    assert len(matches) == 1
    return matches[0]


def test_validation_freqtrade_runtime_is_exactly_pinned() -> None:
    assert _freqtrade_requirement("freqtrade") == (
        f"freqtrade=={REVIEWED_FREQTRADE_VERSION}"
    )


def test_research_and_validation_use_same_reviewed_freqtrade_runtime() -> None:
    assert _freqtrade_requirement("research") == (
        f"freqtrade[hyperopt]=={REVIEWED_FREQTRADE_VERSION}"
    )
