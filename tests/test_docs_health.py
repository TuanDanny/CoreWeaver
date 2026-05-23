from scripts.check_docs_health import main


def test_docs_health() -> None:
    assert main() == 0
