"""Shopee Open Platform API v2 — async client

แหล่งอ้างอิงหลัก:
- Developer guide: https://open.shopee.com/developer-guide/17
- API list:        https://open.shopee.com/documents/v2/

การ sign คำขอ (สำคัญที่สุด):
    sign = HMAC-SHA256(partner_key, partner_id + api_path + timestamp + access_token + shop_id)
    - API แบบ public (auth/token):   ไม่มี access_token / shop_id ต่อท้าย
    - API ระดับร้าน (shop level):     มี access_token + shop_id ต่อท้าย
    - API ระดับ merchant:            มี access_token + merchant_id ต่อท้าย
    ค่าที่ได้ส่งไปเป็น query parameter ชื่อ "sign" พร้อม partner_id, timestamp

Host:
- production: https://partner.shopeemobile.com
- sandbox:    https://partner.test-stable.shopeemobile.com

อายุของข้อมูลสำคัญ (จากเอกสาร Shopee):
- timestamp/sign: อายุประมาณ 5 นาที (เครื่องต้องตั้งเวลาถูกต้อง)
- authorization code: 10 นาที ใช้ได้ครั้งเดียว
- access_token: 4 ชั่วโมง
- refresh_token: 30 วัน

หมายเหตุเรื่องสิทธิ์:
- Order API ใช้ได้ปกติหลังสร้าง app ผ่านอนุมัติ
- Chat API (sellerchat/*) เป็น whitelist-only ต้องยื่นขอสิทธิ์เพิ่มใน Console
  (ดู README หัวข้อ "การขอสิทธิ์ Chat API")
"""

import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from ..config import get_settings

log = logging.getLogger(__name__)

# ---------- ตำแหน่ง endpoint ที่แอปใช้ ----------
PATH_AUTH_PARTNER = "/api/v2/shop/auth_partner"
PATH_TOKEN_GET = "/api/v2/auth/token/get"
PATH_ACCESS_TOKEN_GET = "/api/v2/auth/access_token/get"
PATH_GET_SHOP_INFO = "/api/v2/shop/get_shop_info"

PATH_GET_ORDER_LIST = "/api/v2/order/get_order_list"
PATH_GET_ORDER_DETAIL = "/api/v2/order/get_order_detail"

PATH_GET_UNREAD_CONVERSATION_COUNT = "/api/v2/sellerchat/get_unread_conversation_count"
PATH_GET_CONVERSATION_LIST = "/api/v2/sellerchat/get_conversation_list"
PATH_GET_MESSAGE = "/api/v2/sellerchat/get_message"
PATH_SEND_MESSAGE = "/api/v2/sellerchat/send_message"

PATH_SET_APP_PUSH_CONFIG = "/api/v2/public/set_app_push_config"


