"""PyInstaller onedir build for the native Windows distribution."""

from pathlib import Path

import certifi
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules


ROOT = Path(SPECPATH).resolve().parents[1]
BACKEND = ROOT / "backend"
PACKAGE = BACKEND / "src" / "tonewatch"
WEB_DIST = PACKAGE / "web_dist"
if not WEB_DIST.is_dir():
    raise SystemExit("web/dist must be copied to backend/src/tonewatch/web_dist before packaging")

datas = [
    (str(WEB_DIST), "tonewatch/web_dist"),
    (certifi.where(), "certifi"),
    (str(BACKEND / "alembic.ini"), "."),
]
datas.extend(collect_data_files("tonewatch.storage.migrations", include_py_files=True))
datas.extend(collect_data_files("tonewatch.storage.migrations.versions", include_py_files=True))

import sounddevice

sounddevice_data = Path(sounddevice.__file__).resolve().parent / "_sounddevice_data"
if sounddevice_data.is_dir():
    datas.append((str(sounddevice_data), "sounddevice/_sounddevice_data"))
else:
    raise SystemExit("sounddevice wheel is missing _sounddevice_data/PortAudio")

binaries = collect_dynamic_libs("av")
hiddenimports = collect_submodules("tonewatch") + [
    "aiosqlite",
    "sounddevice",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "sqlalchemy.ext.asyncio",
    "win32service",
    "win32serviceutil",
    "servicemanager",
    "pywintypes",
]

analysis = Analysis(
    [str(BACKEND / "src" / "tonewatch" / "__main__.py")],
    pathex=[str(BACKEND / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="tonewatch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="tonewatch",
)
