//! Blackhole PoC: 验证 Metal 两-pass 后处理（离屏纹理 + 合成采样）。
//!
//! 目标：在不依赖 Xcode / 不修改 Warp 的前提下，验证三个风险点：
//! 1. 场景渲染到离屏 BGRA8 纹理 → 合成 pass 采样（格式/usage 可行）
//! 2. flip-Y / UV 朝向（非对称标记检测）
//! 3. 合成 blend 必须关闭（magenta 清屏 + 半透明探针）

use std::ffi::c_void;
use std::fs::File;
use std::io::BufWriter;
use std::mem;

use metal::*;

const W: u64 = 512;
const H: u64 = 512;

// ---- Uniform 布局（与 MSL 端保持一致）----
#[repr(C)]
#[derive(Clone, Copy)]
struct SceneUniforms {
    size: [f32; 2],
}

#[repr(C)]
#[derive(Clone, Copy)]
struct CompositeUniforms {
    size: [f32; 2],
    warp_amount: f32,
    probe: f32,
}

// ---- Metal Shading Language 源码（运行时编译，无需 Xcode）----
const SHADERS: &str = r#"
#include <metal_stdlib>
using namespace metal;

struct VOut {
    float4 position [[position]];
    float2 uv;
};

// 全屏三角形（y-down UV：uv.y=0 在顶部，与 get_bytes 行序、Warp 像素约定一致）
vertex VOut fullscreen_vertex(uint vid [[vertex_id]]) {
    float2 p = float2(float((vid << 1) & 2), float(vid & 2)); // (0,0) (2,0) (0,2)
    VOut o;
    o.position = float4(p * 2.0 - 1.0, 0.0, 1.0);
    // y-down UV：uv.x=p.x=(NDC.x+1)/2，uv.y=1-p.y，使 uv∈[0,1] 覆盖视口且 uv.y=0 在顶部
    // （匹配 get_bytes 行序与 Warp 像素约定；此前误写 p*0.5 导致视口只采样 uv∈[0,0.5]）
    o.uv = float2(p.x, 1.0 - p.y);
    return o;
}

struct SceneU { float2 size; };

// Pass1: 画一个「假终端」——渐变背景 + 左上白块标记 + 中间红条
fragment float4 scene_fragment(VOut in [[stage_in]],
                               constant SceneU& u [[buffer(0)]]) {
    float2 uv = in.uv;
    // 背景：深蓝 → 青 的竖向渐变
    float3 bg = mix(float3(0.05, 0.07, 0.18), float3(0.05, 0.20, 0.22), uv.y);
    float3 col = bg;
    // 左上标记白块（x<0.15 且 y<0.15）
    if (uv.x < 0.15 && uv.y < 0.15) col = float3(1.0, 1.0, 1.0);
    // 中间水平条（0.45<y<0.55），左半绿右半蓝，便于检测左右翻转
    if (uv.y > 0.45 && uv.y < 0.55) {
        col = (uv.x < 0.5) ? float3(0.1, 0.9, 0.1) : float3(0.1, 0.2, 0.95);
    }
    return float4(col, 1.0);
}

struct CompositeU { float2 size; float warp_amount; float probe; };

// Pass2: 采样场景纹理，径向透镜（黑洞雏形）+ 反色
fragment float4 composite_fragment(VOut in [[stage_in]],
                                   texture2d<float> scene_tex [[texture(0)]],
                                   constant CompositeU& u [[buffer(0)]]) {
    constexpr sampler s(address::clamp_to_edge, filter::linear);
    float2 uv = in.uv;

    // 径向透镜：把内容朝中心 (0.5,0.5) 拉拽，模拟引力透镜
    float2 center = float2(0.5, 0.5);
    float2 d = uv - center;
    float r = length(d);
    float strength = 0.18 * u.warp_amount;
    // 越靠近中心拉得越多（smoothstep 让边缘几乎不动）
    float pull = strength * smoothstep(0.75, 0.05, r);
    float2 suv = uv - normalize(d + 1e-6) * pull;
    suv = clamp(suv, 0.0, 1.0);

    float4 c = scene_tex.sample(s, suv);
    // 反色（最直观的后处理，验证采样正确）
    float3 col = 1.0 - c.rgb;

    // blend-off 探针：右下角小方块输出半透明灰；若 blend 误开会被 magenta 清屏混色
    if (u.probe > 0.5 && uv.x > 0.80 && uv.y > 0.80) {
        return float4(0.5, 0.5, 0.5, 0.5);
    }
    return float4(col, 1.0);
}

