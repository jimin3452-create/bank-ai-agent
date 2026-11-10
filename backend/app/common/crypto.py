"""카드번호 암호화 (AES-256-GCM). DB에는 base64(nonce + 암호문)만 저장하고 화면에는 끝 4자리만 보여준다."""
import base64
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings


def _aes() -> AESGCM:
    return AESGCM(base64.b64decode(settings.card_encryption_key))


def encrypt_card_number(number: str) -> str:
    nonce = secrets.token_bytes(12)
    return base64.b64encode(nonce + _aes().encrypt(nonce, number.encode(), None)).decode()


def decrypt_card_number(stored: str) -> str:
    raw = base64.b64decode(stored)
    return _aes().decrypt(raw[:12], raw[12:], None).decode()


def luhn_number(prefix: str) -> str:
    """prefix로 시작하는 16자리 Luhn 유효 번호."""
    digits = [int(c) for c in prefix] + [secrets.randbelow(10) for _ in range(16 - len(prefix) - 1)]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    digits.append((10 - total % 10) % 10)
    return "".join(str(d) for d in digits)


def luhn_valid(number: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(number)):
        d = int(c)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0
