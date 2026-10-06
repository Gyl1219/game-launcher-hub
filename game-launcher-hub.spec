# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# 随包只读资源（解包到 RES_DIR = sys._MEIPASS）：
#   assets/              图标等
#   config.example.json  首次运行自动复制成 APP_DIR/config.json 的模板（缺它打包版一启动就报错）
#   config.reserved.json 预约条目（代码在 APP_DIR 找不到时会回退到 RES_DIR 读）
datas = [
    ('assets', 'assets'),
    ('config.example.json', '.'),
    ('config.reserved.json', '.'),
]
binaries = []
hiddenimports = ['dulwich', 'dulwich.porcelain', 'dulwich.client', 'dulwich.repo']
tmp_ret = collect_all('qfluentwidgets')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name='game-launcher-hub',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/launcher-icon.ico'],
)
