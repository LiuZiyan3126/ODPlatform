"""使用 Pillow 检查图片能否完整解码。"""
from __future__ import annotations

from typing import Dict, List

from od_platform.validate_dataset.registry import (
    CheckContext,
    CheckResult,
    CheckSeverity,
    check,
)

_PREVIEW_LIMIT = 20


@check("image_integrity")
def validate_image_integrity(ctx: CheckContext) -> CheckResult:
    try:
        from PIL import Image
    except ImportError:
        return CheckResult(
            name="image_integrity",
            severity=CheckSeverity.INFO,
            summary="Pillow 未安装，跳过图片完整性检查",
            details={"reason": "pillow_unavailable"},
        )

    errors: List[Dict[str, str]] = []
    total_images = 0
    for split, images in ctx.snapshot.images_per_split.items():
        for image_path in images:
            total_images += 1
            try:
                with Image.open(image_path) as image:
                    image.verify()
                with Image.open(image_path) as image:
                    image.load()
            except Exception as exc:
                errors.append({
                    "split": split,
                    "image": str(image_path),
                    "error": f"{type(exc).__name__}: {exc}",
                })

    total_corrupt = len(errors)
    if total_corrupt == 0:
        return CheckResult(
            name="image_integrity",
            severity=CheckSeverity.PASS,
            summary=f"全部 {total_images} 张图片均可正常解码",
            details={"total_images": total_images, "total_corrupt": 0},
        )

    return CheckResult(
        name="image_integrity",
        severity=CheckSeverity.ERROR,
        summary=f"发现 {total_corrupt}/{total_images} 张图片损坏或无法解码",
        details={
            "reason": "image_decode_failed",
            "total_images": total_images,
            "total_corrupt": total_corrupt,
            "errors": errors,
            "errors_preview": errors[:_PREVIEW_LIMIT],
        },
    )
