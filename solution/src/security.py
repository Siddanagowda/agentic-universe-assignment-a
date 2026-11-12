import hashlib, hmac, json
from .config import get_fernet


def phone_digest(phone):
    # Keyed digest avoids exposing the canonical phone in indexes or lookup columns.
    key = get_fernet()._signing_key + get_fernet()._encryption_key
    return hmac.new(key, phone.encode(), hashlib.sha256).hexdigest()


def encrypt(value):
    if value is None:
        return None
    return get_fernet().encrypt(str(value).encode()).decode()


def decrypt(value):
    if value is None:
        return None
    return get_fernet().decrypt(value.encode()).decode()
