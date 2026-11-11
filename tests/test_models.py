"""ทดสอบโมเดลฐานข้อมูล (สร้าง/อ่านคืน บน SQLite ชั่วคราว)"""

from sqlmodel import Session, SQLModel, create_engine, select

from spapp import models


def test_models_roundtrip(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as s:
        s.add(models.ShopCredential(shop_id=1, shop_name="ร้านทดสอบ", access_token="a", refresh_token="r"))
        s.add(models.TrackedOrder(order_sn="TH12345", shop_id=1, order_status="UNPAID", buyer_username="buyer1"))
        s.add(models.ChatConversation(conversation_id="99001", shop_id=1, unread=True, unread_count=2))
        s.add(models.NotificationLog(kind="order", title="ออเดอร์ใหม่", body="ทดสอบ"))
        s.commit()

        cred = s.get(models.ShopCredential, 1)
        assert cred is not None
        assert cred.shop_name == "ร้านทดสอบ"
        assert cred.token_expired_or_unknown is True  # ยังไม่ระบุเวลาหมดอายุ

        order = s.get(models.TrackedOrder, "TH12345")
        assert order is not None
        assert order.order_status == "UNPAID"

        conv = s.get(models.ChatConversation, "99001")
        assert conv is not None
        assert conv.unread_count == 2

        notes = s.exec(select(models.NotificationLog)).all()
        assert len(notes) == 1
        assert notes[0].title == "ออเดอร์ใหม่"
