#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主图去重微改 —— 一键脚本
linkfox 生成的元素图 → 抠白底 → 缩放 → 不透明贴到原图空白处 → 校验

保证：
  - 输出尺寸与原图完全一致
  - 主体（产品/人物/配件）像素零改动（元素框外）
  - 元素四边 alpha = 0（无硬边）
  - 不加任何投影

用法：
  python make_main_image.py --base 原图.jpg --prop 元素.jpg --out 成品.jpg \
      --size 300 --spot 590,50

  # 不知道放哪，先扫空白分布
  python make_main_image.py --base 原图.jpg --scan
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


# ---------------- 抠图 ----------------

def cutout_white_bg(path, tol=60, feather=4, erode=2):
    """
    把白底物体抠出来。用 floodfill 从四角吃背景，
    因为生成图的"白底"常是 238~247 的渐变，固定阈值切不干净。

    返回 (RGBA 图, 边缘 alpha 报告 dict)
    """
    orig = Image.open(path).convert("RGB")
    w, h = orig.size
    pad = 20
    canvas = Image.new("RGB", (w + pad * 2, h + pad * 2), (255, 255, 255))
    canvas.paste(orig, (pad, pad))

    MARK = (255, 0, 255)
    for seed in [(0, 0), (canvas.width - 1, 0),
                 (0, canvas.height - 1), (canvas.width - 1, canvas.height - 1)]:
        ImageDraw.floodfill(canvas, seed, MARK, thresh=tol)

    arr = np.array(canvas).astype(int)
    is_mark = (arr[:, :, 0] > 240) & (arr[:, :, 1] < 30) & (arr[:, :, 2] > 240)
    alpha = np.where(is_mark, 0, 255).astype(np.uint8)

    a = Image.fromarray(alpha, "L")
    if erode > 0:
        a = a.filter(ImageFilter.MinFilter(erode * 2 + 1))   # 腐蚀，防贴边
    a = a.filter(ImageFilter.GaussianBlur(feather))
    a = a.crop((pad, pad, pad + w, pad + h))

    # ★ RGB 用原图，绝不能用被洋红污染的 canvas
    rgba = orig.convert("RGBA")
    rgba.putalpha(a)

    aa = np.array(a)
    report = {
        "top": int(aa[0, :].max()), "bottom": int(aa[-1, :].max()),
        "left": int(aa[:, 0].max()), "right": int(aa[:, -1].max()),
    }

    bbox = rgba.getbbox()
    if bbox:
        rgba = rgba.crop(bbox)
    return rgba, report


# ---------------- 空白扫描 ----------------

def scan_white(base_path, step=40, min_size=160, max_size=520, thresh_ratio=0.985):
    """滑动窗口找最大的全白正方形，用积分图加速"""
    im = Image.open(base_path).convert("RGB")
    a = np.array(im)
    H, W = a.shape[:2]
    white = (a.min(axis=2) >= 246).astype(np.int64)
    ii = white.cumsum(0).cumsum(1)

    def white_ratio(x1, y1, x2, y2):
        s = ii[y2 - 1, x2 - 1]
        if x1 > 0:
            s -= ii[y1 - 1, x2 - 1]
        if y1 > 0:
            s -= ii[y2 - 1, x1 - 1]
        if x1 > 0 and y1 > 0:
            s += ii[y1 - 1, x1 - 1]
        return s / ((x2 - x1) * (y2 - y1))

    best = (0, 0, 0)
    for size in range(min_size, max_size + 1, 20):
        for y in range(0, H - size, step):
            for x in range(0, W - size, step):
                if white_ratio(x, y, x + size, y + size) >= thresh_ratio:
                    if size > best[2]:
                        best = (x, y, size)
    return {"image": [W, H], "spot": best}


# ---------------- 合成 ----------------

