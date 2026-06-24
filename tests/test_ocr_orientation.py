from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from doc_auto.vision.ocr_orientation import OcrOrientationProbe


class FakeBatchOcrRunner:
    def __init__(self, texts: list[str] | list[list[str]]) -> None:
        self.texts = texts
        self.calls: list[int] = []
        self.call_index = 0

    def run_batch(self, images) -> list[str]:
        self.calls.append(len(images))
        if self.texts and isinstance(self.texts[0], list):
            batch = self.texts[self.call_index]
            self.call_index += 1
            return batch
        return self.texts


class RecordingBatchOcrRunner:
    def __init__(self, texts: list[list[str]]) -> None:
        self.texts = texts
        self.calls: list[int] = []
        self.batch_sizes: list[list[tuple[int, int]]] = []
        self.call_index = 0

    def run_batch(self, images) -> list[str]:
        image_list = list(images)
        self.calls.append(len(image_list))
        self.batch_sizes.append([image.size for image in image_list])
        batch = self.texts[self.call_index]
        self.call_index += 1
        return batch


def make_probe_image(path: Path) -> None:
    image = Image.new("RGB", (800, 1000), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for y in range(180, 860, 90):
        draw.line((100, y, 700, y), fill=(80, 80, 80), width=4)
    image.save(path)


def test_ocr_orientation_probe_uses_side_header_phase_first(tmp_path):
    image_path = tmp_path / "doc.jpg"
    make_probe_image(image_path)
    runner = FakeBatchOcrRunner(
        [
            "",
            (
                "진료비 계산서 영수증 환자 성명 병원 약국 금액 날짜 "
                "진료비 계산서 영수증 환자 성명 병원 약국 금액 날짜"
            ),
            "",
            "abc",
        ]
    )

    decision = OcrOrientationProbe(runner).detect(image_path)

    assert decision.detected is True
    assert decision.angle_degrees == 90
    assert decision.method == "ocr_probe"
    assert runner.calls == [4, 4]
    assert decision.region_count == 4
    assert decision.scores[90] > decision.scores[0]


def test_ocr_orientation_probe_keeps_zero_when_competing_angle_is_weak(tmp_path):
    image_path = tmp_path / "doc.jpg"
    make_probe_image(image_path)
    runner = FakeBatchOcrRunner(
        [
            ["", "", "", ""],
            [
                "진료비 영수증 환자 성명 날짜 금액 병원",
                "",
                "진료비 영수증 환자 성명 날짜 금액 병원 서류",
                "",
            ],
            [
                "진료비 영수증 환자 성명 날짜 금액 병원 " * 4,
                "",
                "진료비 영수증 환자 성명 날짜 금액 병원 서류 " * 5,
                "",
            ],
        ]
    )

    decision = OcrOrientationProbe(runner).detect(image_path)

    assert decision.detected is False
    assert decision.angle_degrees == 0
    assert decision.method == "ocr_probe_zero_guard"
    assert runner.calls == [4, 4, 4]


def test_ocr_orientation_probe_rejects_weak_or_tied_text(tmp_path):
    image_path = tmp_path / "doc.jpg"
    make_probe_image(image_path)
    runner = FakeBatchOcrRunner(["가", "", "나", ""])

    decision = OcrOrientationProbe(runner).detect(image_path)

    assert decision.detected is False
    assert decision.angle_degrees == 0


def test_ocr_orientation_probe_full_page_uses_1200_max_side_by_default(tmp_path):
    image_path = tmp_path / "large_doc.jpg"
    image = Image.new("RGB", (2600, 3400), (255, 255, 255))
    image.save(image_path)
    runner = RecordingBatchOcrRunner(
        [
            ["", "", "", ""],
            ["", "", "", ""],
            ["", "", "", ""],
            ["", "", "", ""],
        ]
    )

    OcrOrientationProbe(runner).detect(image_path)

    assert runner.calls == [4, 4, 4, 4]
    assert max(max(size) for size in runner.batch_sizes[-1]) <= 1200


def test_ocr_orientation_probe_region_images_are_size_limited(tmp_path):
    image_path = tmp_path / "large_doc.jpg"
    image = Image.new("RGB", (4000, 5000), (255, 255, 255))
    image.save(image_path)
    runner = RecordingBatchOcrRunner(
        [
            ["", "", "", ""],
            ["", "", "", ""],
            ["", "", "", ""],
            ["", "", "", ""],
        ]
    )

    OcrOrientationProbe(runner, region_max_side=900).detect(image_path)

    assert max(max(size) for batch in runner.batch_sizes for size in batch) <= 1200
    assert max(max(size) for size in runner.batch_sizes[0]) <= 900


def test_ocr_orientation_probe_skips_full_page_for_strong_first_phase_upright(tmp_path):
    image_path = tmp_path / "doc.jpg"
    make_probe_image(image_path)
    strong_upright = "진료비 계산서 영수증 환자 성명 금액 날짜 병원 " * 20
    runner = FakeBatchOcrRunner(
        [
            [strong_upright, "", "", ""],
        ]
    )

    decision = OcrOrientationProbe(runner).detect(image_path)

    assert decision.detected is False
    assert decision.angle_degrees == 0
    assert decision.method == "ocr_probe_upright"
    assert runner.calls == [4]


def test_ocr_orientation_probe_full_page_overrides_false_region_rotation(tmp_path):
    image_path = tmp_path / "doc.jpg"
    make_probe_image(image_path)
    runner = FakeBatchOcrRunner(
        [
            [
                "",
                "진료비 계산서 영수증 환자 성명 금액 날짜 병원 " * 4,
                "",
                "abc",
            ],
            [
                "",
                "진료비 계산서 영수증 환자 성명 금액 날짜 병원 " * 4,
                "",
                "진료비 세부내역 환자등록번호 진료기간 병실 환자구분 비고 " * 12,
            ],
        ]
    )

    decision = OcrOrientationProbe(runner).detect(image_path)

    assert decision.detected is True
    assert decision.angle_degrees == 270
    assert decision.method == "ocr_probe_full_page"
    assert runner.calls == [4, 4]


def test_ocr_orientation_probe_full_page_keeps_upright_against_false_region_rotation(tmp_path):
    image_path = tmp_path / "doc.jpg"
    make_probe_image(image_path)
    runner = FakeBatchOcrRunner(
        [
            [
                "진료비 계산서 영수증 환자 성명 금액 날짜 병원",
                "",
                "",
                "진료비 계산서 영수증 환자 성명 금액 날짜 병원 " * 4,
            ],
            [
                "중앙선거관리위원회 투표 안내문 투표일시 투표소 안내 " * 14,
                "",
                "투표 안내문 선거인명부 등재번호 후보자 안내 " * 5,
                "",
            ],
        ]
    )

    decision = OcrOrientationProbe(runner).detect(image_path)

    assert decision.detected is False
    assert decision.angle_degrees == 0
    assert decision.method == "ocr_probe_full_page_upright"
    assert runner.calls == [4, 4]


def test_ocr_orientation_probe_full_page_overrides_false_region_upright(tmp_path):
    image_path = tmp_path / "doc.jpg"
    make_probe_image(image_path)
    upright_region = (
        "\uc9c4\ub8cc\ube44 \uacc4\uc0b0\uc11c \uc601\uc218\uc99d "
        "\ud658\uc790 \uc131\uba85 \uae08\uc561 \ub0a0\uc9dc \ubcd1\uc6d0 " * 4
    )
    correct_full_page = (
        "\uc9c4\ub8cc\ube44 \uacc4\uc0b0\uc11c \uc601\uc218\uc99d "
        "\ud658\uc790 \uc131\uba85 \uae08\uc561 \ub0a0\uc9dc \ubcd1\uc6d0 "
        "\uae09\uc5ec \ube44\uae09\uc5ec \ud56d\ubaa9 \ubcf8\uc778\ubd80\ub2f4\uae08 " * 12
    )
    runner = FakeBatchOcrRunner(
        [
            ["", "", "", ""],
            [upright_region, "", upright_region[:40], ""],
            ["", "", correct_full_page, ""],
            ["", "", correct_full_page, ""],
        ]
    )

    decision = OcrOrientationProbe(runner).detect(image_path)

    assert decision.detected is True
    assert decision.angle_degrees == 180
    assert decision.method == "ocr_probe_full_page"
    assert runner.calls == [4, 4, 4, 4]
