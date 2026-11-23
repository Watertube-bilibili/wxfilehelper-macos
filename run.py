import os
import sys
import traceback
from pathlib import Path


if __name__ == "__main__":
    report = os.environ.get("WXFILEHELPER_SMOKE_REPORT") if "--smoke-test" in sys.argv else None
    try:
        from wxfilehelper.app import main
        code = main()
    except Exception:
        if not report:
            raise
        Path(report).write_text(traceback.format_exc(), encoding="utf-8")
        code = 1
    else:
        if report:
            Path(report).write_text("OK\n" if code == 0 else f"Exit {code}\n", encoding="utf-8")
    raise SystemExit(code)
