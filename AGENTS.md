# AGENTS.md — คู่มือสำหรับ AI coding agent

ไฟล์นี้ให้ AI coding agent (เช่น OpenCode) อ่านเพื่อเข้าใจโปรเจกต์และทำงานได้ถูกทางทันที

## เป้าหมายของโปรเจกต์

ผู้ใช้เป็น**ผู้ขาย Shopee (ไทย)** ต้องการแอปเฝ้าระวังร้าน เพื่อ**ตอบแชท/จัดการออเดอร์ภายใน 1 ชั่วโมง** โดยไม่ต้องเช็คเอง:
- แจ้งเตือนเมื่อมีข้อความแชทใหม่ที่ยังไม่ได้อ่าน (คนถามเรื่องสินค้า)
- แจ้งเตือนเมื่อมีออเดอร์ใหม่ หรือออเดอร์เปลี่ยนสถานะ
- ช่องทางแจ้งเตือน: Telegram + หน้า Dashboard

## Tech stack (อย่าเปลี่ยนถ้าผู้ใช้ไม่ขอ)

- **Python 3.14** (จัดการด้วย **uv** — `uv sync`, `uv add`, `uv run`)
- **NiceGUI 4.x** — UI + background task ในตัว (โมดูล `spapp.ui.main`)
- **SQLModel + SQLite** (โหมด WAL) — ไฟล์อยู่ที่ `data/spapp.db`
- **httpx** — async HTTP ไปยัง Shopee API
- **pydantic-settings** — อ่าน config จาก `.env`

## คำสั่งที่ต้องใช้

```powershell
uv sync                              # ติดตั้ง/sync dependencies
uv run pytest                        # รัน test ทั้งหมด
uv run spapp                         # รันแอป (เปิด browser ที่ http://127.0.0.1:8080)
uv run nicegui --reload dev_main.py  # โหมดพัฒนา auto-reload
uv add <pkg> / uv add --dev <pkg>    # เพิ่ม dependency
$env:SPAPP_NO_BROWSER='1'; uv run spapp   # รันแบบไม่เปิด browser (ใช้ตอน test)
```

ตัวแปรสภาพแวดล้อมที่มีผล: `SPAPP_LOG_LEVEL` (default INFO, ใช้ DEBUG เพื่อดู payload จริงจาก Shopee), `SPAPP_NO_BROWSER`

## โครงสร้างและความรับผิดชอบของแต่ละไฟล์

| ไฟล์ | หน้าที่ |
|---|---|
| `src/spapp/config.py` | ค่า setting ทั้งหมด อ่านจาก `.env` — เพิ่ม config ใหม่ที่นี่เสมอ (+ `.env.example`) |
| `src/spapp/models.py` | ตาราง SQLModel: `ShopCredential`, `ChatConversation`, `TrackedOrder`, `NotificationLog` |
| `src/spapp/db.py` | engine/session เดียวของแอป — path relative ตีความเทียบรากโปรเจกต์ |
| `src/spapp/shopee/client.py` | **Shopee Open Platform API v2** — signing, token, order, chat, push config |
| `src/spapp/services/monitor.py` | background polling + dedup การแจ้งเตือน (เทียบกับ DB ทุกรอบ) |
| `src/spapp/services/notify.py` | ส่งแจ้งเตือน (บันทึก DB เสมอ + Telegram ถ้าตั้งค่า) |
| `src/spapp/ui/main.py` | Dashboard, OAuth callback, webhook endpoint, entry `run()` |

## ความรู้เรื่อง Shopee API ที่ต้องรู้ก่อนแก้โค้ด (อย่าเดา)

- **การ sign ทุก request**: `sign = HMAC-SHA256(partner_key, partner_id + api_path + timestamp + access_token + shop_id)`
  - API แบบ public (auth/token): ไม่มี `access_token`/`shop_id` ต่อท้าย
  - มี test ล็อกลำดับนี้ไว้ที่ `tests/test_shopee_client.py` — ถ้าแก้กลไก sign ให้แก้ test ด้วย
