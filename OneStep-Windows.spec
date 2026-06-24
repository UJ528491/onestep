# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import re

_pyproject = Path('pyproject.toml').read_text(encoding='utf-8')
APP_VERSION = re.search(r'^version\s*=\s*"([^"]+)"', _pyproject, re.MULTILINE).group(1)
APP_NAME = f'OneStep_v{APP_VERSION}'
APP_ICON = 'assets/onestep.ico'

a = Analysis(
    ['run.py'],
    pathex=['src'],
    binaries=[],
    datas=[(APP_ICON, 'assets')],
    hiddenimports=[
        'winrt.windows.media.ocr',
        'winrt.windows.graphics.imaging',
        'winrt.windows.storage.streams',
        'winrt.windows.data.pdf',
        'winrt.windows.storage',
        'winrt.windows.globalization',
        'winrt.windows.foundation',
        'winrt.windows.foundation.collections',
        'cv2',
        'numpy',
        'pythoncom',
        'pywintypes',
        'win32com',
        'win32com.client',
        'win32com.shell',
        'win32com.shell.shell',
        'win32com.shell.shellcon',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=APP_ICON,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
