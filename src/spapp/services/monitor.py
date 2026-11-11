"""ตัวเฝ้าระวังกิจกรรมร้าน (polling loop)

หลักการทำงาน (รอบละ settings.poll_interval_seconds วินาที ต่อร้าน):
1. ดึง access_token ที่ยังไม่หมดอายุ (refresh ล่วงหน้าก่อนหมดอายุ 10 นาที)
2. แชท: เช็คจำนวนห้องแชทที่ยังไม่ได้อ่าน → ดึงรายชื่อห้องแชทล่าสุดมาเทียบ
   ว่ามี "ข้อความใหม่" ที่ยังไม่เคยแจ้งเตือน → แจ้งเตือน
3. ออเดอร์: ดึงออเดอร์ย้อนหลัง N ชั่วโมง → ออเดอร์ใหม่หรือสถานะเปลี่ยน → แจ้งเตือน

การ dedup: ใช้ตาราง ChatConversation.last_seen_marker และ TrackedOrder.order_status
เทียบกับรอบก่อน ทำให้แจ้งเตือนเฉพาะความเปลี่ยนแปลงใหม่จริง ๆ (ไม่ spam ทุกรอบ poll)

หมายเหตุ: ชื่อ field ใน payload ของ Chat API บางตัวไม่ได้ระบุชัดเจนในเอกสารสาธารณะ
โค้ดจึงอ่านแบบยืดหยุ่นหลายชื่อ — เปิด debug log (SPAPP_LOG_LEVEL=DEBUG) เพื่อดู
payload จริงแล้วปรับ _process_conversation() ให้ตรงได้
"""

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from ..config import get_settings
from ..db import session
from ..models import ChatConversation, ShopCredential, TrackedOrder, utcnow
from ..shopee import ShopeeApiError, ShopeeClient
from .notify import Notifier

log = logging.getLogger(__name__)

# แปลสถานะออเดอร์เป็นภาษาไทย (ชื่อสถานะตามเอกสาร Shopee v2)
ORDER_STATUS_TH = {
    "UNPAID": "ยังไม่ชำระเงิน",
    "TO_CONFIRM_RECEIVE": "ชำระแล้ว รอส่งของ",
    "TO_DELIVER": "รอจัดส่ง",
    "SHIPPED": "จัดส่งแล้ว",
    "TO_RETURN": "อยู่ระหว่างคืนสินค้า",
    "COMPLETED": "สำเร็จ",
    "IN_CANCEL": "กำลังยกเลิก",
    "CANCELLED": "ยกเลิกแล้ว",
}


def _status_th(status: str) -> str:
    return ORDER_STATUS_TH.get(status, status)


