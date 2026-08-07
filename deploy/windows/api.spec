# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for SoyMutDB API service (Windows).

Build with:
    conda activate soymutdb-api
    pyinstaller deploy/windows/api.spec
"""

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Collect all soymutdb submodules
hiddenimports = []
hiddenimports += collect_submodules('soymutdb')
hiddenimports += collect_submodules('fastapi')
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('sqlalchemy')
hiddenimports += collect_submodules('alembic')
hiddenimports += collect_submodules('clickhouse_connect')
hiddenimports += collect_submodules('redis')
hiddenimports += collect_submodules('jose')

# Data files
datas = []
# Alembic migrations
datas += [('../../apps/api/alembic', 'alembic')]
datas += [('../../apps/api/alembic.ini', '.')]

block_cipher = None

a = Analysis(
    ['../../apps/api/src/soymutdb/main.py'],
    pathex=['../../apps/api/src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'pandas',
        'numpy',
        'scipy',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
    ],
    noarchive=False,
    optimize=2,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='soymutdb-api',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='soymutdb-api',
)
