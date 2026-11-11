"""ตัวส่งแจ้งเตือน — เก็บลงฐานข้อมูลทุกครั้ง + ส่ง Telegram (ถ้าตั้งค่าไว้)

ช่องทางอื่น ๆ (เช่น LINE Messaging API, เสียงแจ้งเตือนบนเครื่อง) ให้เพิ่มเป็น
เมธอดใหม่ในคลาส Notifier ตามรูปแบบเดียวกัน
"""

import logging

import httpx

from ..config import get_settings
from ..db import session
from ..models import NotificationLog

log = logging.getLogger(__name__)


class Notifier:
    """แจ้งเตือนหลายช่องทางจากที่เดียว"""

    async def notify(self, kind: str, title: str, body: str = "") -> None:
        """ส่งการแจ้งเตือนหนึ่งครั้ง

        kind: "chat" | "order" | "system"
        """
        self._save_log(kind, title, body)
        await self._send_telegram(title, body)

    def _save_log(self, kind: str, title: str, body: str) -> None:
        try:
            with session() as s:
                s.add(NotificationLog(kind=kind, title=title, body=body))
                s.commit()
        except Exception:
            log.exception("บันทึก NotificationLog ไม่สำเร็จ")

    async def _send_telegram(self, title: str, body: str) -> None:
        settings = get_settings()
        if not settings.telegram_configured:
            return
        text = f"🔔 {title}"
        if body:
            text += f"\n{body}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                    json={
                        "chat_id": settings.telegram_chat_id,
                        "text": text,
                    },
                )
                resp.raise_for_status()
        except Exception:
            log.exception("ส่งข้อความ Telegram ไม่สำเร็จ (ตรวจ token/chat_id)")
