"""Copy installed package license notices for binary redistribution."""
import importlib.metadata
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1]
output = root / "licenses" / "dependencies"
output.mkdir(parents=True, exist_ok=True)
for package in ("PySide6-Essentials", "shiboken6", "requests", "urllib3", "certifi", "charset-normalizer", "idna", "defusedxml", "pyinstaller"):
    distribution = importlib.metadata.distribution(package)
    for file in distribution.files or []:
        if ("licenses" in file.parts or any(word in file.name.lower() for word in ("license", "copying", "notice"))) and file.suffix.lower() not in (".py", ".pyc", ".h", ".so", ".dll"):
            source = Path(distribution.locate_file(file))
            if source.is_file():
                target = output / package / file.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.is_file():
    shutil.copyfile(python_license, output / "Python-LICENSE.txt")
print("Collected dependency notices in", output)
