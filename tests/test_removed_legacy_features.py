from pathlib import Path


def test_legacy_classification_renaming_and_auto_crop_modules_are_removed() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "doc_auto"
    removed_paths = [
        root / "services" / "document_classifier.py",
        root / "services" / "document_detection.py",
        root / "services" / "file_renamer.py",
        root / "services" / "rules.py",
        root / "vision" / "paper_region.py",
        root / "vision" / "scene_crop.py",
        root / "vision" / "rotation_canvas.py",
        root / "vision" / "skew.py",
    ]

    assert [path.name for path in removed_paths if path.exists()] == []


def test_source_tree_has_no_disabled_legacy_feature_flags() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "doc_auto"
    forbidden = (
        "rename_enabled",
        "classification_enabled",
        "crop_enabled",
        "deskew_enabled",
        "rotation_canvas_trim_enabled",
        "DocumentClassifier",
        "FileRenamer",
        "detect_document_type",
        "PaperRegionDetector",
        "SkewAngle",
    )

    matches: list[str] = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                matches.append(f"{path.relative_to(root)}:{token}")

    assert matches == []


def test_readme_does_not_describe_disabled_legacy_features() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    forbidden = (
        "문서 종류 자동분류",
        "OCR 금액 추출",
        "파일명 자동 리네이밍",
        "자동 문서 크롭",
        "비활성화",
    )

    assert [token for token in forbidden if token in readme] == []
