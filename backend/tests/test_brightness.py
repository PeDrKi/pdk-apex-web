"""Tăng/giảm sáng đều làm các bit lật NHẤT QUÁN; trước đây hệ thống chọn nhầm cách đọc thô và báo hỏng."""
import io
import numpy as np
import pytest
from PIL import Image
from .conftest import png_bytes
from .test_api import _embed, _extract


@pytest.mark.parametrize("delta,red", [(24, 15), (16, 5), (5, 5)])
@pytest.mark.parametrize("shift", [-15, -8, 8, 12, 15])
def test_uniform_brightness_shift_reads_back(client, photo, delta, red, shift):
    _, stego, keys = _embed(client, png_bytes(photo), "PDK 2026 bản quyền", redundancy=red, delta=delta)
    a = np.asarray(Image.open(io.BytesIO(stego))).astype(np.float64)
    b = np.clip(a + shift, 0, 255).astype(np.uint8)
    buf = io.BytesIO(); Image.fromarray(b).save(buf, "PNG")
    j = _extract(client, buf.getvalue(), keys).json()
    assert j.get("message") == "PDK 2026 bản quyền"