// 真正的黑洞：纯黑事件视界 + 吸积盘亮环 + 引力透镜弯曲背景
fragment float4 blackhole_fragment(VOut in [[stage_in]],
                                   texture2d<float> scene_tex [[texture(0)]],
                                   constant CompositeU& u [[buffer(0)]]) {
    constexpr sampler s(address::clamp_to_edge, filter::linear);
    float2 uv = in.uv;
    float2 center = float2(0.5, 0.5);
    float2 d = uv - center;
    float r = length(d);
    float2 dir = d / max(r, 1e-4);

    float r_shadow = 0.12;            // 事件视界阴影半径
    float r_ring   = r_shadow * 1.45; // 光子环/吸积盘内缘位置

    // --- 引力透镜：偏折量 ~1/r，把背景采样点沿径向外推，制造环绕弯曲 ---
    float bend = (r_shadow * r_shadow) / max(r, r_shadow * 0.5);
    float2 lens_uv = center + dir * (r + bend * 0.6 * u.warp_amount);
    lens_uv = clamp(lens_uv, 0.0, 1.0);
    float3 bg = scene_tex.sample(s, lens_uv).rgb;
    // 透镜区背景略微增亮，凸显弯曲
    float3 col = bg * (1.0 + 0.4 * smoothstep(0.5, r_ring, r) * u.warp_amount);

    // --- 吸积盘亮环：暖色，带多普勒增亮（左侧更亮，模拟相对论束流）---
    float ring = exp(-pow((r - r_ring) / 0.022, 2.0));
    float beam = 0.65 + 0.35 * (-dir.x);   // 左侧(dir.x<0)更亮
    float3 ring_color = float3(1.0, 0.62, 0.25) * beam;
    col += ring_color * ring * 2.4;
    // 内侧再叠一层更白更细的光子环
    float photon = exp(-pow((r - r_shadow * 1.08) / 0.006, 2.0));
    col += float3(1.0, 0.9, 0.75) * photon * 1.8;

    // --- 事件视界：阴影内部纯黑 ---
    float horizon = smoothstep(r_shadow * 1.0, r_shadow * 0.92, r);
    col = mix(col, float3(0.0), horizon);

    return float4(col, 1.0);
}
"#;

fn make_texture(device: &Device, w: u64, h: u64) -> Texture {
    let desc = TextureDescriptor::new();
    desc.set_width(w);
    desc.set_height(h);
    desc.set_pixel_format(MTLPixelFormat::BGRA8Unorm);
    desc.set_usage(MTLTextureUsage::RenderTarget | MTLTextureUsage::ShaderRead);
    // Shared：Apple Silicon 统一内存，GPU 渲染 + CPU get_bytes 回读都可用
    desc.set_storage_mode(MTLStorageMode::Shared);
    device.new_texture(&desc)
}

fn make_pipeline(
    device: &Device,
    library: &Library,
    frag_name: &str,
    blend_on: bool,
) -> RenderPipelineState {
    let vs = library
        .get_function("fullscreen_vertex", None)
        .unwrap_or_else(|e| panic!("vertex shader 编译失败: {e}"));
    let fs = library
        .get_function(frag_name, None)
        .unwrap_or_else(|e| panic!("{frag_name} 编译失败: {e}"));

    let desc = RenderPipelineDescriptor::new();
    desc.set_vertex_function(Some(&vs));
    desc.set_fragment_function(Some(&fs));
    let Some(attach) = desc.color_attachments().object_at(0) else {
        eprintln!("color attachment 0 必须存在");
        std::process::exit(1);
    };
    attach.set_pixel_format(MTLPixelFormat::BGRA8Unorm);
    if blend_on {
        // 与 Warp 场景 pipeline 一致的标准 alpha blend
        attach.set_blending_enabled(true);
        attach.set_source_rgb_blend_factor(MTLBlendFactor::SourceAlpha);
        attach.set_destination_rgb_blend_factor(MTLBlendFactor::OneMinusSourceAlpha);
        attach.set_source_alpha_blend_factor(MTLBlendFactor::One);
        attach.set_destination_alpha_blend_factor(MTLBlendFactor::OneMinusSourceAlpha);
        attach.set_rgb_blend_operation(MTLBlendOperation::Add);
        attach.set_alpha_blend_operation(MTLBlendOperation::Add);
    } else {
        // 合成 pass：不透明覆盖，blend 必须关
        attach.set_blending_enabled(false);
    }
    device
        .new_render_pipeline_state(&desc)
        .unwrap_or_else(|e| panic!("pipeline state 创建失败（检查像素格式一致性）: {e}"))
}

