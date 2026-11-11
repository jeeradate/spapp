"""โมเดลฐานข้อมูล (SQLModel)

ตารางหลัก 4 ตัว:
- ShopCredential   token ของร้านที่อนุญาตแอปแล้ว
- ChatConversation สถานะล่าสุดของห้องแชท (ใช้เทียบว่ามีข้อความใหม่หรือไม่)
- TrackedOrder     ออเดอร์ที่รู้จักแล้ว (เทียบสถานะเพื่อแจ้งเตือนความเปลี่ยนแปลง)
- NotificationLog  ประวัติการแจ้งเตือนทั้งหมด แสดงบน Dashboard
"""

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """เวลาปัจจุบันแบบ UTC (timezone-aware) — SQLModel เก็นลงฐานข้อมูลเป็น UTC เสมอ"""
    return datetime.now(timezone.utc)


class ShopCredential(SQLModel, table=True):
    """Token ของร้านที่ authorize แอปของเราแล้ว (1 ร้าน = 1 แถว)

    access_token อายุ 4 ชม. / refresh_token อายุ 30 วัน — ตัว monitor จะ refresh ให้อัตโนมัติ
    """
    shop_id: int = Field(primary_key=True)
    shop_name: str | None = None
    access_token: str = ""
    refresh_token: str = ""
    access_token_expire_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def token_expired_or_unknown(self) -> bool:
        if self.access_token_expire_at is None:
            return True
        return utcnow() >= self.access_token_expire_at


class ChatConversation(SQLModel, table=True):
    """สถานะล่าสุดของห้องแชท เพื่อ dedup การแจ้งเตือน (ไม่ spam ทุกรอบ poll)"""

    conversation_id: str = Field(primary_key=True)
    shop_id: int = Field(index=True)
    buyer_username: str | None = None
    unread: bool = False
    unread_count: int = 0
    last_message_snippet: str = ""
    last_message_at: datetime | None = None
    # ตัวชี้วัด "ข้อความล่าสุดที่เห็นแล้ว" (message_id หรือ timestamp+snippet)
    last_seen_marker: str | None = None
    updated_at: datetime = Field(default_factory=utcnow)


class TrackedOrder(SQLModel, table=True):
    """ออเดอร์ที่แอปรู้จักแล้ว — เทียบสถานะทุกรอบเพื่อหาออเดอร์ใหม่/เปลี่ยนสถานะ"""

    order_sn: str = Field(primary_key=True)
    shop_id: int = Field(index=True)
    order_status: str = ""
    buyer_username: str | None = None
    create_time: datetime | None = None
    updated_at: datetime = Field(default_factory=utcnow)


class NotificationLog(SQLModel, table=True):
    """ประวัติการแจ้งเตือน (kind: 'chat' | 'order' | 'system')"""

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    title: str = ""
    body: str = ""
    created_at: datetime = Field(default_factory=utcnow, index=True)
