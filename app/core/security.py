"""密码哈希工具（基于标准库 pbkdf2_hmac，无需额外依赖）。

存储格式：`pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>`。
"""
import hashlib
import hmac
import secrets

_PBKDF2_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    """对明文密码做 PBKDF2-SHA256 加盐哈希，返回可持久化字符串。

    Args:
        password: 明文密码。

    Returns:
        形如 `pbkdf2_sha256$100000$<salt_hex>$<hash_hex>` 的哈希串。
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """校验明文密码与存储的哈希是否匹配。

    Args:
        password: 待校验明文。
        hashed: `hash_password` 生成的哈希串。

    Returns:
        匹配返回 True，否则 False（格式非法也返回 False）。
    """
    try:
        algorithm, iterations, salt_hex, digest_hex = hashed.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        expected = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        ).hex()
        return hmac.compare_digest(expected, digest_hex)
    except (ValueError, TypeError):
        return False