def _pick(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """หาค่าจาก payload โดยลองหลายชื่อ key (Shopee บาง endpoint ใส่ข้อมูลที่
    root ของ response บาง endpoint ซ่อนใต้ 'response')"""
    for key in keys:
        if key in payload:
            return payload[key]
    response = payload.get("response") or {}
    for key in keys:
        if key in response:
            return response[key]
    return default


class ShopeeApiError(RuntimeError):
    """Shopee ตอบกลับมาเป็น error (หรือ HTTP ไม่ใช่ 200)"""

    def __init__(self, path: str, error: str, message: str, status_code: int | None = None):
        self.path = path
        self.error = error
        self.message = message
        self.status_code = status_code
        super().__init__(f"Shopee API error [{error}] {message} (path={path}, http={status_code})")


class ShopeeClient:
    """async client ตัวเดียวใช้ทั้งระบบ — สร้างครั้งเดียวแล้ว reuse ได้

    ตัวอย่าง::

        client = ShopeeClient()
        tokens = await client.get_tokens(code, shop_id)
        orders = await client.get_order_list(shop_id, tokens["access_token"],
                                             time_from=..., time_to=...)
    """

    def __init__(
        self,
        partner_id: int | None = None,
        partner_key: str | None = None,
        host: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        settings = get_settings()
        self.partner_id = int(partner_id or settings.shopee_partner_id)
        self.partner_key = partner_key or settings.shopee_partner_key
        self.host = host or settings.shopee_api_host
        self._http = httpx.AsyncClient(base_url=self.host, timeout=timeout)

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---------- การ sign ----------

    def sign(
        self,
        path: str,
        timestamp: int,
        access_token: str = "",
        shop_id: int | None = None,
        merchant_id: int | None = None,
    ) -> str:
        base = f"{self.partner_id}{path}{timestamp}{access_token}"
        if shop_id is not None:
            base += str(shop_id)
        if merchant_id is not None:
            base += str(merchant_id)
        return hmac.new(self.partner_key.encode(), base.encode(), hashlib.sha256).hexdigest()

    # ---------- HTTP core ----------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        shop_id: int | None = None,
        access_token: str | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """ยิงคำขอไปที่ Shopee + sign + ตรวจ error แบบรวมศูนย์"""
        timestamp = int(time.time())
        query: dict[str, Any] = {
            "partner_id": self.partner_id,
            "timestamp": timestamp,
            "sign": self.sign(path, timestamp, access_token or "", shop_id),
        }
        if access_token:
            query["access_token"] = access_token
        if shop_id is not None:
            query["shop_id"] = shop_id
        if params:
            query.update(params)

        try:
            resp = await self._http.request(method, path, params=query, json=json_body)
        except httpx.HTTPError as exc:
            raise ShopeeApiError(path, "network", str(exc)) from exc

        try:
            payload = resp.json()
        except ValueError:
            raise ShopeeApiError(path, f"http_{resp.status_code}", resp.text[:300], resp.status_code) from None

        log.debug("SHOPEE %s %s -> %s", method, path, payload)

        if resp.status_code != 200:
            raise ShopeeApiError(path, f"http_{resp.status_code}", str(payload)[:300], resp.status_code)
        error = payload.get("error") or ""
        if error:
            raise ShopeeApiError(path, error, payload.get("message") or "", resp.status_code)
        return payload

    # ---------- Authorization ----------

    def build_authorize_url(self, redirect_url: str) -> str:
        """สร้างลิงก์ OAuth ให้เจ้าของร้านกดอนุญาตให้แอปเข้าถึงร้าน

        (ลิงก์อายุ ~5 นาที เพราะ sign ผูกกับ timestamp — สร้างตอนผู้ใช้กดปุ่มเท่านั้น)
        """
        timestamp = int(time.time())
        query = urlencode(
            {
                "partner_id": self.partner_id,
                "timestamp": timestamp,
                "sign": self.sign(PATH_AUTH_PARTNER, timestamp),
                "redirect": redirect_url,
            }
        )
        return f"{self.host}{PATH_AUTH_PARTNER}?{query}"

    async def get_tokens(self, code: str, shop_id: int) -> dict[str, Any]:
        """แลก authorization code เป็น access_token + refresh_token

        code อายุ 10 นาที ใช้ได้ครั้งเดียว
        คืน dict: {access_token, refresh_token, expire_in, raw}
        """
        payload = await self._request(
            "POST",
            PATH_TOKEN_GET,
            json_body={"code": code, "partner_id": self.partner_id, "shop_id": int(shop_id)},
        )
        return {
            "access_token": _pick(payload, "access_token", default="") or "",
            "refresh_token": _pick(payload, "refresh_token", default="") or "",
            "expire_in": int(_pick(payload, "expire_in", "expires_in", default=14400) or 14400),
            "raw": payload,
        }

    async def refresh_tokens(self, refresh_token: str, shop_id: int) -> dict[str, Any]:
        """ใช้ refresh_token ขอ access_token ใหม่ (Shopee จะให้ refresh_token ใหม่ด้วย)

        คืนรูปแบบเดียวกับ get_tokens()
        """
        payload = await self._request(
            "POST",
            PATH_ACCESS_TOKEN_GET,
            json_body={"refresh_token": refresh_token, "partner_id": self.partner_id, "shop_id": int(shop_id)},
        )
        return {
            "access_token": _pick(payload, "access_token", default="") or "",
            "refresh_token": _pick(payload, "refresh_token", default=refresh_token) or refresh_token,
            "expire_in": int(_pick(payload, "expire_in", "expires_in", default=14400) or 14400),
            "raw": payload,
        }

    async def get_shop_info(self, shop_id: int, access_token: str) -> dict[str, Any]:
        """ข้อมูลร้าน (shop_name, region ฯลฯ) — ใช้ทดสอบว่า token ใช้ได้จริง"""
        return await self._request("GET", PATH_GET_SHOP_INFO, shop_id=shop_id, access_token=access_token)

    # ---------- Order ----------

    async def get_order_list(
        self,
        shop_id: int,
        access_token: str,
        *,
        time_from: int,
        time_to: int,
        cursor: str = "",
        page_size: int = 20,
        time_range_field: str = "create_time",
    ) -> dict[str, Any]:
        """ออเดอร์ในช่วงเวลาที่ระบุ (unix timestamp)

        คืน payload เต็ม ๆ โดยข้อมูลจริงอยู่ที่ response.order_list
        และ cursor ถัดไปอยู่ที่ response.info.next_cursor
        """
        return await self._request(
            "GET",
            PATH_GET_ORDER_LIST,
            shop_id=shop_id,
            access_token=access_token,
            params={
                "time_range_field": time_range_field,
                "time_from": int(time_from),
                "time_to": int(time_to),
                "page_size": page_size,
                "cursor": cursor,
            },
        )

    async def get_order_detail(
        self, shop_id: int, access_token: str, order_sn_list: list[str]
    ) -> dict[str, Any]:
        """รายละเอียดออเดอร์ (รายการสินค้า ที่อยู่ ฯลฯ)"""
        return await self._request(
            "GET",
            PATH_GET_ORDER_DETAIL,
            shop_id=shop_id,
            access_token=access_token,
            params={"order_sn_list": ",".join(order_sn_list)},
        )

    # ---------- Chat (ต้องได้รับสิทธิ์ whitelist จาก Shopee ก่อน) ----------

    async def get_unread_conversation_count(self, shop_id: int, access_token: str) -> int:
        """จำนวนห้องแชทที่ยังไม่ได้อ่านทั้งหมด"""
        payload = await self._request(
            "GET", PATH_GET_UNREAD_CONVERSATION_COUNT, shop_id=shop_id, access_token=access_token
        )
        value = _pick(
            payload,
            "total_unread_conversation_count",
            "unread_conversation_count",
            "unread_count",
            "count",
            default=0,
        )
        return int(value or 0)

    async def get_conversation_list(
        self,
        shop_id: int,
        access_token: str,
        *,
        page_size: int = 20,
        direction: int = 0,
        conv_type: int = 0,
        next_timestamp_nano: int | None = None,
    ) -> dict[str, Any]:
        """รายชื่อห้องแชทล่าสุด (ข้อมูลอยู่ที่ response.conversation_list)

        ค่า direction / conv_type: 0 = ทั้งหมด (ตามค่าเริ่มต้นในเอกสาร Shopee
        ถ้าผลลัพธ์ไม่ตรง ให้เปิด debug log เพื่อดู payload จริงแล้วปรับ)
        """
        params: dict[str, Any] = {"page_size": page_size, "type": conv_type, "direction": direction}
        if next_timestamp_nano is not None:
            params["next_timestamp_nano"] = next_timestamp_nano
        return await self._request(
            "GET", PATH_GET_CONVERSATION_LIST, shop_id=shop_id, access_token=access_token, params=params
        )

    async def get_message(
        self,
        shop_id: int,
        access_token: str,
        conversation_id: str,
        *,
        page_size: int = 20,
        offset: int | None = None,
    ) -> dict[str, Any]:
        """ข้อความในห้องแชทหนึ่ง ๆ (ข้อมูลอยู่ที่ response.message_list)"""
        params: dict[str, Any] = {"conversation_id": conversation_id, "page_size": page_size}
        if offset is not None:
            params["offset"] = offset
        return await self._request(
            "GET", PATH_GET_MESSAGE, shop_id=shop_id, access_token=access_token, params=params
        )

    async def send_message(self, shop_id: int, access_token: str, to_id: int, text: str) -> dict[str, Any]:
        """ส่งข้อความ text ไปในแชท (สงวนไว้สำหรับพัฒนาต่อ — ระวังนโยบายการส่งข้อความของ Shopee)"""
        return await self._request(
            "POST",
            PATH_SEND_MESSAGE,
            shop_id=shop_id,
            access_token=access_token,
            json_body={"to_id": to_id, "message_type": "TEXT", "content": {"text": text}},
        )

    # ---------- Webhook (push) configuration ----------

    async def set_app_push_config(
        self,
        callback_url: str,
        push_on: list[int],
        push_off: list[int] | None = None,
    ) -> dict[str, Any]:
        """ตั้งค่า webhook ของ app — ใช้เมื่อ deploy แล้วมี public HTTPS แล้วเท่านั้น

        push type ที่น่าสนใจ:
        - 3  = ออเดอร์เปลี่ยนสถานะ (order status update)
        - 10 = webchat push (ข้อความแชทใหม่จากผู้ซื้อ) — ต้องมีสิทธิ์ Chat API
        - 1/2 = ร้าน authorize/deauthorize
        """
        json_body: dict[str, Any] = {
            "partner_id": self.partner_id,
            "callback_url": callback_url,
            "set_push_config_on": push_on,
        }
        if push_off:
            json_body["set_push_config_off"] = push_off
        return await self._request("POST", PATH_SET_APP_PUSH_CONFIG, json_body=json_body)
