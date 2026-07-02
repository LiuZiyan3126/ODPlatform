"""convert 调度层 —— 几行代码接住所有格式。

它是项目其它部分(指挥家 / CLI / 测试)唯一该调用的"转换入口"。
关键性质:【永不增长】—— 无论将来支持多少种格式,本文件一行都不用改,因为它只查表分发。
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from od_platform.data_pipeline.convert.registry import ConvertOptions, get_converter


def convert_data_to_yolo(
    input_dir: Path,
    output_labels_dir: Path,
    annotation_format: str,
    options: ConvertOptions,
) -> List[str]:
    """统一入口:按 annotation_format 分发到具体 converter,返回类名列表。

    Raises:
        ValueError: 格式未注册,或该 converter 不支持请求的 task(在此提前 fail-fast)。
    """
    entry = get_converter(annotation_format)
    # 能力声明的兑现点:格式不支持该 task,在这里当场报清楚,而不是进到 converter 里炸。
    if not entry.supports(options.task):
        raise ValueError(
            f"格式 {annotation_format!r} 不支持 task={options.task!r}。支持: {entry.supported_tasks}"
        )
    return entry.func(input_dir, output_labels_dir, options)