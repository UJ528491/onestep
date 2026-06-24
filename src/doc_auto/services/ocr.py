from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import threading

from winrt.windows.media.ocr import OcrEngine as WinOcrEngine
from winrt.windows.graphics.imaging import BitmapDecoder as WinBitmapDecoder
from winrt.windows.storage.streams import DataWriter as WinDataWriter, InMemoryRandomAccessStream as WinInMemoryRandomAccessStream
from winrt.windows.globalization import Language as WinLanguage

from doc_auto.services.runtime_paths import worker_command

HAS_WINRT_OCR = True
winrt_ocr_lock = threading.Lock()


@dataclass
class OcrResult:
    text: str
    error: str
    tokens: list[dict[str, Any]]
    image_width: int | None = None
    image_height: int | None = None


class OcrEngine:
    DEFAULT_TIMEOUT_SECONDS = 90

    def run(self, source: Path, output_json: Path | None = None, force: bool = False) -> OcrResult:
        if output_json is not None:
            output_json.parent.mkdir(parents=True, exist_ok=True)
            if output_json.exists() and not force:
                cached = self._load(output_json)
                if cached and cached.tokens:
                    return cached

        if source.suffix.lower() == ".pdf":
            width, height = self._image_size(source)
            result = OcrResult("", "PDF는 이미지로 분리한 뒤 OCR해야 합니다.", [], width, height)
            self._save(output_json, source, result, "none")
            return result

        temp_json: Path | None = None
        temp_dir: Path | None = None
        target_json = output_json
        last_error = ""
        try:
            if target_json is None:
                temp_fd, temp_path = tempfile.mkstemp(suffix=".json")
                os.close(temp_fd)
                temp_json = Path(temp_path)
                target_json = temp_json

            attempts: list[tuple[str, Path]] = [("original", source)]
            attempt_index = 0
            while attempt_index < len(attempts):
                label, attempt_source = attempts[attempt_index]
                try:
                    if target_json.exists():
                        target_json.unlink(missing_ok=True)
                    self._run_ocr_worker_once(attempt_source, target_json, self.DEFAULT_TIMEOUT_SECONDS)
                    result = self._load(target_json)
                    if result and (result.text or result.tokens or not result.error):
                        if attempt_source != source and output_json is not None:
                            self._save(output_json, source, result, f"winrt:{label}")
                        return result
                    last_error = result.error if result else "OCR worker result JSON missing"
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"

                if label == "original":
                    normalized = self._normalized_image_copy(source)
                    if normalized is not None:
                        temp_dir = normalized.parent
                        attempts.append(("normalized_png", normalized))
                attempt_index += 1

            width, height = self._image_size(source)
            result = OcrResult("", f"Windows OCR 실행 실패: {last_error}", [], width, height)
            self._save(output_json, source, result, "error")
            return result
        finally:
            if temp_json is not None:
                temp_json.unlink(missing_ok=True)
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def run_image_batch(self, images: list[Any], timeout_seconds: int | None = None) -> list[str]:
        if not images:
            return []
        temp_dir = Path(tempfile.mkdtemp(prefix="doc_auto_ocr_batch_"))
        target_json = temp_dir / "batch_result.json"
        image_paths: list[Path] = []
        try:
            for index, image in enumerate(images):
                path = temp_dir / f"roi_{index:03d}.png"
                if getattr(image, "mode", "RGB") not in ("RGB", "L"):
                    image = image.convert("RGB")
                image.save(path, "PNG")
                image_paths.append(path)

            timeout = timeout_seconds or max(20, min(180, 8 * len(image_paths)))
            try:
                self._run_ocr_batch_worker_once(image_paths, target_json, timeout)
                data = self._load_batch(target_json)
                if data is not None:
                    texts = [str(item.get("text") or "") for item in data]
                    if len(texts) < len(image_paths):
                        texts.extend([""] * (len(image_paths) - len(texts)))
                    return texts[:len(image_paths)]
            except Exception as exc:
                pass

            texts: list[str] = []
            for path in image_paths:
                single_json = temp_dir / f"{path.stem}.json"
                try:
                    self._run_ocr_worker_once(path, single_json, self.DEFAULT_TIMEOUT_SECONDS)
                    result = self._load(single_json)
                    texts.append(result.text if result else "")
                except Exception:
                    texts.append("")
            return texts
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _run_ocr_worker_once(self, source: Path, target_json: Path, timeout_seconds: int) -> None:
        cmd = worker_command("--ocr-worker", str(source.resolve()), str(target_json.resolve()))
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout_seconds,
            **self._subprocess_window_kwargs(),
        )

    def _run_ocr_batch_worker_once(self, image_paths: list[Path], target_json: Path, timeout_seconds: int) -> None:
        cmd = worker_command("--ocr-batch-worker", str(target_json.resolve()))
        cmd.extend(str(path.resolve()) for path in image_paths)
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout_seconds,
            **self._subprocess_window_kwargs(),
        )

    def _normalized_image_copy(self, source: Path) -> Path | None:
        temp_dir: Path | None = None
        try:
            from PIL import Image, ImageOps

            temp_dir = Path(tempfile.mkdtemp(prefix="doc_auto_ocr_norm_"))
            target = temp_dir / f"{source.stem}.png"
            with Image.open(source) as image:
                image = ImageOps.exif_transpose(image)
                if image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
                image.save(target, "PNG")
            return target
        except Exception:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
            return None

    @staticmethod
    def _subprocess_window_kwargs() -> dict[str, Any]:
        if sys.platform != "win32":
            return {}
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        return {"startupinfo": startupinfo, "creationflags": 0x08000000}

    async def _run_win_ocr(self, source: Path) -> OcrResult:
        content = source.read_bytes()
        
        stream = WinInMemoryRandomAccessStream()
        writer = WinDataWriter(stream)
        writer.write_bytes(content)
        await writer.store_async()
        await writer.flush_async()
        stream.seek(0)
        
        decoder = await WinBitmapDecoder.create_async(stream)
        software_bitmap = await decoder.get_software_bitmap_async()
        
        lang = WinLanguage("ko")
        if not WinOcrEngine.is_language_supported(lang):
            engine = WinOcrEngine.try_create_from_user_profile_languages()
        else:
            engine = WinOcrEngine.try_create_from_language(lang)
            
        if not engine:
            return OcrResult("", "윈도우 내장 OCR 엔진을 생성할 수 없습니다.", [])
            
        result = await engine.recognize_async(software_bitmap)
        
        width = software_bitmap.pixel_width
        height = software_bitmap.pixel_height
        
        tokens = []
        for line in result.lines:
            for word in line.words:
                rect = word.bounding_rect
                tokens.append({
                    "text": word.text,
                    "bbox": [rect.x, rect.y, rect.x + rect.width, rect.y + rect.height],
                    "confidence": 0.95
                })
                
        return OcrResult(result.text, "", tokens, width, height)

    def _load(self, output_json: Path) -> OcrResult | None:
        try:
            with output_json.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        return OcrResult(
            text=str(data.get("text") or ""),
            error=str(data.get("error") or ""),
            tokens=list(data.get("tokens") or []),
            image_width=data.get("image_width"),
            image_height=data.get("image_height"),
        )

    def _load_batch(self, output_json: Path) -> list[dict[str, Any]] | None:
        try:
            with output_json.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, list):
            return None
        return [item for item in data if isinstance(item, dict)]

    def _image_size(self, source: Path) -> tuple[int | None, int | None]:
        try:
            from PIL import Image

            with Image.open(source) as image:
                return image.width, image.height
        except Exception:
            return None, None

    def _save(self, output_json: Path | None, source: Path, result: OcrResult, engine: str) -> None:
        if output_json is None:
            return
        payload = self._payload(source, result, engine)
        try:
            with output_json.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _payload(self, source: Path, result: OcrResult, engine: str) -> dict[str, Any]:
        return {
            "source": str(source),
            "text": result.text,
            "error": result.error,
            "engine": engine,
            "tokens": result.tokens,
            "image_width": result.image_width,
            "image_height": result.image_height,
        }


