from pathlib import Path


def test_public_text_uses_image_editing_terms() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = [
        root / "README.md",
        root / "PRIVACY.md",
        root / "SECURITY.md",
        root / "docs" / "user-guide.md",
        root / "src" / "doc_auto" / "ui" / "settings_dialog.py",
    ]

    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "이미지 편집창" in text
    assert "영역 자르기" in text
    assert "수동컷" not in text
    assert "수정컷" not in text


def test_public_release_files_use_onestep_names() -> None:
    root = Path(__file__).resolve().parents[1]
    workflow = root / ".github" / "workflows" / "build-windows.yml"
    pyproject = root / "pyproject.toml"

    assert (root / "OneStep-Windows.spec").exists()
    assert not (root / "Doc-Auto-Windows-OCR.spec").exists()
    assert (root / "assets" / "onestep.ico").exists()
    assert not (root / "assets" / "doc_auto.ico").exists()

    public_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            workflow,
            pyproject,
            root / "OneStep-Windows.spec",
        ]
    )

    assert "Doc-Auto" not in public_text
    assert "doc-auto" not in public_text
    assert "doc_auto.ico" not in public_text
