# -*- coding: utf-8 -*-
"""生成 PyInstaller 版本资源文件（exe 属性页显示的版本信息）。

用法：python assets/build_version_file.py <版本号> <输出路径>
由 build_exe.ps1 在打包时调用；单独运行亦可。
"""
import sys


def main() -> int:
    ver, out = sys.argv[1], sys.argv[2]
    parts = (ver.split(".") + ["0", "0", "0", "0"])[:4]
    v4 = ", ".join(parts)
    text = f'''VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v4}), prodvers=({v4}),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable("080404B0", [
        StringStruct("CompanyName", ""),
        StringStruct("FileDescription", "收藏夹遗忘曲线 · B站版"),
        StringStruct("FileVersion", "{ver}"),
        StringStruct("LegalCopyright", ""),
        StringStruct("OriginalFilename", "收藏夹遗忘曲线.exe"),
        StringStruct("ProductName", "收藏夹遗忘曲线"),
        StringStruct("ProductVersion", "{ver}"),
      ])
    ]),
    VarFileInfo([VarStruct("Translation", [2052, 1200])])
  ]
)
'''
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