- **Host**: production `https://partner.shopeemobile.com`, sandbox `https://partner.test-stable.shopeemobile.com` — key ของสอง environment ต่างกัน ใช้ผสมกันไม่ได้
- **Token**: แลก `code` ที่ `POST /api/v2/auth/token/get`; ต่ออายุที่ `POST /api/v2/auth/access_token/get` (มี `partner_id` ใน JSON body ด้วย); access_token 4 ชม., refresh_token 30 วัน, `code` 10 นาทีใช้ครั้งเดียว
- **ออเดอร์**: `GET /api/v2/order/get_order_list` (query: `time_range_field`, `time_from`, `time_to`, `page_size`, `cursor` แบบ pagination)
- **แชท**: กลุ่ม `GET /api/v2/sellerchat/*` (`get_unread_conversation_count`, `get_conversation_list`, `get_message`) — **whitelist-only** ต้องขอสิทธิ์จาก Shopee ก่อน ถ้ายังไม่ได้สิทธิ์ API นี้จะ error แต่ส่วนออเดอร์ยังใช้ได้
- **Webhook**: endpoint `POST /webhook/shopee` (ใน `ui/main.py`) ตรวจ signature ใน header `Authorization: SHA256 <hex>` = HMAC-SHA256 ของ **raw body** ด้วย partner_key; push type 3 = order status, 10 = webchat, 1/2 = authorize/deauthorize
- ชื่อ field บางอย่างของ Chat API ไม่ได้ระบุชัดในเอกสารสาธารณะ → โค้ดอ่านแบบยืดหยุ่นหลายชื่อ และ **เปิด SPAPP_LOG_LEVEL=DEBUG เพื่อดู payload จริง** ก่อนสรุปว่าอะไรผิด

## Conventions ของโปรเจกต์นี้

- **ภาษา**: docstring/คอมเมนต์/UI เป็นภาษาไทย, ชื่อตัวแปร-func ภาษาอังกฤษ
- **async ทั้งหมด** ในส่วนที่คุยกับ Shopee/Telegram (httpx.AsyncClient) — `ShopeeClient` เดียวกัน reuse ได้ อย่าสร้างใหม่ต่อ request
- **DB**: ใช้ `with session() as s:` สั้น ๆ ทำงานเสร็จปิดทันที (SQLite WAL) — **ห้าม** แชร์ session ข้าม task/thread; อ่าน attribute ของ ORM object ก่อนปิด session เท่านั้น
- **datetime**: ใช้ timezone-aware UTC (`utcnow()` ใน `models.py`) — SQLModel 0.0.24+ บังคับ naive ไม่ได้; แปลงเป็นเวลาท้องถิ่นเฉพาะตอนแสดงผล (`_fmt_dt`)
- **การแจ้งเตือน**: ผ่าน `Notifier.notify(kind, title, body)` เสมอ (`kind` = "chat"/"order"/"system") เพื่อให้บันทึกประวัติ + ส่ง Telegram อัตโนมัติ
- **dedup**: การแจ้งเตือนเป็นเหตุการณ์ "เปลี่ยนแปลงใหม่" เท่านั้น — เทียบ `ChatConversation.last_seen_marker` และ `TrackedOrder.order_status` ก่อนแจ้งทุกครั้ง
- **logging ไม่ใช้ print** — logger ตามโมดูล; การแจ้งเตือนผู้ใช้ใน UI ใช้ `ui.notify`

## เรื่องความปลอดภัย (สำคัญ)

- ห้าม hardcode `SHOPEE_PARTNER_ID`, `SHOPEE_PARTNER_KEY`, token ใด ๆ ในโค้ด — ทุกอย่างมาจาก `.env` (ไม่ถูก track ใน git)
- ห้าม commit `.env`, `data/` — ตรวจสอบก่อนทุก commit
- webhook ต้องตรวจ signature เสมอ ก่อนเชื่อ payload

## เวลาเพิ่มฟีเจอร์ (ลำดับงานที่แนะนำ)

1. แก้/เพิ่มที่ `shopee/client.py` ก่อน (เป็นชั้น API เดียว) → 2. logic ที่ `services/monitor.py` → 3. UI ที่ `ui/main.py` → 4. เพิ่ม config ที่ `config.py` + `.env.example` → 5. เพิ่ม test → 6. `uv run pytest` ให้เขียว → 7. ทดสอบรันจริง `uv run spapp`

## Backlog ที่วางไว้ (คุยกับผู้ใช้ก่อนลงมือ)

- ย้ายจาก polling ไป webhook แบบเต็มตัว (ต้อง public HTTPS + `set_app_push_config` + กู้ข้อความที่พลาดด้วย `get_lost_push_message`)
- ตอบแชทจากในแอป (`send_message`) — ต้องระวังนโยบาย Shopee
- auto-start ตอนบูต Windows / deploy รัน 24/7
- หน้าสถิติสรุปรายวัน