fn begin_pass<'a>(
    cb: &'a CommandBufferRef,
    tex: &TextureRef,
    clear: MTLClearColor,
) -> &'a RenderCommandEncoderRef {
    let rpd = RenderPassDescriptor::new();
    let Some(attach) = rpd.color_attachments().object_at(0) else {
        eprintln!("color attachment 0 必须存在");
        std::process::exit(1);
    };
    attach.set_texture(Some(tex));
    attach.set_load_action(MTLLoadAction::Clear);
    attach.set_store_action(MTLStoreAction::Store); // 必须 Store，否则后续 pass 读不到
    attach.set_clear_color(clear);
    let enc = cb.new_render_command_encoder(&rpd);
    enc.set_viewport(MTLViewport {
        originX: 0.0,
        originY: 0.0,
        width: W as f64,
        height: H as f64,
        znear: 0.0,
        zfar: 1.0,
    });
    enc
}

fn read_back(tex: &TextureRef) -> Vec<u8> {
    let mut buf = vec![0u8; (W * H * 4) as usize];
    let region = MTLRegion::new_2d(0, 0, W, H);
    tex.get_bytes(buf.as_mut_ptr() as *mut c_void, (W * 4) as u64, region, 0);
    buf
}

// BGRA 纹理 → [r,g,b,a]，x、y ∈ [0,1)
fn px(bgra: &[u8], x: f64, y: f64) -> [u8; 4] {
    let ix = (x * W as f64) as usize;
    let iy = (y * H as f64) as usize;
    let o = (iy * W as usize + ix) * 4;
    [bgra[o + 2], bgra[o + 1], bgra[o], bgra[o + 3]] // B,G,R,A → R,G,B,A
}

fn approx(a: u8, b: u8, tol: i32) -> bool {
    (a as i32 - b as i32).abs() <= tol
}

fn write_png(path: &str, bgra: &[u8]) -> std::io::Result<()> {
    let mut rgba = vec![0u8; bgra.len()];
    for i in (0..bgra.len()).step_by(4) {
        rgba[i] = bgra[i + 2];
        rgba[i + 1] = bgra[i + 1];
        rgba[i + 2] = bgra[i];
        rgba[i + 3] = 255;
    }
    let file = BufWriter::new(File::create(path)?);
    let mut encoder = png::Encoder::new(file, W as u32, H as u32);
    encoder.set_color(png::ColorType::Rgba);
    encoder.set_depth(png::BitDepth::Eight);
    let mut writer = encoder.write_header()?;
    writer.write_image_data(&rgba)?;
    Ok(())
}

