# Windows SmartScreen 안내

OneStep은 무료로 배포되는 코드 서명 없는 Windows 실행 파일입니다. 유료 코드 서명 인증서나 충분한 게시자 평판이 없기 때문에 Windows에서 파란색 SmartScreen 경고가 표시될 수 있습니다.

## 경고의 의미

SmartScreen 경고는 Windows가 아직 앱 또는 게시자를 충분히 신뢰하지 못한다는 의미입니다. 악성코드 탐지와는 다른 경고입니다.

OneStep은 작업 파일이나 사용 정보를 외부 서버로 전송하지 않습니다. 자세한 내용은 [`PRIVACY.md`](../PRIVACY.md)를 확인하세요.

공개 릴리즈 ZIP은 GitHub Actions Windows runner에서 테스트 후 생성됩니다. 빌드 로그는 저장소의 `Actions` 탭에서 확인할 수 있습니다.

## 다운로드 파일 확인

릴리즈 ZIP 파일을 다운로드한 뒤 다운로드 폴더에서 PowerShell을 열고 다음 명령을 실행합니다.

```powershell
Get-FileHash .\OneStep-Windows_v1.0.zip -Algorithm SHA256
```

출력된 값을 GitHub 릴리즈 페이지에 게시된 SHA256 값과 비교합니다. 값이 같으면 다운로드한 파일이 릴리즈 파일과 바이트 단위로 동일하다는 뜻입니다.

## 실행 방법

SmartScreen 경고가 표시되면 다음 순서로 실행합니다.

1. `추가 정보`를 누릅니다.
2. 앱 이름이 `OneStep_v1.0.exe`인지 확인합니다.
3. `실행`을 누릅니다.

OneStep은 공식 GitHub 릴리즈 페이지에서만 다운로드하세요.
