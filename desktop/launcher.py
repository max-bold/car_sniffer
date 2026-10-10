"""PyInstaller entry point (absolute import survives freezing)."""
import os
from pathlib import Path
import traceback

try:
    from desktop.__main__ import main
    main()
except Exception:
    log = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'CarSniffer' / 'startup-error.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(traceback.format_exc(), encoding='utf-8')
    raise
