# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Windows portable build.

Run from the repository root::

    uv run pyinstaller packaging/chemeq.spec --noconfirm
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - provided by PyInstaller

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "multipart",
    "jinja2.ext",
    "lxml.etree",
    "lxml._elementpath",
]
hiddenimports += collect_submodules(
    "mcp", filter=lambda name: not name.startswith("mcp.cli"), on_error="ignore"
)
hiddenimports += collect_submodules("mcp_types", on_error="ignore")
hiddenimports += collect_submodules("anyio", on_error="ignore")

datas = [
    (str(ROOT / "src" / "chemeq" / "web" / "templates"), "chemeq/web/templates"),
    (str(ROOT / "src" / "chemeq" / "web" / "static"), "chemeq/web/static"),
]
datas += collect_data_files("pillow_heif")
datas += collect_data_files("mcp")
binaries = collect_dynamic_libs("pillow_heif")

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="chemeq",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="chemeq",
)
