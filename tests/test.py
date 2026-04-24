from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
import binascii


def aes_ecb_decrypt(hex_ciphertext: str, key: bytes) -> str:
    if len(key) not in (16, 24, 32):
        raise ValueError("key 长度必须为 16/24/32 字节")

    ciphertext = binascii.unhexlify(hex_ciphertext)
    cipher = AES.new(key, AES.MODE_ECB)
    plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)
    return plaintext.decode("utf-8")


if __name__ == "__main__":
    key = b"2026041412040022"
    encrypted = "BE99877E07059F1A3F837790B9628D55"

    result = aes_ecb_decrypt(encrypted, key)
    print("解密结果:", result)