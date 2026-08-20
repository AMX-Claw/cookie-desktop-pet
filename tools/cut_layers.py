#!/usr/bin/env python3
"""cookie-live 全套切件（返工版 2026-08-20）
产出 parts/: tail/head/body/leg_FL/leg_FR/leg_BL/leg_BR
          + patch_neck/patch_tail/patch_legs + lid_L/lid_R，公共画布 950x1070（原图 -200,-55）。

返工要点（甲方差评：腿根硬接缝、摇头脸颊裂缝）：
1. 所有切口 mask 高斯羽化 sigma=6（≈15px 过渡带），不再用 1.2~1.5 的硬边
2. head 层在领口切线以下多保留 45px（带着一点脖子毛转），缝藏进毛里
3. patch_neck 加大：沿 head 边界外扩 14px + 向下 22px，覆盖 ±3° 摆头扫过的扇区
4. 腿件只在转轴上方保留 38px 隐藏搭接，并全程锁在各自脚掌边界内；
   旧版向上抓 110px/左右外扩会带走胸毛和邻脚，旋转后露成“分脚趾”
5. body 挖洞洞边同样 sigma=6 羽化
6. 所有补丁颜色改用「遮罩加权高斯模糊原图」（sigma=10 的局部渐变色），不再是单一中位色
"""
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'source_images', 'idle.jpg')
OUT = os.path.join(ROOT, 'assets')
os.makedirs(OUT, exist_ok=True)

im = Image.open(SRC).convert('RGB')
W, H = im.size
arr = np.asarray(im).astype(np.int16)
RGB = np.asarray(im)

# ---- 背景抠除（flood fill from corners）----
corner = np.array([arr[0, 0], arr[0, -1], arr[-1, 0], arr[-1, -1]]).mean(axis=0)
dist = np.sqrt(((arr - corner) ** 2).sum(axis=2))
near_bg = dist < 22
lab, n = ndi.label(near_bg)
bg = np.zeros((H, W), dtype=bool)
for y, x in [(0, 0), (0, W - 1), (H - 1, 0), (H - 1, W - 1)]:
    if lab[y, x]:
        bg |= (lab == lab[y, x])
bg = ndi.binary_dilation(bg, iterations=1)
d_in = ndi.distance_transform_edt(~bg)
ALPHA = np.clip(d_in / 2.0, 0, 1)

SIG = 6.0            # 切口羽化 sigma（过渡带 ≈15px）
GROW = 25            # 藏在上层底下的延伸量
HEAD_KEEP = 45       # head 在切线以下多保留的脖子毛
solid_bin = ndi.binary_erosion(ALPHA > 0.6, iterations=6)
solid = ndi.gaussian_filter(solid_bin.astype(np.float32), 2)

# 补丁用的局部渐变色：遮罩加权模糊（背景色不渗入；深色勾线也剔除权重，
# 否则补丁上会带出灰色墨迹晕影，腿摆开时像一块脏影子）
lum = RGB @ np.array([0.3, 0.59, 0.11])
ink = ndi.gaussian_filter(((lum < 140) & (ALPHA > 0.3)).astype(np.float32), 2)
wgt = ALPHA * np.clip(1 - ink * 1.5, 0, 1)
bA = ndi.gaussian_filter(wgt, 10)
bRGB = np.dstack([ndi.gaussian_filter(RGB[:, :, c] * wgt, 10) for c in range(3)])
BLUR = (bRGB / np.clip(bA, 1e-3, None)[..., None]).clip(0, 255)

# ---- 头/尾多边形 ----
NECK = [(360, 600), (420, 655), (470, 682), (520, 692), (575, 695), (625, 686), (658, 668),
        (688, 646), (720, 630), (770, 612), (810, 585), (840, 545)]
HEAD_POLY = [(160, 60), (870, 60), (890, 420)] + [(840, 545), (810, 585), (770, 612), (720, 630),
        (688, 646), (658, 668), (625, 686), (575, 695), (520, 692), (470, 682), (420, 655), (360, 600)] + \
        [(290, 540), (230, 460), (155, 290)]
