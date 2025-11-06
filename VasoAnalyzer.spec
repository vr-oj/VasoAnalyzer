# VasoAnalyzer
# Copyright © 2025 Osvaldo J. Vega Rodríguez
# Licensed under CC BY-NC-SA 4.0 International
# http://creativecommons.org/licenses/by-nc-sa/4.0/

# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_all
from PyQt5.QtCore import QLibraryInfo

# Increase recursion limit for Windows PyInstaller builds
sys.setrecursionlimit(5000)

spec_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
if os.path.isdir(os.path.join(spec_dir, 'src')):
    project_dir = spec_dir
else:
    project_dir = os.path.abspath(os.path.join(spec_dir, '..'))
src_dir = os.path.join(project_dir, 'src')
package_assets_dir = os.path.join(src_dir, 'vasoanalyzer')

# decide platform‐specific icon
if sys.platform == 'darwin':
    ICON = os.path.join(package_assets_dir, 'VasoAnalyzerIcon.icns')
elif sys.platform.startswith('win'):
    ICON = os.path.join(package_assets_dir, 'VasoAnalyzerIcon.ico')
else:
    ICON = None

req_subs = collect_submodules('requests')
xl_subs = collect_submodules('openpyxl')

# Collect matplotlib data files and submodules for better Windows compatibility
mpl_datas, mpl_binaries, mpl_hiddenimports = collect_all('matplotlib')

# Collect toolbar icon SVGs from the project root
icon_dir = os.path.join(project_dir, 'icons')
icon_datas = []
if os.path.isdir(icon_dir):
    icon_datas = [(os.path.join(icon_dir, f), 'icons') for f in os.listdir(icon_dir)]

# Add Qt platform plugins for macOS
qt_plugins_dir = QLibraryInfo.location(QLibraryInfo.PluginsPath)
qt_plugin_datas = [(os.path.join(qt_plugins_dir, 'platforms'), 'PyQt5/Qt/plugins/platforms')]

datas = [
    (os.path.join(package_assets_dir, 'VasoAnalyzerSplashScreen.png'), 'vasoanalyzer'),
    (os.path.join(package_assets_dir, 'VasoAnalyzerIcon.icns'), 'vasoanalyzer'),
    (os.path.join(package_assets_dir, 'VasoAnalyzerIcon.ico'), 'vasoanalyzer'),
    (os.path.join(package_assets_dir, 'VasoAnalyzerIcon.svg'), 'vasoanalyzer'),
] + icon_datas + qt_plugin_datas + mpl_datas

a = Analysis(
    [os.path.join(src_dir, 'main.py')],
    pathex=[src_dir],
    binaries=mpl_binaries,
    datas=datas,
    hiddenimports=[
        'tkinter',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'PIL._tkinter_finder',
        # VasoAnalyzer modules
        'vasoanalyzer.ui.publication_studio',
        'vasoanalyzer.ui.dialogs.unified_settings_dialog',
        'vasoanalyzer.ui.dialogs.settings.frame_tab',
        'vasoanalyzer.ui.dialogs.settings.layout_tab',
        'vasoanalyzer.ui.dialogs.settings.axis_tab',
        'vasoanalyzer.ui.dialogs.settings.style_tab',
        'vasoanalyzer.ui.dialogs.settings.event_labels_tab',
        # Matplotlib backends for figure export
        'matplotlib.backends.backend_svg',
        'matplotlib.backends.backend_pdf',
        'matplotlib.backends.backend_ps',
        'matplotlib.backends.backend_agg',
        'matplotlib.backends.backend_tkagg',
        'matplotlib.backends.backend_qt5agg',
        # Numpy
        'numpy',
        'numpy.core._methods',
        'numpy.lib.format',
        # Pillow
        'PIL',
        'PIL.Image',
    ] + req_subs + xl_subs + mpl_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
    module_collection_mode={
        'vasoanalyzer': 'py',
    },
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe_common_kwargs = dict(
    name='VasoAnalyzer',
    debug=False,
    strip=False,
    upx=True,
    console=False,
    icon=ICON,
)

if sys.platform == 'darwin':
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        **exe_common_kwargs,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=True,
        name='VasoAnalyzer',
    )

    app = BUNDLE(
        coll,
        name='VasoAnalyzer.app',
        icon=ICON,
        bundle_identifier='org.vasoanalyzer.vaso',
        info_plist=os.path.join(project_dir, 'packaging', 'macos', 'Info.plist'),
    )
else:
    # Windows build - disable UPX for better compatibility
    exe_common_kwargs_win = exe_common_kwargs.copy()
    exe_common_kwargs_win['upx'] = False
    # Set console=True for debugging, change to False for production
    exe_common_kwargs_win['console'] = False

    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        exclude_binaries=False,
        **exe_common_kwargs_win,
    )
