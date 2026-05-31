# -*- mode: python ; coding: utf-8 -*-
# PyInstaller ビルド定義
# 使い方: python -m PyInstaller apy_schedule.spec --noconfirm

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(SPEC)))
from version import APP_VERSION

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# matplotlib のデータファイル（フォント・スタイル等）を同梱
mpl_datas = collect_data_files('matplotlib')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=mpl_datas + [('version.py', '.')],
    hiddenimports=[
        # matplotlib バックエンド（matplotlib.use() で動的にロードされるため明示）
        'matplotlib.backends.backend_qt5agg',
        'matplotlib.backends.backend_agg',
        # PyQt5
        'PyQt5.sip',
        'PyQt5.QtPrintSupport',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 不要な大型ライブラリを除外してサイズを削減
        # ※ xml / email / http は pkg_resources の内部依存のため除外不可
        'tkinter',
        'unittest',
        'pydoc',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

_version_file = 'file_version_info.txt' if os.path.exists('file_version_info.txt') else None

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='作業予定管理',          # 出力 EXE のファイル名
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                    # UPX が入っていれば圧縮（未インストールでも動く）
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,               # コンソールウィンドウを非表示
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_version_file,       # Windowsファイルプロパティにバージョン情報を埋め込む
    # icon='icon.ico',           # アイコンを設定する場合はコメント解除
)
