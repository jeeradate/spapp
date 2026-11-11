"""ทดสอบการ sign และ authorize URL ของ Shopee client

สำคัญ: test นี้ล็อก "ลำดับ base string" ของการ sign ไว้
(partner_id + api_path + timestamp + access_token + shop_id)
ถ้า Shopee เปลี่ยนกลไกการ sign ในอนาคต จะรู้ทันทีจาก test นี้
"""

import hashlib
import hmac
from urllib.parse import parse_qs, urlparse

from spapp.shopee.client import ShopeeClient


def make_client() -> ShopeeClient:
    return ShopeeClient(partner_id=100001, partner_key="test-key", host="https://partner.example.test")


def test_sign_base_string_order_is_locked() -> None:
    client = make_client()
    timestamp = 1700000000
    signature = client.sign("/api/v2/order/get_order_list", timestamp, "TOKEN", 12345)
    expected = hmac.new(
        b"test-key",
        b"100001/api/v2/order/get_order_list1700000000TOKEN12345",
        hashlib.sha256,
    ).hexdigest()
    assert signature == expected


def test_public_sign_has_no_token_or_shop() -> None:
    client = make_client()
    timestamp = 1700000000
    signature = client.sign("/api/v2/auth/token/get", timestamp)
    expected = hmac.new(b"test-key", b"100001/api/v2/auth/token/get1700000000", hashlib.sha256).hexdigest()
    assert signature == expected


def test_sign_changes_with_token_and_shop() -> None:
    client = make_client()
    timestamp = 1700000000
    assert client.sign("/api/v2/x", timestamp) != client.sign("/api/v2/x", timestamp, "TOKEN")
    assert client.sign("/api/v2/x", timestamp, "TOKEN", 1) != client.sign("/api/v2/x", timestamp, "TOKEN", 2)


def test_authorize_url_contains_required_params() -> None:
    client = make_client()
    url = client.build_authorize_url("http://localhost:8080/oauth/callback")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.path == "/api/v2/shop/auth_partner"
    assert query["partner_id"] == ["100001"]
    assert query["redirect"] == ["http://localhost:8080/oauth/callback"]
    assert "timestamp" in query
    assert len(query["sign"][0]) == 64
