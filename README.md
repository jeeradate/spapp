# 🛍️ spapp — Shopee Shop Monitor

แอปเฝ้าระวังกิจกรรมร้าน Shopee ของคุณแบบอัตโนมัติ: **แจ้งเตือนทันทีเมื่อมีคนทักถามเรื่องสินค้า (แชท) หรือมีคนสั่งซื้อ** เพื่อให้คุณตอบลูกค้าได้ภายใน 1 ชั่วโมง โดยไม่ต้องนั่งเช็คเอง

- **ดึงข้อมูลอย่างถูกต้องตามกฎของ Shopee** ผ่าน Shopee Open Platform API v2 (ไม่ใช่ scraping — ซึ่งผิดข้อตกลงของ Shopee และเสี่ยงโดนแบนร้าน)
- **Dashboard ภาษาไทย** ด้วย NiceGUI + ฐานข้อมูล SQLite (SQLModel)
- **แจ้งเตือนผ่าน Telegram** (+ บันทึกประวัติการแจ้งเตือนในแอปเสมอ)
- **ต่ออายุ token อัตโนมัติ** และจำการแจ้งเตือนที่เคยส่งแล้ว ไม่ spam ซ้ำ

---

## 📋 สารบัญ

1. [ภาพรวมการทำงาน](#-ภาพรวมการทำงาน)
2. [ขั้นตอนขอสิทธิ์การใช้ Shopee API](#-ขั้นตอนขอสิทธิ์การใช้-shopee-api-สำคัญที่สุด)
3. [โครงสร้างโปรเจกต์](#-โครงสร้างโปรเจกต์)
4. [การติดตั้งและรัน (uv)](#-การติดตั้งและรัน-uv)
5. [การใช้งานครั้งแรก](#-การใช้งานครั้งแรก)
6. [ตั้งค่า Telegram](#-ตั้งค่า-telegram-เพื่อรับแจ้งเตือนบนมือถือ)
7. [แนวทางพัฒนาต่อ](#-แนวทางพัฒนาต่อ)
8. [การแก้ปัญหาที่พบบ่อย](#-การแก้ปัญหาที่พบบ่อย)

---

## 🔄 ภาพรวมการทำงาน

```
     ┌───────────────────────────── แอปของคุณ (เครื่องคุณเอง) ─────────────────────────────┐
     │                                                                                      │
     │  NiceGUI Dashboard ◄──── ui.timer อัปเดตทุก 5 วิ                                       │
     │       │  อ่าน                                                                        │
     │       ▼                                                                              │
     │  SQLite (SQLModel) ◄── เขียน ── background loop (poll ทุก 60 วิ)                      │
     │                                │                                                     │
     │                                ├──► Shopee Open API ── แชทรอตอบ / ออเดอร์ล่าสุด      │
     │                                ├──► ตรวจ token หมดอายุ → refresh อัตโนมัติ           │
     │                                └──► เจอเหตุการณ์ใหม่ → Notifier                      │
     │                                                              │                       │
     └──────────────────────────────────────────────────────────────┼───────────────────────┘
                                                                    ▼
                                                        🔔 Telegram + ประวัติใน Dashboard
```

สิ่งที่แจ้งเตือน:

| เหตุการณ์ | ตัวอย่างข้อความ |
|---|---|
| ข้อความแชทใหม่ที่ยังไม่ได้อ่าน | `💬 แชทใหม่จาก somchai_99 — สอบถามสินค้าพร้อมส่งไหมคะ` |
| ออเดอร์ใหม่ | `🛒 ออเดอร์ใหม่ THABC12345 — สถานะ: ยังไม่ชำระเงิน` |
| ออเดอร์เปลี่ยนสถานะ | `📦 ออเดอร์ THABC12345 — ยังไม่ชำระเงิน → ชำระแล้ว รอส่งของ` |
| ระบบ (token หมดอายุ ฯลฯ) | `⚠️ ร้านของคุณต้องเชื่อมต่อใหม่` |

---

## 🏛️ ขั้นตอนขอสิทธิ์การใช้ Shopee API (สำคัญที่สุด)

Shopee **ไม่เปิดให้อ่านข้อมูลร้านโดยตรง** ต้องสมัครเป็นนักพัฒนาและสร้าง "App" บน Shopee Open Platform ก่อน ขั้นตอนโดยสรุป:

### 1) สมัครบัญชีนักพัฒนา

- เข้า **https://open.shopee.com** → สมัครบัญชี developer
- เลือกภูมิภาคให้ตรงกับร้านของคุณ (เช่น Thailand) และยืนยันอีเมล
- กรอกข้อมูลตามที่ระบบขอ (อาจมีการขอข้อมูลตัวตน/ธุรกิจ — สำหรับร้านที่จดทะเบียนใช้ข้อมูลนิติบุคคล สำหรับรายบุคคลใช้ข้อมูลส่วนตัว)

### 2) สร้าง App ใน Console

- เข้า Console → **App Management → Create App**
- ตั้งชื่อ/คำอธิบาย app เลือกประเทศไทย และเลือก service ที่ต้องการ (เน้น **Order** และ **Chat/Customer Service**)
- ตั้ง **Redirect URL** = `http://localhost:8080/oauth/callback` (ค่าเดียวกับ `SHOPEE_REDIRECT_URL` ใน `.env`)
- รอ Shopee อนุมัติ — ใช้เวลาไม่แน่นอน ตั้งแต่ไม่กี่วันถึงไม่กี่สัปดาห์

### 3) ทดสอบบน Sandbox ก่อน (แนะนำ)

- หลังสร้าง app สำเร็จจะได้ **Test Partner ID / Test Key** (ใช้กับ sandbox host)
- ร้านทดสอบ: ใน Console มีส่วนจัดการ sandbox shop ให้ทดลอง authorize
- ใน `.env` เปลี่ยน `SHOPEE_API_HOST=https://partner.test-stable.shopeemobile.com`

### 4) ขอสิทธิ์ Chat API (whitelist) — จำเป็นสำหรับฟีเจอร์แจ้งเตือนแชท

- API กลุ่มแชท (`sellerchat/*`) เป็น **whitelist-only** — ต้องยื่นขอเปิดใช้เพิ่มผ่าน **Console → API Permission** (หรือ FAQ เรื่อง Chat API) โดยอาจต้องเปิด ticket กับทีม Shopee
- ⚠️ ข้อควรทราบ: ประเภท app "Customer Service" ในบางภูมิภาคต้องมีเอกสารจดทะเบียนธุรกิจ การอนุมัติจึงยากกว่าสำหรับผู้ขายรายบุคคล
- ✅ **ออเดอร์** (แจ้งเตือนคนสั่งซื้อ) ไม่ต้อง whitelist — ทำงานได้ทันทีที่ app ได้รับอนุมัติ
- 🛟 **แผนสำรองระหว่างรอสิทธิ์แชท**: ตั้ง auto-reply ใน Shopee Seller Centre (เช่น "ขอบคุณครับ เดี๋ยวตอบกลับภายใน 1 ชม.") + เปิดแจ้งเตือนแอป Shopee บนมือถือ ไปพร้อมกับแจ้งเตือนออเดอร์จากแอปนี้

### 5) Publish (Go Live) แล้วใช้งานจริง

- เมื่อพร้อมใช้งานจริง ให้กด **Go Live** ใน Console → จะได้ **Live Partner ID / Live Key**
- ใน `.env` ใส่ค่า live และ `SHOPEE_API_HOST=https://partner.shopeemobile.com`

### 6) เชื่อมต่อร้านของคุณ (authorize)

- รันแอป → กดปุ่ม **"เชื่อมต่อร้าน Shopee"** → ล็อกอินด้วยบัญชีเจ้าของร้าน → กดอนุญาต
- Shopee จะเลือกได้ว่าจะอนุญาตนานแค่ไหน (7/30/90/180/365 วัน)

### 🕐 อายุของข้อมูลสำคัญ (จากเอกสาร Shopee)

| รายการ | อายุ | เกิดอะไรขึ้นเมื่อหมด |
|---|---|---|
| `code` (จากการ authorize) | 10 นาที ใช้ครั้งเดียว | กดปุ่มเชื่อมต่อใหม่ |
| `access_token` | 4 ชั่วโมง | **แอป refresh ให้อัตโนมัติ** |
| `refresh_token` | 30 วัน | **แอปต่ออายุให้อัตโนมัติ** |
| การอนุญาตร้าน (ที่ผู้ขายเลือก) | 7–365 วัน | ต้องกดเชื่อมต่อร้านใหม่ |
| `sign`/timestamp ของ request | ~5 นาที | เครื่องต้องตั้งเวลาถูกต้อง |

---

## 📁 โครงสร้างโปรเจกต์

```
spapp/
├── README.md              # คู่มือนี้
├── AGENTS.md              # คำแนะนำสำหรับ AI coding agent ที่มาทำงานกับโค้ดนี้
├── dev_main.py            # จุดรันโหมดพัฒนา (auto-reload)
├── .env.example           # ตัวอย่างการตั้งค่า (คัดลอกเป็น .env)
├── pyproject.toml          # dependencies + config (จัดการด้วย uv)
├── data/                  # ฐานข้อมูล SQLite (สร้างอัตโนมัติ — ห้าม push ขึ้น git)
└── src/spapp/
    ├── config.py          # อ่านค่าจาก .env (pydantic-settings)
    ├── db.py              # engine + session (SQLite + WAL)
    ├── models.py          # ตาราง: ShopCredential / ChatConversation / TrackedOrder / NotificationLog
    ├── shopee/
    │   └── client.py      # Shopee Open Platform API v2 client (signing, token, order, chat)
    ├── services/
    │   ├── monitor.py     # background polling: ตรวจแชท+ออเดอร์ แล้วแจ้งเตือน (มี dedup)
    │   └── notify.py      # ตัวส่งแจ้งเตือน (Telegram + บันทึกลง DB)
    └── ui/
        └── main.py        # NiceGUI dashboard + OAuth callback + webhook endpoint
```

---

## 🚀 การติดตั้งและรัน (uv)

โปรเจกต์นี้ใช้ [uv](https://docs.astral.sh/uv/) จัดการ Python + dependencies ทั้งหมด (uv จะดาวน์โหลด Python ให้เองถ้าเครื่องยังไม่มี)

```powershell
# 1) ติดตั้ง dependencies (สร้าง .venv อัตโนมัติ)
uv sync

# 2) คัดลอกไฟล์ตั้งค่า แล้วเปิดแก้ค่าตามที่ได้จาก Shopee Console
copy .env.example .env

# 3) รัน test (ไม่ต้องต่อ Shopee ก็รันได้)
uv run pytest

# 4) รันแอป
uv run spapp
# → เปิดเบราว์เซอร์ที่ http://127.0.0.1:8080 ให้อัตโนมัติ
```

คำสั่งอื่น ๆ ที่ใช้บ่อย:

```powershell
uv run nicegui --reload dev_main.py   # โหมดพัฒนา — แก้โค้ดแล้ว reload เอง
uv add <package>                      # เพิ่ม dependency
uv add --dev <package>                # เพิ่ม dependency เฉพาะตอนพัฒนา
SPAPP_NO_BROWSER=1 uv run spapp       # รันแบบไม่เปิดเบราว์เซอร์ (env var ใน PowerShell: $env:SPAPP_NO_BROWSER='1' ก่อน)
```

การตั้งค่าระดับ log: `$env:SPAPP_LOG_LEVEL='DEBUG'` (มีประโยชน์มากเวลาอยากเห็น payload จริงที่ Shopee ตอบกลับ)

---

## 🧭 การใช้งานครั้งแรก

1. แก้ `.env` ให้มี `SHOPEE_PARTNER_ID` + `SHOPEE_PARTNER_KEY` จาก Console
2. `uv run spapp` → เปิด Dashboard
3. กดปุ่ม **🔗 เชื่อมต่อร้าน Shopee** → แท็บใหม่เปิดหน้าล็อกอิน Shopee → ล็อกอิน + กดอนุญาต
4. Shopee พากลับมาหน้า callback ของแอป → เห็นข้อความ "✅ เชื่อมต่อร้านสำเร็จ"
5. รอสักครู่ (ไม่เกิน `POLL_INTERVAL_SECONDS`) ระบบจะเริ่มแจ้งเตือน
   - รอบแรกจะแจ้งเหตุการณ์ที่ "ค้างอยู่" ในช่วง lookback ด้วย (แชทยังไม่ได้อ่าน / ออเดอร์ใน 24 ชม.ล่าสุด) ถือเป็นเรื่องปกติ
6. ตั้งค่า Telegram (ด้านล่าง) เพื่อรับแจ้งเตือนบนมือถือ แล้วกดปุ่ม **🔔 ทดสอบการแจ้งเตือน** ใน Dashboard

> 💡 อยากเปิด Dashboard จากมือถือในบ้าน? ตั้ง `HOST=0.0.0.0` แล้วเข้า `http://<IP เครื่องนี้>:8080`

---

## 📱 ตั้งค่า Telegram เพื่อรับแจ้งเตือนบนมือถือ

1. คุยกับ **@BotFather** ใน Telegram → พิมพ์ `/newbot` → ตั้งชื่อ → ได้ **token** (รูป `123456:ABC-...`)
2. **ส่งข้อความอะไรก็ได้** ให้บอทที่เพิ่งสร้าง (สำคัญ — ต้องส่งก่อนถึงจะรู้ chat id)
3. เปิด `https://api.telegram.org/bot<TOKEN>/getUpdates` ในเบราว์เซอร์ → หา `"chat":{"id":...}`
4. ใส่ 2 ค่าใน `.env`: `TELEGRAM_BOT_TOKEN` และ `TELEGRAM_CHAT_ID`
5. รีสตาร์ทแอป แล้วกดปุ่ม **🔔 ทดสอบการแจ้งเตือน** ใน Dashboard

---

## 🛠️ แนวทางพัฒนาต่อ

- **Webhook แทน polling (real-time)** — ระยะ 2: Shopee มี push notification ผ่าน webhook (`POST /webhook/shopee` พร้อมใช้แล้วในโค้ด) สำหรับ order status (type 3) และ webchat (type 10) แต่ **callback URL ต้องเป็น HTTPS สาธารณะ** จึงต้อง deploy บน VPS/NAS หรือใช้ tunnel (เช่น Cloudflare Tunnel) — ตั้งค่า push ได้ผ่าน `ShopeeClient.set_app_push_config()` และมี `get_lost_push_message` สำหรับกู้ข้อความที่พลาดย้อนหลัง 3 วัน
- **ตอบแชทจากในแอป** — `ShopeeClient.send_message()` เตรียมไว้แล้ว (ระวังนโยบายการส่งข้อความของ Shopee)
- **รัน 24/7** — ทำ auto-start ตอนบูตเครื่อง (Windows Task Scheduler) หรือย้ายไปรันบน mini PC / NAS / VPS
- **สรุปยอดรายวัน** — นับออเดอร์/แชทจากตารางใน DB เพิ่มหน้าสถิติ
- **หลายร้าน** — ระบบรองรับหลายร้านอยู่แล้ว (กดเชื่อมต่อเพิ่มได้)

---

## 🩹 การแก้ปัญหาที่พบบ่อย

| อาการ | สาเหตุ/วิธีแก้ |
|---|---|
| `error_param` ตอนเรียก API | ค่า sign ผิด — เช็คว่า partner_id/key และ host (sandbox vs production) ไม่ชนกัน และเวลาเครื่องถูกต้อง (timestamp อายุ 5 นาที) |
| `error_auth` | token หมดอายุ/ถูกเพิกถอน — กดปุ่มเชื่อมต่อร้านใหม่ |
| ไม่มีแจ้งเตือนแชท (แต่ออเดอร์ได้) | Chat API ยังไม่ได้รับอนุมัติ whitelist — ดูหัวข้อขั้นตอนข้อ 4 |
| log ภาษาไทยเพี้ยนบน console | รัน `chcp 65001` ก่อน หรือตั้ง `$env:PYTHONUTF8='1'` |
| `database is locked` | มีแอป instance เปิดซ้อนกัน — ปิดตัวเก่าก่อน |
| Shopee ตอบช้า/429 | เพิ่ม `POLL_INTERVAL_SECONDS` (เช่น 120) |
| อยากเห็นข้อมูลดิบที่ Shopee ตอบ | `$env:SPAPP_LOG_LEVEL='DEBUG'` แล้วดู log ของ `spapp.shopee.client` |

> ⚠️ **ห้าม push ไฟล์ `.env` และ `data/` ขึ้น git** — เพราะมี `SHOPEE_PARTNER_KEY` และ token ของร้านอยู่ข้างใน (.gitignore ตั้งบล็อกไว้แล้ว)

---

*โปรเจกต์นี้เขียนตาม Shopee Open Platform API v2 (เอกสาร: https://open.shopee.com/documents) — ถ้า Shopee ปรับ endpoint/ชื่อ field ในอนาคต แก้ได้จุดเดียวที่ `src/spapp/shopee/client.py` และใช้ debug log ช่วยเทียบ payload จริง*
