# -*- mode: python ; coding: utf-8 -*-
import os
import sys
sys.setrecursionlimit(sys.getrecursionlimit() * 5)  # Increase recursion limit

project_dir = os.getcwd()

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[project_dir],
    binaries=[],
    datas=[
        ('vasoanalyzer/splash_image_base64.txt', 'vasoanalyzer'),
        ('vasoanalyzer/VasoAnalyzerIcon.icns', 'vasoanalyzer'),
        ('vasoanalyzer/VasoAnalyzerIcon.ico', 'vasoanalyzer'),
    ],
    hiddenimports=['tkinter', 'tkinter.filedialog', 'tkinter.messagebox', 'PIL._tkinter_finder'],  # Add tkinter dependencies
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VasoAnalyzer 2.5',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # You might want to set this to True for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='vasoanalyzer/VasoAnalyzerIcon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VasoAnalyzer 2.5',
)

app = BUNDLE(
    coll,
    name='VasoAnalyzer 2.5.app',
    icon='vasoanalyzer/VasoAnalyzerIcon.icns',
    bundle_identifier=None,
)