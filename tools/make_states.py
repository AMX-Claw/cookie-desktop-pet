#!/usr/bin/env python3
"""cookie-live 状态图流水线（2026-08-20）

输入 Cookie photo/{idle,stand,down,sleep}.png（1254x1254 近白底）
输出 states/{idle,stand,down,sleep}.png（950x1070 透明底，与 parts/ rig 同画布同地面线）

1. 蝴蝶结统一：stand/sleep 的美队徽章款整个换成 idle 的素款（藏青结+红缘+金铃铛）。
   做法：以「蝴蝶结主体质心 A → 铃铛质心 B」为轴，两点对齐解出旋转+缩放，
   仿射搬运 idle 的蝴蝶结 sprite 盖上去；盖不满旧结的残留区用周围毛色
   （遮罩加权高斯 + 微噪声）填充。
2. 抠背景：与 cut_legs.py 同款 corner flood-fill + 距离场羽化。
3. 对位：铃铛直径为统一比例锚（rig 铃铛 82px），脚底对齐 y=1054，
   狗 bbox 中心对齐 x=428（rig 的狗中心），超出画布则等比缩小到装下。
   idle 本身就是 rig 原图，直接裁 (200,55)-(1150,1125)。
"""
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHOTO = os.path.join(ROOT, 'source_images')
OUT = os.path.join(ROOT, 'assets')
QA = os.path.join(ROOT, 'build', 'qa')
os.makedirs(OUT, exist_ok=True)
os.makedirs(QA, exist_ok=True)

CANW, CANH = 950, 1070
GROUND = 1054          # rig 脚底线（画布 y）
CENTER_X = 428         # rig 狗 bbox 中心（画布 x）
BELL_REF = 82.0        # rig 铃铛直径 px

rng = np.random.default_rng(7)

def load(name):
    return np.asarray(Image.open(os.path.join(PHOTO, name + '.png')).convert('RGB')).astype(np.float32)

