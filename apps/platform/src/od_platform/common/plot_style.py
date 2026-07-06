#!/usr/bin/env python
# -*- coding:utf-8 -*-
# @FileName  :plot_style.py
# @Time      :2026/7/6 11:11:24
# @Author    :雨霓同学
# @Project   :ODPlatform
# @Function  : 学术风格的图表，显示调用，不污染全局的import

from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

_ACADEMIC_RCPARAMS: dict[str, object] = {
    "font.family": ["Times New Roman", "STsong"],
    "font.size": 14,
    "axes.titlesize": 18,
    "axes.labelsize": 16,
    "xtick.labelsize": 14,
    "ytick.labelsize": 14,
    "figure.titlesize": 20,
    "savefig.dpi": 600,
    "savefig.format": "png",
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.1,
}

def apply_academic_style(
    *,
    use_matplotx: bool = True,
    matplotx_style: "pitaya_smoothie_light",
) -> bool:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        logger.error("Matplotlib is not installed. Please install it using pip install matplotlib.")
        return False
    plt.rcParams.update(_ACADEMIC_RCPARAMS)
    logger.info("Academic style applied.")

    if use_matplotx:
        try:
            import matplotx
            if "_" in matplotx_style and matplotx_style.endswith(("_light","_dark")):
                style_name,_, variant = matplotx_style.rpartition("_")
                style_dict = getattr(matplotx_style, style_name, None)
                if isinstance(style_dict,dict) and variant in style_dict:
                    plt.style.use(style_dict[variant])
                    logger.info(f"已经应用matplotx配色：{matplotx_style}")
                else:
                    logger.error(f"Matplotx style {matplotx_style} not found.")
            else:
                plt.style.use(matplotx_style)
                logger.info(f"已经应用matplotx配色：{matplotx_style}")
        except ImportError:
            logger.error("Matplotx is not installed. Please install it using pip install matplotx.")
        except (KeyError, AttributeError, ValueError) as e:
            logger.error(f"Matplotx style {matplotx_style} not found.")
    return True



