import time
import random
from PIL import ImageFont

# ================== 配置 ==================
FONT_PATH = "arial.ttf"            # 替换为你的字体文件路径
FONT_SIZE = 20
NUM_IMAGES = 100
MAX_BOXES_PER_IMAGE = 50
MIN_BOXES_PER_IMAGE = 1
CLASS_NAMES = ["person", "car", "dog", "cat", "bicycle", "bus"]
CONF_DECIMALS = 2                  # 置信度保留的小数位数
# ==========================================

def build_template_cache(font, class_names, decimals=2):
    """
    为每个类别构建一个模板尺寸缓存。
    使用最宽的置信度占位符（如 '100%' 或 '1.00'）计算一次，
    保证所有该类别标签都有足够的宽度和高度。
    """
    cache = {}
    # 最宽的占位符：例如 "1.00" 或 "100%" （根据小数位决定）
    # 这里假设格式为 {cls} {conf:.2f}，那么最宽的可能是 "1.00"
    widest_conf = "1." + "0" * decimals  # 例如 "1.00"
    for cls in class_names:
        text = f"{cls} {widest_conf}"
        bbox = font.getbbox(text)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        cache[cls] = (w, h)
    return cache

def main():
    # 预加载字体
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

    # 生成模板缓存（耗时极短，仅计算 N 类）
    print("正在生成模板尺寸缓存...")
    cache_start = time.perf_counter()
    template_cache = build_template_cache(font, CLASS_NAMES, CONF_DECIMALS)
    cache_time = time.perf_counter() - cache_start
    print(f"缓存生成耗时：{cache_time*1000:.3f} ms （共 {len(template_cache)} 个类别）\n")

    # 模拟图像检测结果（不计时）
    all_images = []
    for _ in range(NUM_IMAGES):
        num_boxes = random.randint(MIN_BOXES_PER_IMAGE, MAX_BOXES_PER_IMAGE)
        boxes_info = []
        for _ in range(num_boxes):
            cls = random.choice(CLASS_NAMES)
            conf = random.uniform(0.5, 1.0)
            boxes_info.append((cls, conf))
        all_images.append(boxes_info)

    # ========== 测量：模板缓存方式（第二步仅字典取值） ==========
    step2_cache_ns = 0
    total_objects = 0

    for boxes_info in all_images:
        for cls, conf in boxes_info:
            # 步骤1：拼接文字（不计时）
            text = f"{cls} {conf:.{CONF_DECIMALS}f}"

            # 步骤2：从模板缓存取尺寸 —— 开始计时
            start = time.perf_counter_ns()
            w, h = template_cache[cls]   # 只根据类别名取值
            end = time.perf_counter_ns()
            step2_cache_ns += (end - start)

            total_objects += 1
            # 步骤3-5 绘制框和文字（模拟，此处省略）

    # ========== 对比：无缓存方式（实时 getbbox） ==========
    step2_nocache_ns = 0
    for boxes_info in all_images:
        for cls, conf in boxes_info:
            text = f"{cls} {conf:.{CONF_DECIMALS}f}"
            start = time.perf_counter_ns()
            bbox = font.getbbox(text)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            end = time.perf_counter_ns()
            step2_nocache_ns += (end - start)

    # ========== 输出 ==========
    avg_cache_ns = step2_cache_ns / total_objects
    avg_nocache_ns = step2_nocache_ns / total_objects

    print(f"图片数：{NUM_IMAGES}，总文字对象数：{total_objects}")
    print(f"字体：{FONT_PATH}，字号：{FONT_SIZE}")
    print("--------------------------------------------------")
    print(f"【模板缓存】第二步总耗时：{step2_cache_ns/1e6:.3f} ms")
    print(f"  平均每个标签取值耗时：{avg_cache_ns:.1f} ns  ({avg_cache_ns/1000:.4f} µs)")
    print(f"【无缓存】  第二步总耗时：{step2_nocache_ns/1e6:.3f} ms")
    print(f"  平均每个标签计算耗时：{avg_nocache_ns:.1f} ns  ({avg_nocache_ns/1000:.3f} µs)")
    print(f"--------------------------------------------------")
    print(f"模板缓存提速约 {avg_nocache_ns/avg_cache_ns:.0f} 倍")
    print(f"缓存条目数：{len(template_cache)} （仅为类别数）")

if __name__ == "__main__":
    main()