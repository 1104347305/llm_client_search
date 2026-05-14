import binascii
import json
from typing import Any, Dict

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad

    _USE_CRYPTO = True
except ImportError:  # pragma: no cover - 当前环境未安装 pycryptodome 时兜底
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    _USE_CRYPTO = False


def aes_ecb_encrypt_to_hex(plaintext: str, key: bytes) -> str:
    """使用 AES-ECB + PKCS7Padding 加密，返回十六进制字符串。"""
    if len(key) not in (16, 24, 32):
        raise ValueError("key 长度必须为 16/24/32 字节")

    if _USE_CRYPTO:
        cipher = AES.new(key, AES.MODE_ECB)
        ciphertext = cipher.encrypt(pad(plaintext.encode("utf-8"), AES.block_size))
        return binascii.hexlify(ciphertext).decode("utf-8").upper()

    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return binascii.hexlify(ciphertext).decode("utf-8").upper()

def aes_ecb_decrypt_from_hex(hex_plaintext: str, key: bytes) -> str:
    if len(key) not in (16, 24, 32):
        raise ValueError("key 长度必须为 16/24/32 字节")

    ciphertext = binascii.unhexlify(hex_plaintext)

    if _USE_CRYPTO:
        cipher = AES.new(key, AES.MODE_ECB)
        plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)
        return plaintext.decode("utf-8")

    cipher = Cipher(algorithms.AES(key), modes.ECB())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    plaintext = unpadder.update(padded) + unpadder.finalize()
    return plaintext.decode("utf-8")

def encrypt_parse_response_fields(
    robot_text: str,
    extra_output_params: Dict[str, Any],
    key: bytes,
) -> Dict[str, Any]:
    """对 parse 接口的 robot_text 和 extra_output_params 做响应加密。"""
    encrypted_robot_text = aes_ecb_encrypt_to_hex(robot_text, key)
    encrypted_extra = aes_ecb_encrypt_to_hex(
        json.dumps(extra_output_params, ensure_ascii=False, separators=(",", ":")),
        key,
    )
    return {
        "robot_text": encrypted_robot_text,
        "extra_output_params": {
            "extra_output_params_key": encrypted_extra,
        },
    }
