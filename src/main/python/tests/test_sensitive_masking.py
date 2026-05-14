import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.sensitive_masking import mask_for_log, mask_text


def test_mask_text_masks_phone_id_policy_customer_no():
    text = "手机号13912345678 身份证110101199001011234 保单号P966073446746215 客户号C335906420260306"
    masked = mask_text(text)
    assert "139****5678" in masked
    assert "110101********1234" in masked
    assert "P***********6215" in masked
    assert "C***********0306" in masked


def test_mask_text_masks_name_with_hint():
    assert mask_text("叫张三的客户") == "叫张*的客户"


def test_mask_for_log_masks_condition_value_by_field():
    masked = mask_for_log({"field": "searchClientNameNew", "value": "张三"})
    assert masked["value"] == "张*"


def test_mask_text_masks_name_in_sentence_with_punctuation():
    masked = mask_text("名叫张三，手机号18675564504，年龄25岁女性客户")
    assert "名叫张*" in masked
    assert "186****4504" in masked
