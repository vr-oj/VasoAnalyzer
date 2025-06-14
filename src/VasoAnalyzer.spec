# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_data_files

# decide platform‐specific icon
if sys.platform == 'darwin':
    ICON = 'vasoanalyzer/VasoAnalyzerIcon.icns'
elif sys.platform.startswith('win'):
    ICON = 'vasoanalyzer/VasoAnalyzerIcon.ico'
else:
    ICON = None

spec_dir = os.path.dirname(__file__)
project_dir = os.getcwd()
req_subs = collect_submodules('requests')
xl_subs  = collect_submodules('openpyxl')
icon_dir = os.path.join(spec_dir, 'icons')
icon_datas = [(os.path.join(icon_dir, f), 'icons') for f in os.listdir(icon_dir)]

a = Analysis(
    ['main.py'],
    pathex=[project_dir],
    binaries=[],
    datas=[
        ('vasoanalyzer/VasoAnalyzerSplashScreen.png', 'vasoanalyzer'),
        # include whichever icon file(s) you ship
        ('vasoanalyzer/VasoAnalyzerIcon.icns', 'vasoanalyzer'),
        ('vasoanalyzer/VasoAnalyzerIcon.ico',  'vasoanalyzer'),
    ] + icon_datas,
    hiddenimports=[
        'tkinter',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'PIL._tkinter_finder',
    ] + req_subs + xl_subs,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],                    # no extra binaries here
    exclude_binaries=True,
    name='VasoAnalyzer 1.7',   # base name; extension/platform is automatic
    debug=False,
    strip=False,
    upx=True,
    console=False,         # GUI only
    icon=ICON,             # will be .icns on mac, .ico on Windows
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='VasoAnalyzer 1.7',
)

# Only on macOS do we wrap into a .app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='VasoAnalyzer 1.7.app',
        icon='vasoanalyzer/VasoAnalyzerIcon.icns',
        bundle_identifier=None,
    )
