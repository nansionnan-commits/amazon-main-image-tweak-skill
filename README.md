# 主图去重微改 Skill

> 不能直接拿别人的原图当主图（影响权重）→ 加一个元素制造差异。
> **原图尺寸不变、主体像素零改动、元素不透明无阴影无硬边。**

## 一句话流程

```
linkfox 生成独立元素（白底无阴影）
→ floodfill 抠图（四边 alpha=0）
→ Pillow 不透明贴到原图空白处
→ 校验：尺寸不变 / 框外改动 0
```

## 快速开始

```bash
cd scripts

# ① 不知道放哪，先扫空白
python make_main_image.py --base "原图.jpg" --scan

# ② 一键合成
python make_main_image.py \
    --base "原图.jpg" \
    --prop "元素.jpg" \
    --out "成品.jpg" \
    --size 320 \
    --spot 590,50
```

输出会打印三项硬指标：

```
四边 alpha: 上0 下0 左0 右0  ✅ 无硬边
原图 1789x1839 | 输出 1789x1839  ✅ 尺寸一致
整体改动 1.64% | 框外改动 8 px  ✅ 主体零改动
🎉 三项硬指标全部通过
```

## 三条硬禁止

1. 元素不许半透明/虚化/渐变
2. 绝不扩画布
3. 不加任何投影

## 关键认知

**linkfox 的 AI 生成模型做不到"只加元素"**：输出尺寸随机、产品被重画、人物姿势会变、还会加别人品牌。
**AI 只用来生成独立元素，合成必须用 Pillow。**

## 实测案例

`examples/`：
- `example-original.jpg` — 原图（1789×1839，含人物+产品+配件）
- `example-prop-yarn-ball.jpg` — linkfox 生成的毛线球（白底无阴影）
- `example-result-moto-belt-lint-remover.jpg` — 成品（加毛线球，改动 1.64%）
