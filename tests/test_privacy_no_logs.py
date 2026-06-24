from pathlib import Path


def test_runtime_log_modules_are_removed() -> None:
    services = Path(__file__).resolve().parents[1] / "src" / "doc_auto" / "services"

    assert not (services / "diagnostics.py").exists()
    assert not (services / "log_policy.py").exists()


def test_source_tree_has_no_runtime_log_writers() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src" / "doc_auto"
    forbidden = (
        "log_classification",
        "log_crash",
        "log_hwp",
        "log_hwp_exception",
        "DOC_AUTO_LOG",
        "classification.log",
        "crash.log",
        "roi_selections.log",
        "logs_dir",
        "log_dir",
    )

    matches: list[str] = []
    for path in sorted(source_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                matches.append(f"{path.relative_to(source_root)}:{token}")

    assert matches == []


def test_source_tree_has_no_runtime_log_artifacts() -> None:
    src_root = Path(__file__).resolve().parents[1] / "src"

    assert sorted(path.name for path in src_root.rglob("*.log")) == []