def compose(base_path, prop, spot, size, out_path, jpeg_quality=95):
    base = Image.open(base_path).convert("RGBA")
    W, H = base.size

    # 缩放元素
    sc = size / max(prop.size)
    prop = prop.resize((max(1, int(prop.size[0] * sc)),
                        max(1, int(prop.size[1] * sc))), Image.LANCZOS)

    px, py = spot
    # 边界保护
    px = max(0, min(px, W - prop.size[0]))
    py = max(0, min(py, H - prop.size[1]))

    res = base.copy()
    res.alpha_composite(prop, (px, py))     # 不加任何投影

    ext = os.path.splitext(out_path)[1].lower()
    if ext in (".jpg", ".jpeg"):
        res.convert("RGB").save(out_path, "JPEG", quality=jpeg_quality, optimize=True)
    else:
        res.save(out_path)

    # 校验
    a1 = np.array(base.convert("RGB")).astype(int)
    a2 = np.array(Image.open(out_path).convert("RGB")).astype(int)
    diff = np.abs(a1 - a2).sum(axis=2)
    box = np.zeros((H, W), bool)
    box[py:py + prop.size[1], px:px + prop.size[0]] = True
    changed_total = int((diff > 6).sum())
    changed_outside = int(((diff > 6) & (~box)).sum())

    return {
        "size_original": [W, H],
        "size_output": list(Image.open(out_path).size),
        "elem_size": list(prop.size),
        "elem_pos": [px, py],
        "elem_ratio": round(prop.size[0] * prop.size[1] / (W * H) * 100, 2),
        "changed_total_ratio": round(changed_total / (W * H) * 100, 2),
        "changed_outside_px": changed_outside,
        "filesize_kb": os.path.getsize(out_path) // 1024,
    }


# ---------------- CLI ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="原图（主图）")
    ap.add_argument("--prop", help="元素图（白底物体）")
    ap.add_argument("--out", help="输出路径")
    ap.add_argument("--size", type=int, default=300, help="元素长边像素，默认 300")
    ap.add_argument("--spot", default="", help="元素左上角 x,y")
    ap.add_argument("--tol", type=int, default=60, help="floodfill 容差，默认 60")
    ap.add_argument("--scan", action="store_true", help="只扫描空白分布")
    args = ap.parse_args()

    if args.scan:
        r = scan_white(args.base)
        x, y, s = r["spot"]
        print(f"图 {r['image'][0]}x{r['image'][1]}")
        print(f"最大全白正方形：({x},{y}) 边长 {s}px → 可放 {int(s*0.9)}px 元素")
        print("\n⚠️ 必须人眼复核：这块白是否在某个圆形/异形产品的轮廓内部")
        return 0

    if not (args.prop and args.out):
        print("需要 --prop 和 --out（或用 --scan 只扫描）", file=sys.stderr)
        return 2

    prop, edge = cutout_white_bg(args.prop, tol=args.tol)
    print(f"抠图后 {prop.size}")
    print(f"四边 alpha: 上{edge['top']} 下{edge['bottom']} "
          f"左{edge['left']} 右{edge['right']}"
          + ("  ✅ 无硬边" if max(edge.values()) == 0 else "  ❌ 有硬边！"))

    if args.spot:
        spot = tuple(int(v) for v in args.spot.split(","))
    else:
        x, y, s = scan_white(args.base)["spot"]
        spot = (x + s // 10, y + s // 10)
        print(f"自动选位 ({x},{y}) 空白 {s}px → 贴 {spot}")

    r = compose(args.base, prop, spot, args.size, args.out)

    print(f"\n✅ {args.out} ({r['filesize_kb']} KB)")
    print(f"   原图 {r['size_original'][0]}x{r['size_original'][1]} | "
          f"输出 {r['size_output'][0]}x{r['size_output'][1]}"
          + ("  ✅ 尺寸一致" if r["size_original"] == r["size_output"] else "  ❌ 尺寸变了！"))
    print(f"   元素 {r['elem_size'][0]}x{r['elem_size'][1]} @ {tuple(r['elem_pos'])} "
          f"占画面 {r['elem_ratio']}%")
    print(f"   整体改动 {r['changed_total_ratio']}% | "
          f"框外改动 {r['changed_outside_px']} px"
          + ("  ✅ 主体零改动" if r["changed_outside_px"] < 20 else "  ⚠️ 压到主体了"))

    ok = (r["size_original"] == r["size_output"]
          and max(edge.values()) == 0
          and r["changed_outside_px"] < 20)
    print("\n" + ("🎉 三项硬指标全部通过" if ok else "⚠️ 有指标未通过，检查上面的输出"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
