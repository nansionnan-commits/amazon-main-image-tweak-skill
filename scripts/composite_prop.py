#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把元素图叠加到原图空白角落（原图其他像素 100% 不动）

与「生成模型重绘」的本质区别：
  - 本脚本只做 alpha 合成，原图未被覆盖的区域逐像素完全相同
  - 不存在"产品被重画"的可能

用法：
  # 1) 找空白区域（给出建议位置）
  python composite_prop.py find-space "D:/图/main.jpg"

  # 2) 合成（元素图需带 alpha 通道的 PNG）
  python composite_prop.py paste --base "D:/图/main.jpg" --prop "D:/图/prop.png" \
      --corner lower-left --scale 0.22 --out "D:/图/out.jpg"

  # 3) 从原图裁一块做元素（无外部素材时的应急方案）
  python composite_prop.py crop-prop --base "D:/图/main.jpg" \
      --box 1200,900,1500,1100 --feather 40 --out "D:/图/prop.png"
"""
import argparse
import json
import os
import sys

try:
    from PIL import Image, ImageFilter
except ImportError:
    print("需要 Pillow：pip install pillow", file=sys.stderr)
    sys.exit(2)


# ---------- 空白检测 ----------

def find_space(path, grid=12, thresh=245, min_block=3):
    """粗网格扫描，找出"接近纯色"的连续区域"""
    im = Image.open(path).convert("RGB")
    w, h = im.size
    cw, ch = w // grid, h // grid
    mat = []
    for gy in range(grid):
        row = []
        for gx in range(grid):
            box = (gx * cw, gy * ch, (gx + 1) * cw, (gy + 1) * ch)
            crop = im.crop(box).resize((8, 8))
            px = list(crop.getdata())
            mean = tuple(sum(c[i] for c in px) // len(px) for i in range(3))
            # 方差
            var = sum(abs(c[i] - mean[i]) for c in px for i in range(3)) / (len(px) * 3)
            row.append({"mean": mean, "var": round(var, 1),
                        "white": min(mean) >= thresh and var < 12})
        mat.append(row)
    return {"size": [w, h], "grid": grid, "matrix": mat}


def cmd_find(args):
    r = find_space(args.path)
    w, h = r["size"]
    grid = r["grid"]
    print(f"图 {w}x{h}，{grid}x{grid} 网格空区分布（# = 空白）：\n")
    for gy, row in enumerate(r["matrix"]):
        line = ""
        for gx, cell in enumerate(row):
            line += " # " if cell["white"] else " . "
        print(f"  行{gy:>2} |{line}|")
    print()
    # 四角评分
    corners = {
        "upper-left": [(0, 0), (1, 0), (0, 1), (1, 1)],
        "upper-right": [(grid - 1, 0), (grid - 2, 0), (grid - 1, 1), (grid - 2, 1)],
        "lower-left": [(0, grid - 1), (1, grid - 1), (0, grid - 2), (1, grid - 2)],
        "lower-right": [(grid - 1, grid - 1), (grid - 2, grid - 1), (grid - 1, grid - 2), (grid - 2, grid - 2)],
    }
    print("四角空白率：")
    best, bestv = None, -1
    for name, cells in corners.items():
        cnt = sum(1 for x, y in cells if r["matrix"][y][x]["white"])
        pct = cnt / len(cells)
        print(f"  {name:<14} {pct:.0%}")
        if pct > bestv:
            best, bestv = name, pct
    print(f"\n👉 建议放元素的位置：**{best}**（空白率 {bestv:.0%}）")
    if bestv < 0.5:
        print("⚠️ 该图四角都不够空，建议改用 crop-prop 从原图裁元素，或换一张图")
    return 0


# ---------- 从原图裁元素 ----------

def cmd_crop(args):
    x1, y1, x2, y2 = [int(v) for v in args.box.split(",")]
    im = Image.open(args.base).convert("RGBA")
    prop = im.crop((x1, y1, x2, y2))
    # 羽化边缘
    mask = Image.new("L", prop.size, 255)
    mask = mask.filter(ImageFilter.GaussianBlur(args.feather))
    prop.putalpha(mask)
    prop.save(args.out)
    print(f"✅ 元素图已保存 {args.out}（{prop.size[0]}x{prop.size[1]}，羽化 {args.feather}px）")
    return 0


# ---------- 合成 ----------

CORNER_ANCHOR = {
    "upper-left": ("left", "top"),
    "upper-right": ("right", "top"),
    "lower-left": ("left", "bottom"),
    "lower-right": ("right", "bottom"),
}


def cmd_paste(args):
    base = Image.open(args.base).convert("RGBA")
    prop = Image.open(args.prop).convert("RGBA")
    W, H = base.size

    # 按比例缩放元素
    target = int(min(W, H) * args.scale)
    scale = target / max(prop.size)
    prop = prop.resize((max(1, int(prop.size[0] * scale)),
                        max(1, int(prop.size[1] * scale))), Image.LANCZOS)

    if args.opacity < 100:
        a = prop.split()[-1].point(lambda p: int(p * args.opacity / 100))
        prop.putalpha(a)

    if args.blur > 0:
        prop = prop.filter(ImageFilter.GaussianBlur(args.blur))

    hx, vy = CORNER_ANCHOR[args.corner]
    margin = int(min(W, H) * args.margin)
    x = margin if hx == "left" else W - prop.size[0] - margin
    y = margin if vy == "top" else H - prop.size[1] - margin

    # 关键：只在元素区域内做 alpha 合成，其余像素保持原样
    out = base.copy()
    out.alpha_composite(prop, (x, y))

    ext = os.path.splitext(args.out)[1].lower()
    if ext in (".jpg", ".jpeg"):
        out.convert("RGB").save(args.out, "JPEG", quality=args.quality, optimize=True)
    else:
        out.save(args.out)

    print(f"✅ 合成完成 {args.out}")
    print(f"   原图 {W}x{H} | 元素 {prop.size[0]}x{prop.size[1]} | 位置 {args.corner} @({x},{y})")
    print(f"   元素占画面 {(prop.size[0]*prop.size[1])/(W*H):.1%}")
    print("   ⚠️ 原图其他区域像素 100% 保留（alpha_composite 只影响贴图区域）")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("find-space", help="检测空白区域")
    p1.add_argument("path")
    p1.set_defaults(func=cmd_find)

    p2 = sub.add_parser("crop-prop", help="从原图裁一块做元素")
    p2.add_argument("--base", required=True)
    p2.add_argument("--box", required=True, help="x1,y1,x2,y2")
    p2.add_argument("--feather", type=int, default=40)
    p2.add_argument("--out", required=True)
    p2.set_defaults(func=cmd_crop)

    p3 = sub.add_parser("paste", help="合成到角落")
    p3.add_argument("--base", required=True)
    p3.add_argument("--prop", required=True)
    p3.add_argument("--corner", default="lower-left", choices=list(CORNER_ANCHOR))
    p3.add_argument("--scale", type=float, default=0.22, help="元素占短边比例")
    p3.add_argument("--opacity", type=int, default=100)
    p3.add_argument("--blur", type=float, default=1.5)
    p3.add_argument("--margin", type=float, default=0.02)
    p3.add_argument("--quality", type=int, default=92)
    p3.add_argument("--out", required=True)
    p3.set_defaults(func=cmd_paste)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