TAIL_POLY = [(925, 688), (900, 640), (900, 500), (940, 430), (1030, 420), (1110, 490),
             (1130, 600), (1110, 700), (1050, 745), (1000, 742)]

def poly_mask(pts):
    m = Image.new('L', (W, H), 0)
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return np.asarray(m) > 0

def grow(mask_bin, px):
    return ndi.distance_transform_edt(~mask_bin) <= px

def shift_down_union(mask_bin, px, step=3):
    out = mask_bin.copy()
    for s in range(step, px + 1, step):
        r = np.zeros_like(mask_bin)
        r[s:, :] = mask_bin[:-s, :]
        out |= r
    return out

head_bin = poly_mask(HEAD_POLY)
tail_bin = poly_mask(TAIL_POLY)

# ---- head：切线以下多留 HEAD_KEEP px 脖子毛，羽化 ----
head_ext = shift_down_union(head_bin, HEAD_KEEP)
head_piece = ndi.gaussian_filter(head_ext.astype(np.float32), SIG) * ALPHA
hole_head = ndi.gaussian_filter(head_bin.astype(np.float32), SIG)

# ---- tail：向 body 里长 GROW px（藏在 body 后面），羽化 ----
tail_ext = grow(tail_bin, GROW)
tail_piece = ndi.gaussian_filter(tail_ext.astype(np.float32), SIG) * ALPHA
hole_tail = ndi.gaussian_filter(tail_bin.astype(np.float32), SIG)

# ---- 四条腿 ----
LEGS = {
  # x 边界按源图四只脚掌之间的空隙划分；每个脚掌只属于一条腿。
  'leg_FL': dict(x0=380, x1=575, cut=992, pivot=(490, 988)),   # 前近（画面左）
  'leg_FR': dict(x0=575, x1=740, cut=985, pivot=(650, 982)),   # 前远
  'leg_BR': dict(x0=750, x1=895, cut=958, pivot=(840, 955)),   # 后远（内侧小脚）
  'leg_BL': dict(x0=895, x1=1045, cut=945, pivot=(965, 942)),  # 后近（画面右大毛腿）
}
CX0, CY0, CX1, CY1 = 200, 55, 1150, 1125   # 950 x 1070

def rect_mask(x0, y0, x1, y1, sig):
    m = np.zeros((H, W), np.float32)
    m[max(y0, 0):min(y1, H), max(x0, 0):min(x1, W)] = 1
    return ndi.gaussian_filter(m, sig) if sig else m

def tapered_leg_mask(x0, x1, cut, sig):
    """腿根留遮缝余量，脚掌段严格独占，不能吃进相邻脚的像素。"""
    # 转轴就在 cut 附近，body 会盖住它上方；只需要很短的隐藏搭接。
    # 旧版向上抓 110px，会把胸毛/邻腿也收进活动层，摆动后露成鬼影。
    top = cut - 38
    mask = rect_mask(x0, top, x1, H, sig)
    # Gaussian feathering also grows *outward*. Below the pivot that would
    # quietly re-import a neighbour's toe by a few pixels, recreating the bug
    # this tapered mask is meant to prevent. Keep feathering inside the limb,
    # but make ownership exclusive outside x0..x1 in the visible paw section.
    mask[:top, :] = 0
    mask[:, :x0] = 0
    mask[:, x1:] = 0
    return mask

def save_rgba(name, rgb, alpha):
    img = np.dstack([rgb.astype(np.uint8), (np.clip(alpha, 0, 1) * 255).astype(np.uint8)])
    Image.fromarray(img, 'RGBA').crop((CX0, CY0, CX1, CY1)).save(f'{OUT}/{name}.png')

body_alpha = ALPHA * np.clip(1 - hole_head, 0, 1) * np.clip(1 - hole_tail, 0, 1)
patch_legs_a = np.zeros((H, W), np.float32)

