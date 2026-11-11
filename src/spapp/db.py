"""การเชื่อมต่อฐานข้อมูล SQLite (SQLModel / SQLAlchemy)

- ไฟล์ฐานข้อมูลเก็บที่ `data/spapp.db` ที่รากโปรเจกต์ (สร้างโฟลเดอร์ให้อัตโนมัติ)
- เปิดโหมด WAL เพื่อให้อ่าน/เขียนพร้อมกันได้ (background poller + UI)
"""

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlmodel import Session, SQLModel

from . import models  # noqa: F401 — import เพื่อให้ SQLModel.metadata รู้จักทุกตาราง
from .config import get_settings

# รากโปรเจกต์ (D:\spapp) — db.py อยู่ที่ src/spapp/db.py
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _database_url() -> str:
    url = get_settings().database_url
    if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
        raw_path = Path(url[len("sqlite:///"):])
        # path แบบ relative ให้ตีความเทียบกับรากโปรเจกต์ ไม่ขึ้นกับ cwd ที่ใช้รันคำสั่ง
        # เช่น "sqlite:///data/spapp.db" -> D:\spapp\data\spapp.db
        if not raw_path.is_absolute():
            raw_path = PROJECT_ROOT / raw_path
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{raw_path.as_posix()}"
    return url


engine = create_engine(
    _database_url(),
    echo=False,
    connect_args={"check_same_thread": False},  # SQLite + หลาย thread (NiceGUI)
)


if engine.url.drivername.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def init_db() -> None:
    """สร้างตารางที่ยังไม่มี (เรียกครั้งเดียวตอน startup)"""
    SQLModel.metadata.create_all(engine)


def session() -> Session:
    """สร้าง session ใหม่ ใช้แบบ context manager: `with session() as s:`"""
    return Session(engine)
