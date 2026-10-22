#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把「独立物体」不透明地放进原图空白区（带落地投影）

与半透明贴片的区别：
  - 元素 alpha 保持 255（完全不透明），只有 1~2px 边缘羽化防锯齿
  - 底部加真实投影，让物体"落在台面上"而不是"浮着"
  - 原图除空白区外像素零改动

用法：
  python place_prop.py --base "原图.jpg" --prop "白底物体.png" --out "结果.png"
  python place_prop.py --base ... --prop ... --spot 600,120 --size 240 --shadow 0.35
"""
import argparse
import os
import sys

from PIL import Image, ImageFilter, ImageDraw
import numpy as np


def cutout_white(prop_path, thresh=None, feather=2):
    """
    把白底物体抠出来。thresh=None 时自动按边缘亮度推断
    （生成图的白底常有 238~247 的渐变，固定 242 会抠不干净）
    """
    im = Image.open(prop_path).convert("RGBA")
    arr = np.array(im)
    rgb = arr[:, :, :3].astype(int)
    mn = rgb.min(axis=2)

    if thresh is None:
        # 用四周 8% 边框的中位数当作背景亮度，再减 8 作为阈值
        h, w = mn.shape
        band = max(4, int(min(h, w) * 0.08))
        edge = np.concatenate([mn[:band, :].ravel(), mn[-band:, :].ravel(),
                               mn[:, :band].ravel(), mn[:, -band:].ravel()])
        bg = int(np.median(edge))
        thresh = max(200, bg - 8)
        print(f"  自动背景亮度 {bg} → 抠图阈值 {thresh}")

    is_bg = mn >= thresh
    alpha = np.where(is_bg, 0, 255).astype(np.uint8)

    # 只保留最大的不透明连通块（去掉零散噪点）
    try:
        from scipy import ndimage
        lab, n = ndimage.label(alpha > 0)
        if n > 1:
            sizes = ndimage.sum(alpha > 0, lab, range(1, n + 1))
            keep = int(np.argmax(sizes)) + 1
            alpha = np.where(lab == keep, alpha, 0).astype(np.uint8)
    except ImportError:
        pass

    a = Image.fromarray(alpha, "L").filter(ImageFilter.GaussianBlur(feather))
    im.putalpha(a)
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)
    return im


def find_spot(base_arr, start_xy, max_size=420, step=10, tol=0.004):
    """从指定点贪心扩正方形，只在全白区域内"""
    H, W = base_arr.shape[:2]
    white = base_arr.min(axis=2) >= 246
    cx, cy = start_xy
    size = 40
    best = 40
    while size < max_size:
        x2, y2 = cx + size, cy + size
        if x2 >= W or y2 >= H:
            break
        if white[cy:y2, cx:x2].mean() < (1 - tol):
            break
        best = size
        size += step
    return cx, cy, best


def add_shadow(canvas, prop, pos, blur=18, opacity=0.28, offset=(0, 6)):
    """在物体下方画柔和椭圆投影"""
    w, h = prop.size
    pad = blur * 3
    sw, sh = w + pad * 2, h + pad * 2
    sh_img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
    d = ImageDraw.Draw(sh_img)
    # 椭圆比物体略扁、略窄
    ex1 = pad + int(w * 0.12)
    ex2 = pad + int(w * 0.88)
    ey1 = pad + int(h * 0.66)
    ey2 = pad + int(h * 0.94)
    d.ellipse([ex1, ey1, ex2, ey2], fill=(90, 82, 74, int(255 * opacity)))
    sh_img = sh_img.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(sh_img, (pos[0] - pad + offset[0], pos[1] - pad + offset[1]))
    return canvas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--prop", required=True)
    ap.add_argument("--spot", default="", help="空白区左上角 x,y；留空则自动搜索")
    ap.add_argument("--size", type=int, default=0, help="元素长边像素；0=按空白区自动")
    ap.add_argument("--corner", default="auto", choices=["auto", "upper-left", "upper-right", "lower-left", "lower-right"])
    ap.add_argument("--thresh", type=int, default=0, help="抠图阈值，0=自动")
    ap.add_argument("--shadow", type=float, default=0.28, help="投影不透明度 0~1，0=不加")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    base = Image.open(args.base).convert("RGBA")
    arr = np.array(base.convert("RGB"))
    W, H = base.size
    print(f"原图 {W}x{H}")

    # 1) 抠出物体
    prop = cutout_white(args.prop, thresh=(args.thresh or None))
    print(f"抠图后 {prop.size}")

    # 2) 决定位置
    if args.spot:
        sx, sy = [int(v) for v in args.spot.split(",")]
    else:
        # 四个候选点，取能扩出最大空白区的那个
        cands = {
            "upper-left": (int(W*0.30), int(H*0.05)),
            "upper-right": (int(W*0.55), int(H*0.03)),
            "lower-left": (int(W*0.02), int(H*0.72)),
            "lower-right": (int(W*0.70), int(H*0.72)),
        }
        best, bs = None, -1
        for k, pt in cands.items():
            x, y, sz = find_spot(arr, pt)
            print(f"  候选 {k:<12} ({x},{y}) 可用 {sz}px")
            if sz > bs:
                best, bs, sx, sy = k, sz, x, y
        print(f"→ 选中 {best}，空白区 {bs}px @({sx},{sy})")

    x, y, size = find_spot(arr, (sx, sy))
    print(f"空白区 {size}px @({x},{y})")

    # 3) 缩放到空白区 82%
    target = args.size or int(size * 0.82)
    sc = target / max(prop.size)
    prop = prop.resize((max(1, int(prop.size[0]*sc)), max(1, int(prop.size[1]*sc))), Image.LANCZOS)

    # 4) 定位（在空白区内居中）
    px = x + (size - prop.size[0]) // 2
    py = y + (size - prop.size[1]) // 2
    px, py = max(0, px), max(0, py)

    # 5) 先投影，再不透明贴物体
    res = base.copy()
    if args.shadow > 0:
        res = add_shadow(res, prop, (px, py), opacity=args.shadow)
    res.alpha_composite(prop, (px, py))
    print(f"物体 {prop.size} 贴到 ({px},{py})，占比 {prop.size[0]*prop.size[1]/(W*H):.1%}")

    # 6) 保存 + 校验
    ext = os.path.splitext(args.out)[1].lower()
    if ext in (".jpg", ".jpeg"):
        res.convert("RGB").save(args.out, "JPEG", quality=95, optimize=True)
    else:
        res.save(args.out)
    print(f"✅ {args.out} ({os.path.getsize(args.out)//1024}KB)")

    a1 = np.array(base.convert("RGB")).astype(int)
    a2 = np.array(Image.open(args.out).convert("RGB")).astype(int)
    diff = np.abs(a1 - a2).sum(axis=2)
    # 只统计物体+投影外框之外的改动
    pad = 80
    box = np.zeros((H, W), bool)
    box[max(0,py-pad):min(H,py+prop.size[1]+pad), max(0,px-pad):min(W,px+prop.size[0]+pad)] = True
    outside = ((diff > 3) & (~box)).sum()
    print(f"\n🔍 框外改动像素: {outside}" + ("  ✅ 主体零改动" if outside == 0 else "  ⚠️ 有溢出"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
