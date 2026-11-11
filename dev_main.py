"""จุดรันสำหรับโหมดพัฒนา (auto-reload)

คำสั่ง: uv run nicegui --reload dev_main.py
"""

from spapp.ui.main import run

if __name__ in {"__main__", "__mp_main__"}:
    run()
