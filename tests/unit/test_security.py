from datetime import timedelta

from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    mask_address,
    mask_phone,
    verify_password,
)


def test_password_hash_round_trip():
    hashed = hash_password("Demo123!")
    assert hashed != "Demo123!"
    assert verify_password("Demo123!", hashed)
    assert not verify_password("wrong-password", hashed)


def test_access_token_round_trip():
    token = create_token(
        "user-1",
        token_type="access",
        roles=["customer"],
        expires_delta=timedelta(minutes=5),
    )
    payload = decode_token(token, expected_type="access")
    assert payload["sub"] == "user-1"
    assert payload["roles"] == ["customer"]


def test_pii_masking():
    assert mask_phone("联系电话 13812345678") == "联系电话 138****5678"
    assert "***" in mask_address("地址：上海市浦东新区测试路100号")
