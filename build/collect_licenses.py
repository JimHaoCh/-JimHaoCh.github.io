"""Copy license material included in the installed build dependencies."""
from __future__ import annotations

import importlib.metadata as metadata
import shutil
import sys
from pathlib import Path, PurePosixPath


def main(destination: str) -> None:
    dest = Path(destination)
    dest.mkdir(parents=True, exist_ok=True)
    packages = ("PySide6", "PySide6-Essentials", "PySide6-Addons", "shiboken6", "pyserial", "PyInstaller")
    for name in packages:
        dist = metadata.distribution(name)
        copied = 0
        for entry in dist.files or ():
            rel = PurePosixPath(str(entry).replace("\\", "/"))
            if rel.is_absolute() or ".." in rel.parts:
                continue
            parts = [part.lower() for part in rel.parts]
            base = rel.name.lower()
            is_notice = base.startswith(("license", "licence", "copying", "notice"))
            in_notice_dir = any(part in ("licenses", "licences") for part in parts)
            if not (is_notice or in_notice_dir):
                continue
            source = Path(dist.locate_file(entry))
            if source.is_file() and source.stat().st_size <= 2_000_000:
                target = dest / name / Path(*rel.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                copied += 1
        print(f"{name} {dist.version}: collected {copied} license/notice files")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        target = dest / "Python" / "LICENSE.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(python_license, target)
    for name in ("LGPL-3.0.txt", "GPL-3.0.txt", "GPL-2.0.txt"):
        source = Path("third_party_license_texts") / name
        if source.is_file():
            shutil.copy2(source, dest / name)


if __name__ == "__main__":
    main(sys.argv[1])