for nm, L in LEGS.items():
    hole = rect_mask(L['x0'], L['cut'], L['x1'], 1260, SIG)
    piece = tapered_leg_mask(L['x0'], L['x1'], L['cut'], SIG)
    save_rgba(nm, RGB, ALPHA * piece)
    body_alpha *= np.clip(1 - hole, 0, 1)
    # 补丁只填腿根洞口。旧版一路延伸到 cut+85，等于在活动腿后面又
    # 留了一截静止脚掌；腿抬起时那截会露成分叉/鬼影。
    pm = rect_mask(L['x0'], L['cut'] - 55, L['x1'], L['cut'] + 22, SIG) * solid
    patch_legs_a = np.maximum(patch_legs_a, pm)
    print(nm, 'pivot%%=(%.2f%%, %.2f%%)' % ((L['pivot'][0] - CX0) / 9.5, (L['pivot'][1] - CY0) / 10.7))

save_rgba('tail', RGB, tail_piece)
save_rgba('head', RGB, head_piece)
save_rgba('body', RGB, body_alpha)
save_rgba('patch_legs', BLUR, patch_legs_a)

# ---- patch_neck：head 边界外扩 14 + 向下 22，y 限制 380..760，实心内 ----
pn = grow(head_bin, 14)
pn = shift_down_union(pn, 22)
band = np.zeros((H, W), bool); band[380:760, :] = True
pn_a = ndi.gaussian_filter((pn & band & solid_bin).astype(np.float32), SIG) * solid
save_rgba('patch_neck', BLUR, pn_a)

# ---- patch_tail：尾根椭圆（盖在 tail 之上、body 之下）----
def ellipse_mask(cx, cy, rx, ry, angle_deg=0, sig=5):
    m = Image.new('L', (W, H), 0)
    e = Image.new('L', (2 * rx + 8, 2 * ry + 8), 0)
    ImageDraw.Draw(e).ellipse([4, 4, 4 + 2 * rx, 4 + 2 * ry], fill=255)
    e = e.rotate(angle_deg, expand=True, resample=Image.BICUBIC)
    m.paste(e, (int(cx - e.width / 2), int(cy - e.height / 2)))
    mm = np.asarray(m).astype(np.float32) / 255
    return ndi.gaussian_filter(mm, sig)

pt_a = ellipse_mask(968, 700, 70, 38, angle_deg=-36, sig=SIG) * solid
save_rgba('patch_tail', BLUR, pt_a)

# ---- 眼皮（与上一版一致）----
def sample(cx, cy, r=12):
    reg = RGB[cy - r:cy + r, cx - r:cx + r].reshape(-1, 3)
    return tuple(int(v) for v in np.median(reg, axis=0))

fur_L, fur_R = sample(505, 575), sample(700, 520)
for name, (cx, cy), col in [('lid_L', (458, 508), fur_L), ('lid_R', (638, 458), fur_R)]:
    m = ellipse_mask(cx, cy, 58 if name == 'lid_L' else 60, 54 if name == 'lid_L' else 56, sig=4)
    img = np.zeros((H, W, 4), dtype=np.uint8)
    img[:, :, 0], img[:, :, 1], img[:, :, 2] = col
    img[:, :, 3] = (m * 255).astype(np.uint8)
    pil = Image.fromarray(img, 'RGBA')
    d = ImageDraw.Draw(pil)
    rx, ry = 34, 26
    d.arc([cx - rx, cy - ry + 14, cx + rx, cy + ry + 14], start=200, end=340, fill=(58, 48, 38, 255), width=7)
    pil.crop((CX0, CY0, CX1, CY1)).save(f'{OUT}/{name}.png')

# ---- recompose 静止验证 ----
comp = Image.new('RGBA', (CX1 - CX0, CY1 - CY0), (250, 247, 242, 255))
for nm in ['tail', 'patch_tail', 'patch_legs', 'leg_BR', 'leg_FR', 'leg_BL', 'leg_FL',
           'body', 'patch_neck', 'head']:
    comp.alpha_composite(Image.open(f'{OUT}/{nm}.png'))
orig = im.crop((CX0, CY0, CX1, CY1))
diff = np.abs(np.asarray(comp.convert('RGB')).astype(int) - np.asarray(orig).astype(int)).sum(axis=2)
print('recompose maxdiff', diff.max(), 'mean', round(diff.mean(), 2), 'px>40:', int((diff > 40).sum()))
ys, xs = np.where(diff > 40)
if len(ys):
    print('diff bbox x', xs.min(), xs.max(), 'y', ys.min(), ys.max())
