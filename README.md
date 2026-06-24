# OneStep

OneStep은 Windows에서 ZIP, PDF, TIFF, HWP, 이미지 파일을 빠르게 정리하기 위한 로컬 전용 업무 도구입니다.

파일을 드롭하면 압축 해제, PDF/TIFF 분해, 회전, 리사이징, PDF 변환 같은 반복 작업을 한 번에 처리하고, 필요한 파일은 미리보기와 이미지 편집창에서 직접 보정할 수 있습니다.

## 배포

- 현재 버전: `1.0`
- 대상 OS: Windows
- 배포 형태: PyInstaller 기반 무설치 ZIP
- 실행 파일: `OneStep_v1.0.exe`
- 릴리즈 파일: `OneStep-Windows_v1.0.zip`
- 빌드 방식: GitHub Actions Windows runner에서 테스트 후 생성

압축을 푼 뒤 실행 파일을 바로 실행하면 됩니다. 코드 서명이 없는 공개 빌드이므로 Windows SmartScreen 경고가 표시될 수 있습니다. 자세한 내용은 [Windows SmartScreen 안내](docs/smartscreen.md)를 참고하세요.

릴리즈 ZIP의 SHA256 값은 릴리즈 페이지에 함께 게시됩니다.

## 주요 기능

- 파일/폴더 드롭
- ZIP 내부 파일 목록 표시 후 처리
- ZIP 압축 해제
- PDF 페이지별 이미지 분해
- 다중 페이지 TIFF 프레임별 이미지 분해
- HWP 파일 PDF 변환
- 이미지 90도 회전 보정
- 이미지 리사이징
- PNG 결과물 JPG 변환
- 이미지 파일 개별 PDF 변환
- 여러 이미지 파일을 하나의 PDF로 묶기
- 우측 미리보기 패널 및 그리드 미리보기
- 미리보기 전체화면
- 이미지 편집창에서 영역 자르기, 회전, 기울임 보정, 편집 이력 이동
- 작업 정지

## 지원 파일

- 압축파일: `zip`
- PDF: `pdf`
- TIFF: `tif`, `tiff`
- 이미지: `jpg`, `jpeg`, `png`, `bmp`
- HWP: `hwp`

## 처리 방식

1. 사용자가 파일, 폴더, ZIP, PDF, TIFF, HWP, 이미지를 목록 영역에 드롭합니다.
2. 새 작업이 들어오면 기존 목록을 새 입력 목록으로 교체합니다.
3. 작업 시작 시 temp 폴더를 비웁니다.
4. ZIP은 압축을 풀고, PDF/TIFF는 페이지 또는 프레임별 이미지로 분해합니다.
5. HWP는 로컬 PC에 설치된 한글 프로그램을 사용해 PDF로 변환합니다.
6. 이미지는 설정에 따라 회전 보정, 리사이징, PNG-JPG 변환을 수행합니다.
7. 완료된 파일만 작업 폴더 또는 원래 위치에 생성/교체합니다.
8. 목록은 최종 결과물 기준으로 갱신됩니다.

## 설정

설정값은 실행 파일 폴더의 `data/settings.json`에 저장됩니다.

주요 설정:

- temp 폴더
- 회전
- 리사이징
- PNG-JPG 변환
- PDF 변환 후 원본파일 삭제
- PDF 묶음 후 원본파일 삭제
- 압축파일 작업 후 원본파일 삭제
- 압축파일 현재 위치에 작업 풀기
- 긴 변 최대값
- JPG 품질

## 개인정보 및 보안

OneStep은 로컬 PC 안에서만 파일을 처리합니다.

- 외부 서버 전송 없음
- 외부 API 호출 없음
- 텔레메트리/분석 도구 없음
- 런타임 로그 파일 생성 없음
- 문서 내용, OCR 결과, 파일명, 파일 경로 수집 없음

작업 과정에서 필요한 임시 파일은 설정된 temp 폴더에만 생성됩니다. 새 작업이 시작되면 temp 폴더를 비우며, 비정상 종료 시 남은 임시 파일은 사용자가 삭제할 수 있습니다.

## 빌드 검증

공개 릴리즈는 GitHub Actions에서 다음 순서로 생성됩니다.

1. `requirements-lock.txt` 기준 의존성 설치
2. `python -m pytest -q` 테스트 실행
3. PyInstaller 빌드
4. `OneStep-Windows_v1.0.zip` 생성
5. SHA256 파일 생성 및 릴리즈 첨부

빌드 로그는 GitHub 저장소의 `Actions` 탭에서 확인할 수 있습니다. 다운로드한 ZIP은 다음 명령으로 릴리즈에 게시된 SHA256 값과 비교할 수 있습니다.

```powershell
Get-FileHash .\OneStep-Windows_v1.0.zip -Algorithm SHA256
```

## 파일 삭제

설정에서 원본 삭제 옵션을 켠 경우 일부 작업 후 원본 파일을 Windows 휴지통으로 이동합니다.

- PDF 변환 후 원본파일 삭제
- PDF 묶음 후 원본파일 삭제
- 압축파일 작업 후 원본파일 삭제

휴지통 이동이 OS 권한, 경로 상태, 보안 정책 때문에 실패하면 앱은 결과물을 유지하고 삭제를 건너뜁니다.

## 기술 스택

- Python
- PySide6
- PyInstaller
- Pillow
- OpenCV headless
- NumPy
- Windows Runtime OCR
- Windows Runtime PDF
- pywin32
- pytest

## 문서

- [사용 설명서](docs/user-guide.md)
- [Windows SmartScreen 안내](docs/smartscreen.md)
- [개인정보 처리 안내](PRIVACY.md)
- [보안 안내](SECURITY.md)
- [서드파티 고지](THIRD_PARTY_NOTICES.md)

## 개발

실행:

```powershell
python run.py
```

테스트:

```powershell
python -m pytest -q
```

의존성:

```powershell
python -m pip install -r requirements-lock.txt
```
