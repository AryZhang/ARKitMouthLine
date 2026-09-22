# ARKit Mouth Line Binder

面向 Blender 三渲二角色的 ARKit 52 嘴角装饰线生成插件。输入默认表情下已经摆放正确的一侧月牙嘴角线，插件会自动识别左右、生成镜像月牙，并把两侧月牙合并进一个保留 ARKit 52 的非破坏性导出网格。

当前公开版本：**1.0.0**

## 下载

[直接下载 Blender 插件 ARKitMouthLine-1.0.0.zip](../../releases/download/v1.0.0/ARKitMouthLine-1.0.0.zip)

下载后不需要解压，直接从 Blender 安装 ZIP。

## 环境要求

- Blender 4.2 或更高版本。
- 一个包含 ARKit 52 Shape Keys 的面部 Mesh。
- 一条已经在默认表情下摆放正确的独立月牙 Line Mesh。
- Line 只需要制作一侧；不需要预先制作镜像、Shape Keys、Driver 或辅助骨骼。

## 安装

1. 打开 Blender。
2. 进入 `Edit > Preferences > Add-ons`。
3. 点击右上角菜单，选择 `Install from Disk...`。
4. 选择下载的 `ARKitMouthLine-1.0.0.zip`。
5. 启用 `ARKit Mouth Line Binder`。
6. 回到 3D Viewport，按 `N` 打开侧栏，在 `ARKit Mouth Line` 标签中使用插件。

## 输入准备

1. 让角色 Body 处于默认表情，所有 ARKit Shape Key 值归零。
2. 制作左侧或右侧的一条完整月牙实体线，并保持为独立 Mesh 对象。
3. 把 Line 摆放到最终默认位置；插件会直接使用它当前的位置和形状。
4. Line 不要放在嘴部正中，否则插件无法可靠判断它属于哪一侧。
5. Body 和 Line 都应处于 Object Mode。

## 使用流程

1. 在 `Face Body` 中选择包含 ARKit 52 的面部对象。
2. 在 `Mouth Line` 中选择输入月牙对象。
3. 设置输出名称；默认是 `Body_ARKit_Line`。
4. 点击 `Scan ARKit Mouth Keys`，确认检测到 `28/28` 个嘴部相关键。
5. 点击 `Build / Rebuild Export Copy`。
6. 点击 `Validate` 检查顶点数、Shape Keys、左右识别、Driver 和 Armature 状态。
7. 导出或使用生成的 `Body_ARKit_Line`；原始 Body 和 Line 会保持不变。

## 输出内容

- 一个包含 Body 与左右月牙的单一 Mesh。
- 保留原始 ARKit 52 Shape Keys。
- 新增 `mouthLineLengthLeft` 和 `mouthLineLengthRight`。
- 两个长度键默认值为 `1`；设为 `0` 时，对应月牙收缩到嘴角根部。
- 左右长度可以分别控制，不会串扰。
- 输出不使用 Blender Driver，也不会创建辅助骨骼。
- 输出对象记录源对象、自动识别侧、镜像侧、插件版本和对称校正状态。

## 表情跟随逻辑

- 默认月牙会沿检测到的面部对称平面精确镜像。
- 每侧月牙在一个 Shape Key 内使用统一位移，因此月牙不会被局部拉伸。
- `jawOpen`、`mouthPucker` 等双侧键会进行左右对称校正。
- `mouthSmileLeft/Right`、`mouthFrownLeft/Right` 等成对键会跨键校正；左右权重相同时得到对称结果，单侧权重仍然只表现对应一侧。
- `mouthLeft`、`mouthRight` 以及单独的 Left/Right 表情本来就是非对称状态。

## 已知限制

- 1.0.0 使用嘴角锚点的统一平移来保持月牙形状。在 `jawOpen` 这类嘴角、嘴唇和脸颊发生明显非刚性变形的表情中，月牙可能离开默认状态下对应的局部皮肤区域。
- 只使用普通 Shape Keys 时，无法同时保证“每个顶点始终完全贴面”和“月牙在所有中间值下绝对保持刚体”。后续版本会继续优化局部表面跟随。
- 如果 Body 的 ARKit 键命名与标准名称差异过大，扫描可能无法识别。

## 重新调整

如果默认位置不正确，请直接移动或编辑原始 Line，然后再次点击 `Build / Rebuild Export Copy`。插件不会修改原始 Body 或 Line。

## 仓库结构

```text
arkit_mouth_line/
  __init__.py       Blender 插件源码
README.md           安装和使用说明
```
