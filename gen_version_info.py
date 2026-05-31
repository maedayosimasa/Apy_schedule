"""build.bat から呼ばれる：Windows ファイルプロパティ用 version info を生成する。"""
from version import APP_VERSION, APP_NAME

parts = APP_VERSION.split('.')
major = int(parts[0])
minor = int(parts[1])
patch = int(parts[2]) if len(parts) > 2 else 0

content = f"""# -*- coding: utf-8 -*-
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major},{minor},{patch},0),
    prodvers=({major},{minor},{patch},0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
    subtype=0x0, date=(0,0)
  ),
  kids=[
    StringFileInfo([
      StringTable(u'041104B0',[
        StringStruct(u'FileDescription', u'{APP_NAME}'),
        StringStruct(u'FileVersion',     u'{APP_VERSION}'),
        StringStruct(u'InternalName',    u'{APP_NAME}'),
        StringStruct(u'OriginalFilename',u'{APP_NAME}.exe'),
        StringStruct(u'ProductName',     u'{APP_NAME}'),
        StringStruct(u'ProductVersion',  u'{APP_VERSION}')])
    ]),
    VarFileInfo([VarStruct(u'Translation',[0x0411,1200])])
  ]
)
"""

with open('file_version_info.txt', 'w', encoding='utf-8') as f:
    f.write(content)

print(f"[gen_version_info] {APP_NAME} v{APP_VERSION} -> file_version_info.txt")
