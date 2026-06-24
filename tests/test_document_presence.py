from PIL import Image, ImageDraw

from doc_auto.vision.document_presence import DocumentPresenceAnalyzer


def test_document_presence_detects_white_paper_on_dark_background(tmp_path):
    image_path = tmp_path / "dark_background.jpg"
    image = Image.new("RGB", (800, 1000), (25, 25, 25))
    draw = ImageDraw.Draw(image)
    draw.rectangle((160, 120, 640, 880), fill=(235, 235, 230))
    image.save(image_path)

    result = DocumentPresenceAnalyzer().analyze(image_path)

    assert result.document_like is True
    assert result.scene_kind == "dark_background"
    assert result.confidence >= 0.75


def test_document_presence_detects_full_frame_document(tmp_path):
    image_path = tmp_path / "full_frame.jpg"
    image = Image.new("RGB", (800, 1000), (245, 245, 240))
    draw = ImageDraw.Draw(image)
    for y in range(120, 820, 80):
        draw.line((80, y, 720, y), fill=(80, 80, 80), width=2)
    image.save(image_path)

    result = DocumentPresenceAnalyzer().analyze(image_path)

    assert result.document_like is True
    assert result.scene_kind == "full_frame"
    assert result.confidence >= 0.70


def test_document_presence_detects_text_graphic_document(tmp_path):
    image_path = tmp_path / "text_graphic.jpg"
    image = Image.new("RGB", (1000, 700), (232, 226, 214))
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 120, 900, 580), fill=(248, 246, 238))
    draw.rectangle((120, 140, 430, 520), fill=(80, 85, 180))
    draw.rectangle((460, 140, 880, 220), fill=(230, 230, 236))
    for y in range(250, 520, 42):
        draw.line((470, y, 870, y), fill=(45, 45, 45), width=4)
    image.save(image_path)

    result = DocumentPresenceAnalyzer().analyze(image_path)

    assert result.document_like is True
    assert result.scene_kind == "text_graphic_document"
    assert result.confidence >= 0.65


def test_document_presence_detects_color_document_on_white_background(tmp_path):
    image_path = tmp_path / "color_document_canvas.png"
    image = Image.new("RGB", (1200, 1600), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((190, 220, 1010, 1380), fill=(45, 47, 55), outline=(140, 140, 140), width=3)
    draw.rectangle((300, 330, 900, 430), fill=(235, 235, 230))
    draw.rectangle((310, 500, 890, 610), fill=(235, 235, 230))
    draw.rectangle((310, 680, 890, 780), fill=(235, 235, 230))
    draw.rectangle((330, 850, 470, 980), fill=(170, 70, 90))
    draw.rectangle((520, 850, 660, 980), fill=(60, 110, 190))
    draw.rectangle((710, 850, 850, 980), fill=(80, 160, 110))
    for y in range(1070, 1260, 70):
        draw.line((320, y, 880, y), fill=(235, 235, 230), width=8)
    draw.polygon([(0, 0), (160, 0), (0, 260)], fill=(30, 30, 30))
    draw.polygon([(1200, 1600), (1040, 1600), (1200, 1340)], fill=(30, 30, 30))
    image.save(image_path)

    result = DocumentPresenceAnalyzer().analyze(image_path)

    assert result.document_like is True
    assert result.scene_kind == "color_document_canvas"
    assert result.confidence >= 0.60


def test_document_presence_detects_low_saturation_warm_background(tmp_path):
    image_path = tmp_path / "warm_background_document.png"
    image = Image.new("RGB", (1000, 1300), (205, 195, 176))
    draw = ImageDraw.Draw(image)
    draw.rectangle((150, 120, 850, 1180), fill=(235, 235, 230))
    draw.rectangle((240, 220, 760, 360), outline=(80, 80, 80), width=3)
    for y in range(460, 880, 80):
        draw.line((240, y, 760, y), fill=(70, 70, 70), width=4)
    draw.rectangle((240, 940, 760, 1100), outline=(80, 80, 80), width=3)
    image.save(image_path)

    result = DocumentPresenceAnalyzer().analyze(image_path)

    assert result.document_like is True
    assert result.scene_kind == "warm_background_document"
    assert result.confidence >= 0.60


def test_document_presence_rejects_color_photo_like_image(tmp_path):
    image_path = tmp_path / "photo.jpg"
    image = Image.new("RGB", (800, 1000), (40, 120, 180))
    draw = ImageDraw.Draw(image)
    draw.ellipse((180, 220, 620, 760), fill=(180, 80, 120))
    image.save(image_path)

    result = DocumentPresenceAnalyzer().analyze(image_path)

    assert result.document_like is False
    assert result.scene_kind == "non_document"
    assert result.confidence <= 0.40
