# Blackhole PoC — Metal 两-pass 后处理验证

## 目标
验证「在 Warp 的 Metal 渲染器里加黑洞后处理」的三个真实技术风险，**不依赖 Xcode、不碰 Warp 源码**（headless Metal + 运行时编译 shader）。

## 待验证风险点（来自对 `crates/warpui/.../metal/renderer.rs` 的分析）
1. **两-pass 渲染可行性**：场景 → 离屏 BGRA8 纹理（blend on）→ 合成 pass 采样（blend off）→ 输出纹理。验证 BGRA8 格式 + `RenderTarget|ShaderRead` usage 的离屏纹理能被后续 pass 采样。
2. **flip-Y / UV 朝向**：用非对称标记（左上白块 + 中间红条）检测合成后图像是否上下/左右颠倒。
3. **合成 blend 必须关**：清成 magenta 的输出纹理 + 半透明探针方块，断言回读为探针纯色（未被 magenta 混色），证明 blend-off 生效。

## 架构
```
Pass1 (scene,  blend ON):  fullscreen tri → scene_tex (BGRA8, Shared, RT|ShaderRead)
Pass2 (composite, blend OFF): fullscreen tri 采样 scene_tex → 反色 + 径向透镜(warp 可调) → out_tex
CPU get_bytes 回读两个纹理 → 断言 + 导出 PNG
```

## 验证标准（PASS 条件，全部满足才算通过）
- [ ] A: scene_tex 左上区域为白（标记在预期位置，场景 pass 朝向正确）
- [ ] B: out_tex（warp=0 纯反色）左上区域为「反色后的暗色」且位置仍在左上 → 合成未翻转
- [ ] C: out_tex 探针方块回读 == 探针纯色（blend-off 证明）
- [ ] D: out_tex 无残留 magenta（全屏被覆盖）
- [ ] E: warp=1 的黑洞 PNG 成功导出且进程不崩溃

## Uniform 布局（Metal，16 字节对齐）
- Scene: `{ float2 size }`
- Composite: `{ float2 size; float warp_amount; float probe }`

## 非目标（本次不做）
- 不集成进 Warp（那一步需要装 Xcode，另行确认）
- 不接 Claude Code context 数据通道（PoC 用固定 uniform）
- 不做真实吸积盘/光子环（只做径向透镜雏形）
