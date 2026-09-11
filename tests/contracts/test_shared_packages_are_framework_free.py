from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_shared_phase_1_packages_do_not_import_streamlit() -> None:
    package_sources = (ROOT / "packages").glob("*/python/**/*.py")
    offenders = [
        source.relative_to(ROOT).as_posix()
        for source in package_sources
        if "streamlit" in source.read_text(encoding="utf-8").lower()
    ]
    assert offenders == []
