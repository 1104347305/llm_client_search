import json

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad

    _USE_CRYPTO = True
except ImportError:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    _USE_CRYPTO = False

from utils.response_crypto import aes_ecb_encrypt_to_hex, encrypt_parse_response_fields


def aes_ecb_decrypt(hex_ciphertext: str, key: bytes) -> str:
    ciphertext = bytes.fromhex(hex_ciphertext)
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


def test_aes_ecb_encrypt_to_hex_round_trip():
    key = b"1234567890abcdef"
    plaintext = "系统识别查询条件：A1且高温的客户"

    encrypted = aes_ecb_encrypt_to_hex(plaintext, key)

    assert aes_ecb_decrypt(encrypted, key) == plaintext


def test_encrypt_parse_response_fields_shape_and_content():
    key = b"1234567890abcdef"
    payload = encrypt_parse_response_fields(
        robot_text="系统识别查询条件：A1的客户",
        extra_output_params={
            "query": "A1客户",
            "matched_level": 2,
            "conditions": [{"field": "newValueLabel", "operator": "MATCH", "value": "A1"}],
        },
        key=key,
    )

    assert isinstance(payload["robot_text"], str)
    assert payload["extra_output_params"].keys() == {"extra_output_params_key"}
    assert aes_ecb_decrypt(payload["robot_text"], key) == "系统识别查询条件：A1的客户"
    assert json.loads(
        aes_ecb_decrypt(payload["extra_output_params"]["extra_output_params_key"], key)
    ) == {
        "query": "A1客户",
        "matched_level": 2,
        "conditions": [{"field": "newValueLabel", "operator": "MATCH", "value": "A1"}],
    }
