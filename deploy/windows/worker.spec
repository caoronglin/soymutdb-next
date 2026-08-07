# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for SoyMutDB Worker service (Windows).

Build with:
    conda activate soymutdb-worker
    pyinstaller deploy/windows/worker.spec
"""

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = []
hiddenimports += collect_submodules('soymutdb_worker')
hiddenimports += collect_submodules('celery')
hiddenimports += collect_submodules('kombu')
hiddenimports += collect_submodules('billiard')
hiddenimports += collect_submodules('Bio')
hiddenimports += collect_submodules('clickhouse_connect')
hiddenimports += collect_submodules('boto3')
hiddenimports += collect_submodules('sqlalchemy')

# Data files
datas = []

block_cipher = None

a = Analysis(
    ['../../apps/worker/src/soymutdb_worker/main.py'],
    pathex=['../../apps/worker/src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'PyQt5',
        'PyQt6',
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
    name='soymutdb-worker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='soymutdb-worker',
)