fn main() {
    let Some(device) = Device::system_default() else {
        eprintln!("找不到 Metal 设备");
        std::process::exit(1);
    };
    println!("[i] Metal 设备就绪（headless）");

    let opts = CompileOptions::new();
    let library = device
        .new_library_with_source(SHADERS, &opts)
        .unwrap_or_else(|e| panic!("MSL 运行时编译失败: {e}"));

    let scene_pipeline = make_pipeline(&device, &library, "scene_fragment", true);
    let composite_pipeline = make_pipeline(&device, &library, "composite_fragment", false);
    let blackhole_pipeline = make_pipeline(&device, &library, "blackhole_fragment", false);

    let scene_tex = make_texture(&device, W, H);
    let out_tex = make_texture(&device, W, H);
    let queue = device.new_command_queue();

    // 运行一次「场景 + 合成」，ps 为合成 pipeline，warp/probe 可调，返回 out_tex 回读
    let run = |ps: &RenderPipelineState, warp: f32, probe: f32| -> Vec<u8> {
        let cb = queue.new_command_buffer();

        // Pass1: 场景 → scene_tex（清成黑）
        let enc = begin_pass(cb, &scene_tex, MTLClearColor::new(0.0, 0.0, 0.0, 1.0));
        enc.set_render_pipeline_state(&scene_pipeline);
        let su = SceneUniforms {
            size: [W as f32, H as f32],
        };
        enc.set_fragment_bytes(
            0,
            mem::size_of::<SceneUniforms>() as u64,
            &su as *const _ as *const c_void,
        );
        enc.draw_primitives(MTLPrimitiveType::Triangle, 0, 3);
        enc.end_encoding();

        // Pass2: 采样 scene_tex → out_tex（清成 magenta，用于 blend-off 检测）
        let enc2 = begin_pass(cb, &out_tex, MTLClearColor::new(1.0, 0.0, 1.0, 1.0));
        enc2.set_render_pipeline_state(ps);
        enc2.set_fragment_texture(0, Some(&scene_tex));
        let cu = CompositeUniforms {
            size: [W as f32, H as f32],
            warp_amount: warp,
            probe,
        };
        enc2.set_fragment_bytes(
            0,
            mem::size_of::<CompositeUniforms>() as u64,
            &cu as *const _ as *const c_void,
        );
        enc2.draw_primitives(MTLPrimitiveType::Triangle, 0, 3);
        enc2.end_encoding();

        cb.commit();
        cb.wait_until_completed();
        read_back(&out_tex)
    };

    // 确定性 pass：warp=0（纯反色，标记位置可预测）、probe=1
    let img = run(&composite_pipeline, 0.0, 1.0);

    // 单独渲染并回读 scene_tex，验证场景朝向
    let scene_rb = {
        let cb = queue.new_command_buffer();
        let enc = begin_pass(cb, &scene_tex, MTLClearColor::new(0.0, 0.0, 0.0, 1.0));
        enc.set_render_pipeline_state(&scene_pipeline);
        let su = SceneUniforms {
            size: [W as f32, H as f32],
        };
        enc.set_fragment_bytes(
            0,
            mem::size_of::<SceneUniforms>() as u64,
            &su as *const _ as *const c_void,
        );
        enc.draw_primitives(MTLPrimitiveType::Triangle, 0, 3);
        enc.end_encoding();
        cb.commit();
        cb.wait_until_completed();
        read_back(&scene_tex)
    };

    let mut pass = true;
    let mut check = |name: &str, ok: bool, detail: String| {
        println!(
            "{} {}  {}",
            if ok { "[PASS]" } else { "[FAIL]" },
            name,
            detail
        );
        if !ok {
            pass = false;
        }
    };

    // A: scene 左上应为白标记
    let s_tl = px(&scene_rb, 0.05, 0.05);
    check(
        "A  场景左上白标记",
        s_tl[0] > 240 && s_tl[1] > 240 && s_tl[2] > 240,
        format!("scene(0.05,0.05)=RGB{:?}", &s_tl[..3]),
    );
    // A2: 中间条左半绿、右半蓝（场景左右朝向正确）
    let s_ml = px(&scene_rb, 0.25, 0.50);
    let s_mr = px(&scene_rb, 0.75, 0.50);
    check(
        "A2 场景条左绿右蓝",
        s_ml[1] > 200 && s_mr[2] > 200,
        format!("左=RGB{:?} 右=RGB{:?}", &s_ml[..3], &s_mr[..3]),
    );

    // B: out（反色后）左上应为暗色（白→黑）→ 合成未上下翻转
    let o_tl = px(&img, 0.05, 0.05);
    let o_bl = px(&img, 0.05, 0.95);
    check(
        "B  合成左上=暗块(flip-Y 正确)",
        o_tl[0] < 30 && o_tl[1] < 30 && o_tl[2] < 30,
        format!("out(0.05,0.05)=RGB{:?}（白标记反色→应接近黑）", &o_tl[..3]),
    );
    check(
        "B2 合成左下≠暗块(标记没跑到左下)",
        !(o_bl[0] < 30 && o_bl[1] < 30 && o_bl[2] < 30),
        format!("out(0.05,0.95)=RGB{:?}", &o_bl[..3]),
    );
    // B3: 反色后原绿条左半应变品红(R高B高G低)、原蓝条右半变黄 → 验证左右未翻转
    let o_ml = px(&img, 0.25, 0.50);
    let o_mr = px(&img, 0.75, 0.50);
    check(
        "B3 反色条左右未翻转",
        o_ml[0] > 200 && o_ml[2] > 200 && o_mr[1] > 180,
        format!(
            "左=RGB{:?}(原绿→品红) 右=RGB{:?}(原蓝→黄)",
            &o_ml[..3],
            &o_mr[..3]
        ),
    );

    // C: 探针方块（右下，半透明灰）回读应 ≈(128,128,128) → blend 关闭
    let o_probe = px(&img, 0.90, 0.90);
    check(
        "C  探针=纯灰(blend-off 证明)",
        approx(o_probe[0], 128, 10) && approx(o_probe[1], 128, 10) && approx(o_probe[2], 128, 10),
        format!(
            "out(0.90,0.90)=RGB{:?}（若 blend 误开会被 magenta 混色偏红蓝）",
            &o_probe[..3]
        ),
    );

    // D: 背景点无 magenta 残留 → 全屏被合成覆盖
    let o_bg = px(&img, 0.50, 0.10);
    check(
        "D  无 magenta 残留(全屏覆盖)",
        !(o_bg[0] > 240 && o_bg[1] < 20 && o_bg[2] > 240),
        format!("out(0.50,0.10)=RGB{:?}", &o_bg[..3]),
    );

    // E: 导出真正的黑洞 PNG（warp=1 透镜开启, probe=0）
    let pretty = run(&blackhole_pipeline, 1.0, 0.0);
    match write_png("blackhole.png", &pretty) {
        Ok(()) => check("E  黑洞 PNG 导出", true, "blackhole.png 已写出".to_string()),
        Err(e) => check("E  黑洞 PNG 导出", false, format!("写 PNG 失败: {e}")),
    }

    println!(
        "\n总结: {}",
        if pass {
            "全部 PASS ✅"
        } else {
            "存在 FAIL ❌"
        }
    );
    std::process::exit(if pass { 0 } else { 1 });
}