def run_ocr_worker() -> None:
    import sys
    from pathlib import Path
    try:
        source_path = Path(sys.argv[2])
        output_json = Path(sys.argv[3])
        
        # Run WinRT OCR synchronously in single thread
        engine = OcrEngine()
        
        # Force fresh in-process run
        import asyncio
        try:
            with winrt_ocr_lock:
                result = asyncio.run(engine._run_win_ocr(source_path))
            engine._save(output_json, source_path, result, "winrt")
            sys.exit(0)
        except Exception as e:
            width, height = engine._image_size(source_path)
            result = OcrResult("", f"Windows OCR 실행 실패: {e}", [], width, height)
            engine._save(output_json, source_path, result, "error")
            sys.exit(0)  # exit 0 because error is handled and saved
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)


def run_ocr_batch_worker() -> None:
    try:
        if len(sys.argv) < 4:
            sys.exit(1)
        output_json = Path(sys.argv[2])
        image_paths = [Path(arg) for arg in sys.argv[3:]]
        engine = OcrEngine()
        payloads: list[dict[str, Any]] = []
        for source_path in image_paths:
            try:
                with winrt_ocr_lock:
                    result = asyncio.run(engine._run_win_ocr(source_path))
                payloads.append(engine._payload(source_path, result, "winrt"))
            except Exception as exc:
                width, height = engine._image_size(source_path)
                result = OcrResult("", f"Windows OCR 실행 실패: {exc}", [], width, height)
                payloads.append(engine._payload(source_path, result, "error"))
        with output_json.open("w", encoding="utf-8") as f:
            json.dump(payloads, f, ensure_ascii=False)
        sys.exit(0)
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)