# ---------- 颜色分类 ----------
def masks(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    v = rgb.max(axis=2)
    navy = (b > r + 12) & (b > g + 8) & (v < 190)
    red = (r > 130) & (r > g + 55) & (r > b + 55)
    gold = (r > 170) & (g > 130) & (b < 160) & (r > b + 55) & (g > b + 25)
    ink = v < 110
    white_cool = (rgb.min(axis=2) > 195) & ((r - b) < 22)   # 星星白布（毛色 r-b≈40 排除）
    return navy, red, gold, ink, white_cool

def bbox_mask(shape, x0, y0, x1, y1):
    m = np.zeros(shape[:2], bool)
    m[y0:y1, x0:x1] = True
    return m

def largest(m):
    lab, n = ndi.label(m)
    if n == 0:
        return m
    sizes = ndi.sum(m, lab, range(1, n + 1))
    return lab == (np.argmax(sizes) + 1)

def bow_mask(rgb, box, include_white=False):
    """蝴蝶结+铃铛整体 mask（含勾线），返回 (mask, bow质心A(y,x), 铃铛质心B(y,x), 铃铛直径)"""
    navy, red, gold, ink, white = masks(rgb)
    inb = bbox_mask(rgb.shape, *box)
    core = (navy | red | gold) & inb
    if include_white:
        core = core | (white & inb)
    # 先闭合出蝴蝶结实体，再只收实体贴边 3px 内的勾线——防止把旁边下巴/毛发墨线连进来
    body_f = ndi.binary_fill_holes(ndi.binary_closing(core, structure=np.ones((7, 7))))
    body_f = largest(body_f)
    outline = ink & ndi.binary_dilation(body_f, iterations=3) & inb
    m = largest(ndi.binary_fill_holes(body_f | outline))
    gm = largest(gold & m)
    ys, xs = np.where(gm)
    bell_d = xs.max() - xs.min()
    B = np.array([ys.mean(), xs.mean()])
    body = m & ~ndi.binary_dilation(gm, iterations=3)
    ys, xs = np.where(body)
    A = np.array([ys.mean(), xs.mean()])
    return m, A, B, bell_d

# ---------- 仿射搬运 ----------
def warp(idle_rgb, sprite_soft, P1, P2, s, th):
    """把 idle 蝴蝶结按锚点 P1->P2 对齐：缩放 s、旋转 th 搬到目标坐标系"""
    c, si = np.cos(-th), np.sin(-th)
    M = np.array([[c, -si], [si, c]]) / s          # 逆变换 (y,x)
    off = P1 - M @ P2
    w_rgb = np.dstack([ndi.affine_transform(idle_rgb[..., k], M, offset=off, order=1, cval=255)
                       for k in range(3)])
    w_m = ndi.affine_transform(sprite_soft, M, offset=off, order=1, cval=0)
    return w_rgb, np.clip(w_m, 0, 1)

def fur_fill(rgb, hole):
    """旧结区域用周围毛色填充：遮罩加权高斯（剔除勾线深色）+ 微噪声保留纸感"""
    v = rgb.max(axis=2)
    keep = ~ndi.binary_dilation(hole, iterations=8) & (v > 130)   # 不采勾线墨色
    w = ndi.gaussian_filter(keep.astype(np.float32), 2)
    bA = ndi.gaussian_filter(w, 12)
    bRGB = np.dstack([ndi.gaussian_filter(rgb[..., k] * w, 12) for k in range(3)])
    fill = bRGB / np.clip(bA, 1e-4, None)[..., None]
    fill = fill + rng.normal(0, 2.5, rgb.shape).astype(np.float32)
    soft = ndi.gaussian_filter(hole.astype(np.float32), 1.5)[..., None]
    return rgb * (1 - soft) + np.clip(fill, 0, 255) * soft

def transplant(target_rgb, tgt_box, idle_rgb, idle_m, A1, B1, bell_idle):
    """比例 = 新旧铃铛直径比；定位 = 铃铛对铃铛；旋转 = 结心→铃铛轴线夹角。
    先把旧结整体抹成毛色再贴新结，不留残影。"""
    old_m, A2, B2, bell_old = bow_mask(target_rgb, tgt_box, include_white=True)
    base_s = bell_old / bell_idle
    v1, v2 = B1 - A1, B2 - A2
    th = np.arctan2(v2[0], v2[1]) - np.arctan2(v1[0], v1[1])
    # 锚点用整体质心（含铃铛）对齐——居中盖住旧结的上缘和翼尖
    C1 = np.array(np.where(idle_m)).mean(axis=1)
    ys, xs = np.where(old_m)
    C2 = np.array([ys.mean(), xs.mean()])
    out = fur_fill(target_rgb, ndi.binary_dilation(old_m, iterations=2))
    sprite_soft = ndi.gaussian_filter(idle_m.astype(np.float32), 1.2)
    extra = 1.0
    for _ in range(5):
        w_rgb, w_m = warp(idle_rgb, sprite_soft, C1, C2, base_s * extra, th)
        residual = old_m & (w_m < 0.75)
        if residual.sum() < 300 or extra >= 1.15:
            break
        extra *= 1.04
    print('  s=%.3f(extra %.2f) rot=%.1fdeg old_px=%d bell_old=%d residual=%d'
          % (base_s * extra, extra, np.degrees(th), old_m.sum(), bell_old, int(residual.sum())))
    mm = w_m[..., None]
    return out * (1 - mm) + w_rgb * mm

# ---------- 抠背景 ----------
def cutout(rgb):
    arr = rgb.astype(np.int16)
    corner = np.array([arr[0, 0], arr[0, -1], arr[-1, 0], arr[-1, -1]]).mean(axis=0)
    dist = np.sqrt(((arr - corner) ** 2).sum(axis=2))
    near_bg = dist < 22
    lab, n = ndi.label(near_bg)
    H, W = rgb.shape[:2]
    bg = np.zeros((H, W), bool)
    for y, x in [(0, 0), (0, W - 1), (H - 1, 0), (H - 1, W - 1)]:
        if lab[y, x]:
            bg |= (lab == lab[y, x])
    bg = ndi.binary_dilation(bg, iterations=1)
    d_in = ndi.distance_transform_edt(~bg)
    return np.clip(d_in / 2.0, 0, 1)

# ---------- 对位到 950x1070 ----------
def place(rgb, alpha, bell_d):
    a5 = alpha > 0.5
    ys, xs = np.where(a5)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    s = BELL_REF / bell_d
    # 画布约束：高 ≤ GROUND-6，宽 ≤ 装得下（中心 428，两侧留 2px）
    dog_w, dog_h = x1 - x0 + 1, y1 - y0 + 1
    s = min(s, (GROUND - 6) / dog_h)
    max_w = 2 * min(CENTER_X - 2, CANW - 2 - CENTER_X)
    s = min(s, max_w / dog_w)
    rgba = np.dstack([rgb, alpha[..., None] * 255]).astype(np.uint8)
    im = Image.fromarray(rgba)
    nw, nh = round(im.width * s), round(im.height * s)
    im = im.resize((nw, nh), Image.LANCZOS)
    arr = np.asarray(im).astype(np.float32)
    a5 = arr[..., 3] > 128
    ys, xs = np.where(a5)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    canvas = np.zeros((CANH, CANW, 4), np.float32)
    ox = CENTER_X - (x0 + x1) // 2
    oy = GROUND - y1
    # 源区域 → 画布区域（裁剪越界）
    sy0, sy1 = max(0, -oy), min(arr.shape[0], CANH - oy)
    sx0, sx1 = max(0, -ox), min(arr.shape[1], CANW - ox)
    canvas[sy0 + oy:sy1 + oy, sx0 + ox:sx1 + ox] = arr[sy0:sy1, sx0:sx1]
    return Image.fromarray(canvas.astype(np.uint8)), s

# ================= 主流程 =================
idle = load('idle'); stand = load('stand'); down = load('down'); sleep = load('sleep')

print('== 提取 idle 素款蝴蝶结 sprite ==')
IDLE_BOX = (440, 645, 790, 920)
idle_m, A1, B1, bell_idle = bow_mask(idle, IDLE_BOX)
print('  idle bow A=%s B=%s bell_d=%d px=%d' % (A1.round(1), B1.round(1), bell_idle, idle_m.sum()))

print('== stand 移植 ==')
stand_fix = transplant(stand, (575, 465, 835, 700), idle, idle_m, A1, B1, bell_idle)
print('== sleep 移植 ==')
sleep_fix = transplant(sleep, (560, 530, 800, 860), idle, idle_m, A1, B1, bell_idle)

# QA 局部放大
for name, img, box in [('qa_stand_fix', stand_fix, (560, 440, 880, 760)),
                       ('qa_sleep_fix', sleep_fix, (520, 500, 840, 900))]:
    c = Image.fromarray(img.astype(np.uint8)).crop(box)
    c = c.resize((c.width * 3, c.height * 3), Image.LANCZOS)
    c.save(os.path.join(QA, name + '.png'))

print('== 抠背景 + 对位 ==')
# idle：就是 rig 原图，直接裁窗（保证与 rig 完全对齐）
a = cutout(idle)
rgba = np.dstack([idle, a[..., None] * 255]).astype(np.uint8)
Image.fromarray(rgba).crop((200, 55, 1150, 1125)).save(os.path.join(OUT, 'idle.png'))
print('  idle: direct crop')

for name, img in [('stand', stand_fix), ('down', down), ('sleep', sleep_fix)]:
    a = cutout(img)
    # 各自铃铛直径（stand/sleep 已是移植后的 idle 铃铛）
    _, _, _, bd = bow_mask(img, {'stand': (500, 400, 900, 800),
                                 'down': (420, 700, 790, 990),
                                 'sleep': (500, 450, 900, 950)}[name])
    im, s = place(img, a, bd)
    im.save(os.path.join(OUT, name + '.png'))
    print('  %s: bell_d=%d scale=%.3f' % (name, bd, s))

print('done ->', OUT)
