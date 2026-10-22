---
name: amazon-main-image-tweak
description: 亚马逊主图去重微改 —— 不能直接拿别人的原图当主图（影响权重），要在原图上加一个"一眼能联想到产品"的元素制造差异。做法是 linkfox 生成独立元素 + Pillow 精确合成：原图尺寸不变、产品/人物像素零改动、元素不透明无阴影无硬边。当用户提到主图微调、主图去重、换个主图、图片不能一样、main image tweak 时触发。
---

# 主图去重微改

> ## 唯一目的
> **不能拿别人的原图直接当主图，会影响权重。**
> 在原图上加一个元素，让图跟原图不一样就行。

---

## 🔴 核心结论（2026-10-22 实测，别再走弯路）

**linkfox 的 AI 生成模型做不到"只加元素"。**

| 问题 | 实测表现 |
|---|---|
| 输出尺寸不可控 | 1789×1839 → **920×504**（宽幅）或 2816×1536，随机 |
| 产品被重画 | 底部凭空多出椭圆灯窗、罩子纹理改变、刀片变滤网 |
| 人物姿势被改 | 低头看手 → 摸头发大头像 |
| 会加别人的品牌 | BANANA_2 给产品打上 "Holiro" |

**⇒ 所以：AI 只用来生成"独立的元素"，合成必须用 Pillow 精确贴。**

---

## 完整流程（5 步）

### 第 1 步：判断这张图能不能做

| 图类型 | 可用空白 | 建议 |
|---|---|---|
| 单品居中 + 大面积白 | 充足 | ✅ 最佳 |
| 单品 + 简单背景 | 一般 | ✅ 可以做 |
| 多元素拼贴（人+产品+配件）| 很少 | ⚠️ 元素只能 250~320px |
| 满版场景 | 无 | ❌ 不做 |

**⚠️ 致命陷阱**：白像素检测**分不清"背景白"和"产品轮廓内的白"**。
圆形/异形产品（如透明圆盖）内部有大片白，算法会判为空白 → **必须人眼复核位置**。

### 第 2 步：选元素（最关键）

> 老板原话：**"元素选择是重点，要让人一眼就能联想到这个产品。"**
> 可以是**卡通元素**，也可以是**缩小的实物 / 缩小的物品**。

| 产品 | ✅ 好元素 | ❌ 差元素 |
|---|---|---|
| 除毛器 / 剃毛球 | **毛线球**、针织毛衣一角 | 一朵花、一个杯子 |
| 保温窗帘 | 窗框一角、雪花、温度计 | 一棵树 |
| 宠物窝 | 猫/狗玩偶、爪印、毛球 | 一盆绿植 |
| 焊接夹 | 焊条、小铁件、火花 | 螺丝刀 |
| 挂壁置物架 | 迷你小盆栽、迷你书本 | 台灯 |
| 双肩包 / 胸包 | 缩小行李箱、地图折角 | 咖啡杯 |
| 头灯 | 迷你帐篷、登山扣 | 手机 |
| 打孔器 | 迷你卡纸碎片、邮票 | 剪刀 |

完整对照表见 `references/product-prop-map.md`。

### 第 3 步：linkfox 生成独立元素

```
mcp__linkfox__proxy_call
  toolName: "aigc/imageGenAsync"        ← 大小写敏感
  arguments: {
    prompt, provider: "BANANA_PRO",
    resolution: "2K", outputNum: 1
  }
→ taskId

mcp__linkfox__proxy_call
  toolName: "aigc/taskQuery"
  arguments: { taskId }
→ status: SUCCESS，图在 resultList[].url
```

**prompt 模板（必须包含 NO shadow 那段）**：

```
A single {物体}, about {尺寸}, {姿态}.
Isolated object on PURE WHITE background (RGB 255,255,255).

CRITICAL: NO shadow at all. No ground shadow, no contact shadow,
no drop shadow, no darkening under the object. The object must sit on
completely uniform flat white with zero shading around it, as if cut out.

Studio lighting, even illumination, sharp focus on {材质} texture,
45 degree top-down view.
No text, no watermark, no logo, no hands, no props, no reflection.
```

**⚠️ 生成图的白底常是 238~247 的渐变**（不是纯 255），所以后面必须用 floodfill 抠，不能用固定阈值。

`AIDRAW_EDIT`（Linkfox-Image-1）需要 **2K 起**，1K 会报 `不支持分辨率 1K`；且该服务当前返回 `图片生成失败`，暂不可用。

### 第 4 步：抠图 + 合成（一条命令）

```bash
cd scripts

# 一键：抠图 → 缩放 → 贴到指定位置 → 保存
python make_main_image.py \
    --base "原图.jpg" \
    --prop "元素.jpg" \
    --out "成品.jpg" \
    --size 300 \
    --spot 590,50
```

**抠图算法（floodfill，这是唯一可靠的）**：

```python
canvas = 原图 + 20px 白边        # 保证四角一定是背景
四角 ImageDraw.floodfill(canvas, seed, (255,0,255), thresh=60)
alpha = where(是洋红, 0, 255)
alpha = MinFilter(5) → GaussianBlur(4)     # 腐蚀 2px + 羽化，防硬边

# ★ RGB 必须用原图，不能用被洋红污染的 canvas，否则边缘泛洋红
rgba = 原图.convert("RGBA"); rgba.putalpha(alpha)
```

### 第 5 步：验收（三项硬指标）

| 指标 | 门槛 | 怎么查 |
|---|---|---|
| **输出尺寸** | **必须与原图完全相同** | `Image.open(out).size` |
| **四边 alpha** | **必须全 0** | 抠图后 `alpha[0,:].max()` 等 |
| **框外改动** | **≈ 0**（JPEG 噪声 <20 像素）| 逐像素 diff，排除元素框 |

**元素框外如果改了几千像素 → 说明压到主体了，位置错了。**

---

## 三条硬禁止

| # | 禁止 | 原因 |
|---|---|---|
| **1** | 元素不许半透明/虚化/渐变 | 变成"飘着的虚影"，很丑 |
| **2** | 绝不扩画布 | 产品占比下降，构图失真 |
| **3** | 不加任何投影 | 投影图层矩形边界会露出直边，Amazon 会禁显 |

**硬边三个来源**：① 裁剪框切到物体 ② 元素自带阴影被抠进来 ③ 自己加的投影图层边界

---

## 实测案例（除毛器，2026-10-22）

| 版本 | 做法 | 结果 |
|---|---|---|
| v1 | BANANA_PRO 整图重绘 | ❌ 产品变形、人物丢失 |
| v2 | 扩画布 ×1.5 | ❌ 像贴纸，占比降到 65% |
| v3 | 裁原图毛衣 + 半透明渐变 | ❌ "飘着的虚影" |
| v4 | 合成 + 自带阴影 | ❌ 底部一条直边 |
| v6 | BANANA_PRO 详细描述 | ⚠️ 产品/人物保留，但**尺寸变 920×504**，产品多了灯窗 |
| **v7** | **合成 + 无阴影元素** | ✅ **尺寸 1789×1839 不变，主体零改动，改动 1.64%** |

**最终参数**：元素 320px，贴 (590, 50)，原图 1789×1839。

---

## 目录

```
SKILL.md                        本文件
references/product-prop-map.md  产品→元素对照表
scripts/make_main_image.py      一键：抠图 + 合成 + 校验
scripts/place_prop.py           分步合成（可指定 corner / shadow）
scripts/composite_prop.py       空白检测 / 裁元素
examples/                       实测样图
```
