"""Bundle Qt's own Traditional Chinese labels for standard file/dialog controls."""
from pathlib import Path
import shutil
from PySide6.QtCore import QLibraryInfo

root=Path(__file__).resolve().parents[1]
source=Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))/'qtbase_zh_TW.qm'
if not source.is_file():
    raise RuntimeError('Qt Traditional Chinese translation is missing: '+str(source))
destination=root/'assets/translations'/source.name
destination.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(source,destination)
print('Bundled Qt Traditional Chinese translation.')
