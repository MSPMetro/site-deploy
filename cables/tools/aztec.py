#!/usr/bin/env python3
import base64
from dataclasses import dataclass
from pathlib import Path


class AztecError(RuntimeError):
    pass


@dataclass(frozen=True)
class AztecPng:
    png_bytes: bytes

    def as_data_uri(self) -> str:
        b64 = base64.b64encode(self.png_bytes).decode("ascii")
        return f"data:image/png;base64,{b64}"


def render_aztec_png(payload: str, *, module_size: int = 6) -> AztecPng:
    try:
        from aztec_code_generator import AztecCode  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise AztecError(
            "Aztec encoder library missing; run `make -C cables setup` to install dependencies."
        ) from exc

    try:
        from PIL import Image  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise AztecError("Pillow missing; run `make -C cables setup`.") from exc

    code = AztecCode(payload)
    matrix = code.matrix

    if not matrix or not matrix[0]:
        raise AztecError("Aztec encoder produced an empty matrix")

    height = len(matrix)
    width = len(matrix[0])

    img = Image.new("1", (width, height), 1)
    for y in range(height):
        row = matrix[y]
        if len(row) != width:
            raise AztecError("Aztec matrix is not rectangular")
        for x in range(width):
            img.putpixel((x, y), 0 if row[x] else 1)

    if module_size > 1:
        img = img.resize((width * module_size, height * module_size), resample=Image.NEAREST)

    out = _encode_png(img)
    return AztecPng(png_bytes=out)


def write_aztec_png(payload: str, out_path: Path, *, module_size: int = 6) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    png = render_aztec_png(payload, module_size=module_size)
    out_path.write_bytes(png.png_bytes)


def _encode_png(img) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()

