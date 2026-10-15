# 伪 3D 视差壁纸 — 深度图路线

之前用 ImageGen 拆"前景地板/中景设施/背景穹顶"3 张独立 PNG，再用 alpha_composite 叠——AI 没法保证对齐，**叠出来会错位（家具悬空、地板过大）**。

新路线：**保留原连贯壁纸 + 配套一张灰度深度图**，让 Wallpaper Engine 用"Depth Map Parallax"模式自动生成视差。**不再需要切层，对齐天然正确**。

## 文件清单

| 文件 | 内容 |
|---|---|
| `bug_room_wallpaper_1920x1080.png` | 主图（连贯房间）— **当前桌面壁纸** |
| `bug_room_native_1536x1024.png` | 主图原生版（1536×1024） |
| `depth_map_FHD.png` | 1920×1080 灰度深度图（亮=近，暗=远） |
| `depth_map_native.png` | 1536×1024 灰度深度图 |

## 深度图怎么生成

不是 AI 出的，是程序按 Y 轴分 3 段生成的灰度渐变（和原图严格对齐）：

| Y 区域 | 灰度值 | 对应原图内容 |
|---|---|---|
| 顶部 ~25% | 0–90（暗） | 穹顶+远山雾 |
| 中部 ~30% | 90–180（中） | 玻璃墙+食堂+训练区+睡窝 |
| 底部 ~45% | 180–255（亮） | 前景地板（虫子走的区域） |

## Wallpaper Engine 配视差（推荐）

1. Wallpaper Engine → "Create wallpaper" → "Image"
2. 选 `bug_room_wallpaper_1920x1080.png` 作主图
3. 右侧 "Effects" 面板 → 启用 **"Depth Map Parallax"**
4. 上传 `depth_map_FHD.png` 作为深度图源
5. 调 "Parallax intensity"：建议 30-50（越大动得越狠）
6. "Apply" 应用

鼠标动 → Wallpaper Engine 按深度图把亮处（地板）多移、暗处（穹顶）少移 → 真 3D。虫子站在地板层，会感觉自己在前景，背景向后推。

## 不要用旧的分层 PNG

`parallax/` 文件夹里的 `01_foreground_floor.png` / `02_midground_structure.png` / `03_background_dome.png` 是失败的尝试，**层之间错位明显，不要拿来用**。保留仅作存档。

如果不想用 Wallpaper Engine：直接用当前桌面壁纸就够了（已经是连贯的 FHD 版）。