"""หน้า Dashboard หลัก (NiceGUI) + background polling loop + webhook endpoint

รันแอป:
    uv run spapp                        # โหมดปกติ
    uv run nicegui --reload dev_main.py # โหมดพัฒนา (reload อัตโนมัติ)

หน้าหลัก ๆ:
- /                Dashboard: สถานะร้าน แชทรอตอบ ออเดอร์ล่าสุด ประวัติแจ้งเตือน
- /oauth/callback  หน้ารับ code จาก Shopee หลังกดอนุญาต (แลกเป็น token แล้วเก็บ)
- POST /webhook/shopee  รับ push จาก Shopee (ใช้ได้เมื่อ deploy มี public HTTPS)
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
from datetime import timedelta

from fastapi import Request, Response
from nicegui import app, ui
from sqlmodel import select

from ..config import get_settings
from ..db import init_db, session
from ..models import ChatConversation, NotificationLog, ShopCredential, TrackedOrder, utcnow
from ..services.monitor import ORDER_STATUS_TH, ShopMonitor
from ..shopee import ShopeeApiError, ShopeeClient

log = logging.getLogger(__name__)
settings = get_settings()

# singleton เดียวกันนี้ใช้ทั้ง background loop และหน้า UI
monitor = ShopMonitor()


# ================================ helpers ================================


def _fmt_dt(dt) -> str:
    if not dt:
        return "-"
    if dt.tzinfo is not None:
        dt = dt.astimezone()  # UTC -> เวลาท้องถิ่นของเครื่อง
    return dt.strftime("%d %b %H:%M")


def _status_th(status: str) -> str:
    return ORDER_STATUS_TH.get(status, status)


def _chat_rows() -> list[dict]:
    with session() as s:
        rows = s.exec(
            select(ChatConversation).order_by(ChatConversation.updated_at.desc())  # type: ignore[union-attr]
        ).all()
    return [
        {
            "buyer": ("🔴 " if c.unread else "") + (c.buyer_username or "ผู้ซื้อ"),
            "snippet": c.last_message_snippet or "-",
            "time": _fmt_dt(c.last_message_at),
        }
        for c in rows[:20]
    ]


def _order_rows() -> list[dict]:
    with session() as s:
        rows = s.exec(
            select(TrackedOrder).order_by(TrackedOrder.updated_at.desc())  # type: ignore[union-attr]
        ).all()
    return [
        {
            "order_sn": o.order_sn,
            "buyer": o.buyer_username or "-",
            "status": _status_th(o.order_status),
            "created": _fmt_dt(o.create_time),
        }
        for o in rows[:20]
    ]


def _notification_rows() -> list[tuple[str, str, str]]:
    with session() as s:
        rows = s.exec(
            select(NotificationLog).order_by(NotificationLog.created_at.desc(), NotificationLog.id.desc())  # type: ignore[union-attr]
        ).all()
    return [(n.kind, n.title, _fmt_dt(n.created_at)) for n in rows[:20]]


# ================================ หน้าหลัก ================================


def connect_shop() -> None:
    """เปิดลิงก์ OAuth ของ Shopee ให้เจ้าของร้านกดอนุญาต"""
    if not settings.shopee_configured:
        ui.notify("ยังไม่ได้ตั้งค่า SHOPEE_PARTNER_ID / SHOPEE_PARTNER_KEY ใน .env", type="warning")
        return
    url = monitor.client.build_authorize_url(settings.shopee_redirect_url)
    ui.navigate.to(url, new_tab=True)


async def test_notify() -> None:
    """ทดสอบช่องทางแจ้งเตือน (Telegram + ประวัติใน Dashboard)"""
    await monitor.notifier.notify(
        "system", "🔔 ทดสอบการแจ้งเตือน", "หากได้รับข้อความนี้บน Telegram แสดงว่าตั้งค่าถูกต้อง"
    )
    ui.notify("ส่งการทดสอบแล้ว — ดูที่ Telegram และประวัติการแจ้งเตือน", type="positive")


@ui.page("/")
def dashboard() -> None:
    with ui.column().classes("max-w-5xl mx-auto p-4 gap-4 w-full"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("🛍️ Shopee Monitor").classes("text-2xl font-bold")
            poll_label = ui.label().classes("text-sm text-gray-500")

        # ---------- การเชื่อมต่อ ----------
        with ui.card().classes("w-full"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("การเชื่อมต่อร้าน").classes("text-lg font-semibold")
                with ui.row().classes("gap-2"):
                    ui.button("🔔 ทดสอบแจ้งเตือน", on_click=test_notify).props("outline")
                    ui.button("🔗 เชื่อมต่อร้าน Shopee", on_click=connect_shop).props("color=primary")

            config_hints = ui.label().classes("text-xs text-gray-500")
            shop_container = ui.column().classes("w-full gap-1")

        # ---------- การ์ดสรุป ----------
        with ui.row().classes("w-full gap-4 items-stretch"):
            with ui.card().classes("flex-1"):
                ui.label("💬 แชทรอตอบ").classes("text-gray-500 text-sm")
                unread_label = ui.label("-").classes("text-3xl font-bold")
            with ui.card().classes("flex-1"):
                ui.label("🛒 ออเดอร์ใหม่ (24 ชม.)").classes("text-gray-500 text-sm")
                orders_label = ui.label("-").classes("text-3xl font-bold")
            with ui.card().classes("flex-1"):
                ui.label("🔔 การแจ้งเตือนวันนี้").classes("text-gray-500 text-sm")
                notif_label = ui.label("-").classes("text-3xl font-bold")

        # ---------- ตารางแชท ----------
        with ui.card().classes("w-full"):
            ui.label("💬 แชทล่าสุด (🔴 = ยังไม่ได้อ่าน)").classes("text-lg font-semibold")
            chat_table = ui.table(
                columns=[
                    {"name": "buyer", "label": "ผู้ซื้อ", "field": "buyer", "align": "left"},
                    {"name": "snippet", "label": "ข้อความล่าสุด", "field": "snippet", "align": "left"},
                    {"name": "time", "label": "เวลา", "field": "time", "align": "left"},
                ],
                rows=[],
                row_key="buyer",
            ).classes("w-full").props("flat dense")

        # ---------- ตารางออเดอร์ ----------
        with ui.card().classes("w-full"):
            ui.label("🛒 ออเดอร์ล่าสุด").classes("text-lg font-semibold")
            order_table = ui.table(
                columns=[
                    {"name": "order_sn", "label": "เลขออเดอร์", "field": "order_sn", "align": "left"},
                    {"name": "buyer", "label": "ผู้ซื้อ", "field": "buyer", "align": "left"},
                    {"name": "status", "label": "สถานะ", "field": "status", "align": "left"},
                    {"name": "created", "label": "สร้างเมื่อ", "field": "created", "align": "left"},
                ],
                rows=[],
                row_key="order_sn",
            ).classes("w-full").props("flat dense")

        # ---------- ประวัติการแจ้งเตือน ----------
        with ui.card().classes("w-full"):
            ui.label("🔔 ประวัติการแจ้งเตือน").classes("text-lg font-semibold")
            notif_container = ui.column().classes("w-full gap-1")

    def refresh() -> None:
        """ดึงข้อมูลใหม่จากฐานข้อมูล (background loop เป็นคนเขียนลง DB)"""
        try:
            # สถานะ poll
            if monitor.last_error:
                poll_label.text = f"⚠️ {monitor.last_error}"
                poll_label.classes(replace="text-sm text-red-500")
            elif monitor.last_poll_at:
                local_time = monitor.last_poll_at.astimezone()
                poll_label.text = f"อัปเดตล่าสุด {local_time:%H:%M:%S} · ทุก {settings.poll_interval_seconds} วิ"
                poll_label.classes(replace="text-sm text-gray-500")
            else:
                poll_label.text = "ยังไม่เริ่มการตรวจสอบ..."
                poll_label.classes(replace="text-sm text-gray-400")

            # การตั้งค่า
            hints = []
            hints.append("✅ Shopee API" if settings.shopee_configured else "❌ ยังไม่ตั้งค่า Shopee (.env)")
            hints.append("✅ Telegram" if settings.telegram_configured else "— Telegram ยังไม่ได้ตั้งค่า")
            config_hints.text = "   ·   ".join(hints)

            # ร้านที่เชื่อมต่อ
            with session() as s:
                creds = s.exec(select(ShopCredential).order_by(ShopCredential.shop_id)).all()
                cutoff = utcnow() - timedelta(hours=settings.order_lookback_hours)
                unread = s.exec(select(ChatConversation).where(ChatConversation.unread == True)).all()  # noqa: E712
                new_orders = s.exec(
                    select(TrackedOrder).where(TrackedOrder.create_time >= cutoff)  # type: ignore[union-attr]
                ).all()
                midnight = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                today_notifs = s.exec(
                    select(NotificationLog).where(NotificationLog.created_at >= midnight)  # type: ignore[union-attr]
                ).all()

            shop_container.clear()
            if creds:
                with shop_container:
                    for c in creds:
                        expire = _fmt_dt(c.access_token_expire_at)
                        state = "✅" if not c.token_expired_or_unknown else "⚠️ ต้องเชื่อมต่อใหม่"
                        ui.label(f"{state} ร้าน {c.shop_name or c.shop_id} (ID {c.shop_id}) — token ถึง {expire}").classes(
                            "text-sm text-gray-700"
                        )
            else:
                with shop_container:
                    ui.label("ยังไม่มีร้านเชื่อมต่อ — กดปุ่ม “เชื่อมต่อร้าน Shopee” แล้วเข้าสู่ระบบด้วยบัญชีเจ้าของร้าน").classes(
                        "text-sm text-gray-500"
                    )

            unread_label.text = str(sum(c.unread_count for c in unread))
            orders_label.text = str(len(new_orders))
            notif_label.text = str(len(today_notifs))

            chat_table.rows = _chat_rows()
            order_table.rows = _order_rows()

            notif_container.clear()
            with notif_container:
                for kind, title, created in _notification_rows():
                    icon = {"chat": "💬", "order": "🛒"}.get(kind, "ℹ️")
                    ui.label(f"{created} · {icon} {title}").classes("text-sm text-gray-700")
        except Exception:
            log.exception("refresh dashboard ล้มเหลว")

    refresh()
    ui.timer(5.0, refresh)


# ================================ OAuth callback ================================


@ui.page("/oauth/callback")
async def oauth_callback(
    code: str = "",
    shop_id: int = 0,
    main_account_id: int = 0,
    error: str = "",
    error_description: str = "",
) -> None:
    """Shopee พาผู้ใช้กลับมาที่นี่พร้อม code + shop_id หลังกดอนุญาต

    (code อายุ 10 นาที ใช้ได้ครั้งเดียว — ถ้า refresh หน้านี้ซ้ำจะ error ให้กดเชื่อมต่อใหม่)
    """
    with ui.column().classes("max-w-xl mx-auto p-6 gap-2"):
        if error or not code or not shop_id:
            ui.label("❌ การเชื่อมต่อร้านไม่สำเร็จ").classes("text-xl font-bold")
            ui.label(f"{error or 'ไม่พบ code / shop_id'} {error_description}").classes("text-sm text-gray-600")
            ui.link("← กลับหน้าหลัก", "/")
            return

        client = ShopeeClient()
        try:
            data = await client.get_tokens(code, shop_id)
            shop_name = ""
            try:
                info = await client.get_shop_info(shop_id, data["access_token"])
                shop_name = str((info.get("response") or {}).get("shop_name") or "")
            except ShopeeApiError:
                log.debug("ดึง shop_name ไม่สำเร็จ — ข้าม")

            expire_at = utcnow() + timedelta(seconds=data["expire_in"])
            with session() as s:
                row = s.get(ShopCredential, shop_id)
                if row is None:
                    row = ShopCredential(shop_id=shop_id)
                    s.add(row)
                row.shop_name = shop_name or row.shop_name
                row.access_token = data["access_token"]
                row.refresh_token = data["refresh_token"]
                row.access_token_expire_at = expire_at
                row.updated_at = utcnow()
                s.add(row)
                s.commit()

            await monitor.notifier.notify(
                "system",
                f"✅ เชื่อมต่อร้าน {shop_name or shop_id} สำเร็จ",
                "เริ่มเฝ้าระวังแชทและออเดอร์แล้ว",
            )
            ui.label(f"✅ เชื่อมต่อร้าน {shop_name or shop_id} สำเร็จ").classes("text-xl font-bold text-green-600")
            ui.label(f"token หมดอายุ {_fmt_dt(expire_at)} (ระบบต่ออายุให้อัตโนมัติ)").classes(
                "text-sm text-gray-600"
            )
        except ShopeeApiError as exc:
            ui.label("❌ แลก token ไม่สำเร็จ").classes("text-xl font-bold text-red-600")
            ui.label(str(exc)).classes("text-sm text-gray-600")
            ui.label("code ใช้ได้ครั้งเดียวและอายุ 10 นาที — กดปุ่มเชื่อมต่อร้านใหม่อีกครั้ง").classes(
                "text-xs text-gray-500"
            )
        finally:
            await client.aclose()
        ui.link("← กลับหน้าหลัก", "/")


# ================================ Webhook (ระยะที่ 2) ================================


@app.post("/webhook/shopee")
async def shopee_webhook(request: Request) -> Response:
    """รับ push จาก Shopee — ใช้ได้เมื่อ deploy แอปให้มี public HTTPS แล้ว

    - ตรวจลายเซ็นใน header ``Authorization: SHA256 <hmac>``
    - push type ที่น่าสนใจ: 3 = ออเดอร์เปลี่ยนสถานะ, 10 = webchat (ข้อความแชทใหม่)
    - ตั้งค่า callback ได้ผ่าน ShopeeClient.set_app_push_config() หรือใน Console
    """
    raw = await request.body()
    if not settings.shopee_configured:
        return Response(status_code=503)
    signature = request.headers.get("authorization", "").removeprefix("SHA256").strip()
    expected = hmac.new(settings.shopee_partner_key.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return Response(status_code=401)

    try:
        event = json.loads(raw)
        code = int(event.get("code") or 0)
        data = json.loads(event.get("data") or "{}")
    except (TypeError, ValueError):
        return Response(status_code=400)

    if code == 3:
        order_sn = data.get("order_sn") or ""
        status = data.get("order_status") or ""
        await monitor.notifier.notify("order", f"📦 ออเดอร์ {order_sn} เปลี่ยนสถานะ", _status_th(status))
    elif code == 10:
        await monitor.notifier.notify("chat", "💬 ข้อความแชทใหม่", str(data)[:300])
    elif code in (1, 2):
        await monitor.notifier.notify("system", "การอนุญาตร้านมีการเปลี่ยนแปลง", str(data)[:300])
    return Response(status_code=200)


# ================================ background loop ================================


@app.on_startup
async def start_monitor() -> None:
    """เริ่ม background loop ตรวจสอบร้านทุก settings.poll_interval_seconds วินาที"""

    async def loop() -> None:
        while True:
            try:
                await monitor.poll_once()
            except Exception:
                log.exception("poll cycle ล้มเหลว")
            await asyncio.sleep(settings.poll_interval_seconds)

    asyncio.create_task(loop())


# ================================ entry point ================================


def run() -> None:
    """จุดเริ่มรันแอป (ถูกเรียกจากคำสั่ง `uv run spapp`)"""
    logging.basicConfig(
        level=os.environ.get("SPAPP_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    init_db()
    ui.run(
        host=settings.host,
        port=settings.port,
        title="Shopee Monitor",
        favicon="🛍️",
        reload=False,
        show=os.environ.get("SPAPP_NO_BROWSER") != "1",
    )


if __name__ in {"__main__", "__mp_main__"}:
    run()
