"""การตั้งค่าแอปทั้งหมด (อ่านจากไฟล์ .env / environment variables)

วิธีใช้: คัดลอก `.env.example` เป็น `.env` แล้วแก้ค่าตามที่ได้จาก
Shopee Open Platform Console (https://open.shopee.com)
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------- Shopee Open Platform ----------
    # ได้จาก Console > App List หลังสร้าง app และผ่านการอนุมัติ
    shopee_partner_id: int = 0
    shopee_partner_key: str = ""
    # production: https://partner.shopeemobile.com
    # sandbox:    https://partner.test-stable.shopeemobile.com
    shopee_api_host: str = "https://partner.shopeemobile.com"
    # URL ที่ Shopee ส่ง code กลับมาหลังเจ้าของร้านกดอนุญาต
    # (ต้องกรอกค่าเดียวกันนี้ใน Shopee Console ด้วย)
    shopee_redirect_url: str = "http://localhost:8080/oauth/callback"

    # ---------- แอป ----------
    host: str = "127.0.0.1"
    port: int = 8080
    # ระยะห่างระหว่างการดึงข้อมูลจาก Shopee (วินาที) — 60 วิ เพียงพอสำหรับเป้าหมายตอบภายใน 1 ชม.
    poll_interval_seconds: int = 60
    # ดึงออเดอร์ย้อนหลังกี่ชั่วโมง (สำหรับตรวจจับออเดอร์ใหม่/เปลี่ยนสถานะ)
    order_lookback_hours: int = 24
    database_url: str = "sqlite:///data/spapp.db"

    # ---------- ช่องทางแจ้งเตือน ----------
    # Telegram Bot: คุยกับ @BotFather สร้างบอท แล้วขอ token + chat id
    # (หากไม่ใช้ Telegram เว้นว่างได้ — แจ้งเตือนจะไปอยู่ใน Dashboard อย่างเดียว)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    @property
    def shopee_configured(self) -> bool:
        """ตั้งค่า Shopee ครบแล้วหรือยัง"""
        return self.shopee_partner_id > 0 and bool(self.shopee_partner_key)

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


@lru_cache
def get_settings() -> Settings:
    """ค่า setting แบบ singleton (อ่าน .env ครั้งเดียวต่อ process)"""
    return Settings()
