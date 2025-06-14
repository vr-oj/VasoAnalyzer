# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_data_files
from PyQt5.QtCore import QLibraryInfo

# decide platform‐specific icon
if sys.platform == 'darwin':
    ICON = 'vasoanalyzer/VasoAnalyzerIcon.icns'
elif sys.platform.startswith('win'):
    ICON = 'vasoanalyzer/VasoAnalyzerIcon.ico'
else:
    ICON = None

spec_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
project_dir = os.path.abspath(os.path.join(spec_dir, '..'))
src_dir = os.path.join(project_dir, 'src')

req_subs = collect_submodules('requests')
xl_subs = collect_submodules('openpyxl')

# Collect toolbar icon SVGs from the project root
icon_dir = os.path.join(project_dir, 'icons')
icon_datas = [(os.path.join(icon_dir, f), 'icons') for f in os.listdir(icon_dir)]

# Add Qt platform plugins for macOS
qt_plugins_dir = QLibraryInfo.location(QLibraryInfo.PluginsPath)
qt_plugin_datas = [(os.path.join(qt_plugins_dir, 'platforms'), 'PyQt5/Qt/plugins/platforms')]

a = Analysis(
    [os.path.join(src_dir, 'main.py')],
    pathex=[src_dir],
    binaries=[],
    datas=[
        ('vasoanalyzer/VasoAnalyzerSplashScreen.png', 'vasoanalyzer'),
        ('vasoanalyzer/VasoAnalyzerIcon.icns', 'vasoanalyzer'),
        ('vasoanalyzer/VasoAnalyzerIcon.ico',  'vasoanalyzer'),
    ] + icon_datas + qt_plugin_datas,
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
    [],
    exclude_binaries=True,
    name='VasoAnalyzer 1.7',
    debug=False,
    strip=False,
    upx=True,
    console=False,
    icon=ICON,
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

if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='VasoAnalyzer 1.7.app',
        icon='vasoanalyzer/VasoAnalyzerIcon.icns',
        bundle_identifier=None,
    )