class ShopMonitor:
    """state เดียวกันนี้ถูกใช้ทั้ง background loop และหน้า UI"""

    def __init__(self, client: ShopeeClient | None = None, notifier: Notifier | None = None) -> None:
        self.client = client or ShopeeClient()
        self.notifier = notifier or Notifier()
        self.last_poll_at: datetime | None = None
        self.last_error: str | None = None

    # ---------- token ----------

    async def ensure_access_token(self, cred: ShopCredential) -> str | None:
        """คืน access_token ที่ยังใช้ได้ — refresh อัตโนมัติก่อนหมดอายุ 10 นาที"""
        expire_at = cred.access_token_expire_at
        needs_refresh = (
            not cred.access_token
            or expire_at is None
            or expire_at <= utcnow() + timedelta(minutes=10)
        )
        if not needs_refresh:
            return cred.access_token
        if not cred.refresh_token:
            return None

        data = await self.client.refresh_tokens(cred.refresh_token, cred.shop_id)
        new_expire_at = utcnow() + timedelta(seconds=data["expire_in"])
        with session() as s:
            row = s.get(ShopCredential, cred.shop_id)
            if row is None:
                return None
            row.access_token = data["access_token"]
            row.refresh_token = data["refresh_token"]
            row.access_token_expire_at = new_expire_at
            row.updated_at = utcnow()
            s.add(row)
            s.commit()
        log.info("refresh token ร้าน %s สำเร็จ (หมดอายุ %s)", cred.shop_id, new_expire_at)
        return data["access_token"]

    # ---------- วงจรหลัก ----------

    async def poll_once(self) -> None:
        """รันหนึ่งรอบของการตรวจสอบทุกร้านที่เชื่อมต่อไว้"""
        settings = get_settings()
        if not settings.shopee_configured:
            self.last_error = "ยังไม่ตั้งค่า SHOPEE_PARTNER_ID / SHOPEE_PARTNER_KEY ใน .env"
            return

        with session() as s:
            creds = s.exec(select(ShopCredential)).all()

        had_error = False
        for cred in creds:
            try:
                access_token = await self.ensure_access_token(cred)
                if not access_token:
                    await self.notifier.notify(
                        "system",
                        f"⚠️ ร้าน {cred.shop_name or cred.shop_id} ต้องเชื่อมต่อใหม่",
                        "refresh_token หมดอายุแล้ว — เปิด Dashboard แล้วกดปุ่มเชื่อมต่อร้านอีกครั้ง",
                    )
                    had_error = True
                    continue
                await self.poll_chat(cred, access_token)
                await self.poll_orders(cred, access_token)
            except ShopeeApiError as exc:
                had_error = True
                self.last_error = str(exc)
                log.warning("Shopee API error (ร้าน %s): %s", cred.shop_id, exc)
            except Exception:
                had_error = True
                self.last_error = "เกิดข้อผิดพลาดบางอย่าง — ดู log ประกอบ"
                log.exception("poll ร้าน %s ล้มเหลว", cred.shop_id)

        if not had_error:
            self.last_error = None
        self.last_poll_at = utcnow()

    # ---------- แชท ----------

    async def poll_chat(self, cred: ShopCredential, access_token: str) -> None:
        unread_total = await self.client.get_unread_conversation_count(cred.shop_id, access_token)
        if unread_total <= 0:
            return

        payload = await self.client.get_conversation_list(cred.shop_id, access_token, page_size=20)
        conversations = (payload.get("response") or {}).get("conversation_list") or []

        if not conversations:
            # มี unread แต่ดึงรายชื่อไม่ได้ — ยังแจ้งเตือนคร่าว ๆ ให้รู้ตัว
            await self.notifier.notify(
                "chat",
                f"💬 มีแชทที่ยังไม่ได้อ่าน {unread_total} รายการ",
                "เข้าไปตอบใน Shopee Seller Centre / แอป Shopee",
            )
            return

        for conv in conversations:
            await self._process_conversation(cred, conv)

    async def _process_conversation(self, cred: ShopCredential, conv: dict) -> None:
        conv_id = str(conv.get("conversation_id") or "")
        if not conv_id:
            return

        last_message = conv.get("last_message") or {}
        marker = str(
            conv.get("last_message_id")
            or last_message.get("message_id")
            or last_message.get("id")
            or ""
        )
        snippet = self._snippet(conv)
        buyer = str(
            conv.get("buyer_username")
            or conv.get("user_name")
            or conv.get("from_name")
            or "ผู้ซื้อ"
        )
        unread = int(conv.get("unread") or conv.get("unread_count") or 0)
        last_message_at = self._to_datetime(
            conv.get("last_message_time") or last_message.get("create_time")
        )

        # marker ใช้เทียบว่า "ข้อความล่าสุด" เปลี่ยนไปจากที่เคยเห็นไหม
        if not marker:
            marker = f"{last_message_at}|{snippet}"

        with session() as s:
            row = s.get(ChatConversation, conv_id)
            already_seen = row is not None and row.last_seen_marker == marker
            if row is None:
                row = ChatConversation(conversation_id=conv_id, shop_id=cred.shop_id)
                s.add(row)
            row.buyer_username = buyer
            row.unread = unread > 0
            row.unread_count = unread
            row.last_message_snippet = snippet
            row.last_message_at = last_message_at
            row.last_seen_marker = marker
            row.updated_at = utcnow()
            s.add(row)
            s.commit()

        if unread > 0 and not already_seen:
            title = f"💬 แชทใหม่จาก {buyer}"
            body = snippet or "มีข้อความที่ยังไม่ได้อ่าน — เข้าไปตอบใน Shopee"
            await self.notifier.notify("chat", title, body)

    @staticmethod
    def _snippet(conv: dict) -> str:
        """ดึงข้อความตัวอักษรจาก last_message แบบยืดหยุ่น (รองรับหลายรูปแบบ payload)"""
        content = (conv.get("last_message") or {}).get("content") or {}
        if isinstance(content, dict):
            return str(content.get("text") or content.get("content") or "").strip()
        if isinstance(content, str):
            return content.strip()
        return str(conv.get("last_message") or "").strip()[:120]

    @staticmethod
    def _to_datetime(value) -> datetime | None:
        """แปลง timestamp ของ Shopee (วินาที หรือ nanosecond) เป็น datetime"""
        if not value:
            return None
        try:
            ts = int(value)
        except (TypeError, ValueError):
            return None
        if ts > 10**15:  # nanosecond
            ts //= 10**9
        elif ts > 10**12:  # millisecond
            ts //= 10**3
        try:
            # เก็บเป็น UTC (timezone-aware) แล้วแปลงเป็นเวลาท้องถิ่นตอนแสดงผล
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OSError, ValueError):
            return None

    # ---------- ออเดอร์ ----------

    async def poll_orders(self, cred: ShopCredential, access_token: str) -> None:
        settings = get_settings()
        now = int(time.time())
        time_from = now - settings.order_lookback_hours * 3600

        orders: list[dict] = []
        cursor = ""
        # กันลูปยาว: จำกัดจำนวนหน้าที่ดึงต่อรอบ
        for _ in range(10):
            payload = await self.client.get_order_list(
                cred.shop_id, access_token, time_from=time_from, time_to=now, cursor=cursor
            )
            response = payload.get("response") or {}
            batch = response.get("order_list") or []
            orders.extend(batch)
            info = response.get("info") or {}
            cursor = info.get("next_cursor") or ""
            if not cursor or not info.get("more", False):
                break

        for order in orders:
            await self._process_order(cred, order)

    async def _process_order(self, cred: ShopCredential, order: dict) -> None:
        order_sn = str(order.get("order_sn") or "")
        if not order_sn:
            return
        status = str(order.get("order_status") or "")
        buyer = order.get("buyer_username") or "ผู้ซื้อ"
        create_time = self._to_datetime(order.get("create_time"))

        with session() as s:
            row = s.get(TrackedOrder, order_sn)
            previous_status = row.order_status if row is not None else None
            if row is None:
                row = TrackedOrder(order_sn=order_sn, shop_id=cred.shop_id)
                s.add(row)
            row.order_status = status
            row.buyer_username = buyer
            row.create_time = create_time
            row.updated_at = utcnow()
            s.add(row)
            s.commit()

        if previous_status is None:
            await self.notifier.notify(
                "order",
                f"🛒 ออเดอร์ใหม่ {order_sn}",
                f"ผู้ซื้อ: {buyer}\nสถานะ: {_status_th(status)}",
            )
        elif status != previous_status:
            await self.notifier.notify(
                "order",
                f"📦 ออเดอร์ {order_sn} เปลี่ยนสถานะ",
                f"{_status_th(previous_status)} → {_status_th(status)}",
            )
