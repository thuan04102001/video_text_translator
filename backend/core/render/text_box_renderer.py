from typing import List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


DEFAULT_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
]


def clamp(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(value, max_value))


def normalize_box(
    box: List[int],
    frame_width: int,
    frame_height: int,
) -> List[int]:
    if not box or len(box) != 4:
        return [0, 0, frame_width, frame_height]

    x1, y1, x2, y2 = [int(v) for v in box]

    x1 = clamp(x1, 0, frame_width - 1)
    y1 = clamp(y1, 0, frame_height - 1)
    x2 = clamp(x2, x1 + 1, frame_width)
    y2 = clamp(y2, y1 + 1, frame_height)

    return [x1, y1, x2, y2]


def load_font(
    font_size: int,
    bold: bool = True,
) -> ImageFont.FreeTypeFont:
    candidates = DEFAULT_FONT_CANDIDATES

    if not bold:
        candidates = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/tahoma.ttf",
        ]

    for font_path in candidates:
        try:
            return ImageFont.truetype(font_path, font_size)
        except Exception:
            continue

    return ImageFont.load_default()


def measure_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
) -> Tuple[int, int]:
    if not text:
        return 0, 0

    bbox = draw.textbbox(
        (0, 0),
        text,
        font=font,
        stroke_width=0,
    )

    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def measure_multiline_text(
    draw: ImageDraw.ImageDraw,
    lines: List[str],
    font: ImageFont.FreeTypeFont,
    line_spacing: int = 4,
) -> Tuple[int, int]:
    if not lines:
        return 0, 0

    widths = []
    heights = []

    for line in lines:
        width, height = measure_text(
            draw=draw,
            text=line,
            font=font,
        )

        widths.append(width)
        heights.append(height)

    total_height = sum(heights)

    if len(lines) > 1:
        total_height += line_spacing * (len(lines) - 1)

    return max(widths), total_height


def wrap_text_to_width(
    text: str,
    draw: ImageDraw.ImageDraw,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> List[str]:
    clean_text = str(text or "").strip()

    if not clean_text:
        return []

    words = clean_text.split()

    if not words:
        return []

    lines = []
    current_line = ""

    for word in words:
        test_line = word if not current_line else f"{current_line} {word}"

        test_width, _ = measure_text(
            draw=draw,
            text=test_line,
            font=font,
        )

        if test_width <= max_width:
            current_line = test_line
            continue

        if current_line:
            lines.append(current_line)
            current_line = word
        else:
            lines.append(word)
            current_line = ""

    if current_line:
        lines.append(current_line)

    return lines


def get_text_width_at_font_size(
    text: str,
    font_size: int,
) -> int:
    dummy_image = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(dummy_image)
    font = load_font(font_size)

    width, _height = measure_text(
        draw=draw,
        text=text,
        font=font,
    )

    return width


def get_box_area(box: List[int]) -> int:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def get_intersection_area(box_a: List[int], box_b: List[int]) -> int:
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])

    return max(0, x2 - x1) * max(0, y2 - y1)


def expand_box(
    box: List[int],
    frame_width: int,
    frame_height: int,
    pad_x: int,
    pad_y: int,
) -> List[int]:
    return normalize_box(
        [
            box[0] - pad_x,
            box[1] - pad_y,
            box[2] + pad_x,
            box[3] + pad_y,
        ],
        frame_width,
        frame_height,
    )


def union_boxes(boxes: List[List[int]]) -> List[int]:
    valid_boxes = [
        box
        for box in boxes
        if box and len(box) == 4 and box[2] > box[0] and box[3] > box[1]
    ]

    if not valid_boxes:
        return []

    return [
        min(box[0] for box in valid_boxes),
        min(box[1] for box in valid_boxes),
        max(box[2] for box in valid_boxes),
        max(box[3] for box in valid_boxes),
    ]


def detect_caption_background_mask(
    frame: np.ndarray,
    ocr_box: List[int],
) -> Tuple[List[int], np.ndarray]:
    frame_height, frame_width = frame.shape[:2]
    x1, y1, x2, y2 = ocr_box

    box_width = max(1, x2 - x1)
    box_height = max(1, y2 - y1)

    search_box = expand_box(
        box=ocr_box,
        frame_width=frame_width,
        frame_height=frame_height,
        pad_x=max(28, int(box_width * 0.55), int(frame_width * 0.045)),
        pad_y=max(24, int(box_height * 1.35), int(frame_height * 0.035)),
    )
    sx1, sy1, sx2, sy2 = search_box

    crop = frame[sy1:sy2, sx1:sx2]

    if crop.size == 0:
        return [], np.zeros((frame_height, frame_width), dtype=np.uint8)

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    min_channel = np.min(crop, axis=2)

    mask = np.where(
        ((value >= 205) & (saturation <= 58)) | (min_channel >= 212),
        255,
        0,
    ).astype(np.uint8)

    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 5))
    dilate_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel, iterations=2)
    mask = cv2.dilate(mask, dilate_kernel, iterations=1)

    component_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        mask,
        connectivity=8,
    )

    anchor_box = expand_box(
        box=ocr_box,
        frame_width=frame_width,
        frame_height=frame_height,
        pad_x=max(8, int(box_width * 0.16)),
        pad_y=max(8, int(box_height * 0.35)),
    )
    ocr_center_x = (x1 + x2) / 2
    ocr_center_y = (y1 + y2) / 2

    selected_indexes = []
    candidate_boxes = []
    min_component_area = max(120, int(box_width * box_height * 0.18))

    for index in range(1, component_count):
        local_x = int(stats[index, cv2.CC_STAT_LEFT])
        local_y = int(stats[index, cv2.CC_STAT_TOP])
        local_w = int(stats[index, cv2.CC_STAT_WIDTH])
        local_h = int(stats[index, cv2.CC_STAT_HEIGHT])
        area = int(stats[index, cv2.CC_STAT_AREA])

        if area < min_component_area:
            continue

        component_box = [
            sx1 + local_x,
            sy1 + local_y,
            sx1 + local_x + local_w,
            sy1 + local_y + local_h,
        ]

        component_width = component_box[2] - component_box[0]
        component_height = component_box[3] - component_box[1]
        component_center_x = (component_box[0] + component_box[2]) / 2
        component_center_y = (component_box[1] + component_box[3]) / 2

        if component_width < box_width * 0.55:
            continue

        if component_height < box_height * 0.35:
            continue

        if component_width > frame_width * 0.95:
            continue

        if component_height > frame_height * 0.36:
            continue

        if component_height > box_height * 2.05:
            continue

        if abs(component_center_x - ocr_center_x) > max(box_width * 0.9, frame_width * 0.18):
            continue

        if abs(component_center_y - ocr_center_y) > max(box_height * 1.15, frame_height * 0.08):
            continue

        if get_intersection_area(component_box, anchor_box) <= 0:
            continue

        intersection_with_ocr = get_intersection_area(component_box, ocr_box)
        contains_ocr_center = (
            component_box[0] <= ocr_center_x <= component_box[2]
            and component_box[1] <= ocr_center_y <= component_box[3]
        )

        if (
            not contains_ocr_center
            and intersection_with_ocr < get_box_area(ocr_box) * 0.28
        ):
            continue

        selected_indexes.append(index)
        candidate_boxes.append(component_box)

    background_box = union_boxes(candidate_boxes)

    if not background_box:
        return [], np.zeros((frame_height, frame_width), dtype=np.uint8)

    if get_box_area(background_box) < get_box_area(ocr_box) * 0.7:
        return [], np.zeros((frame_height, frame_width), dtype=np.uint8)

    selected_local_mask = np.zeros(mask.shape, dtype=np.uint8)

    for index in selected_indexes:
        selected_local_mask[labels == index] = 255

    smooth_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    selected_local_mask = cv2.dilate(selected_local_mask, smooth_kernel, iterations=1)

    margin_x = max(2, int(box_width * 0.012))
    margin_y = max(2, int(box_height * 0.018))

    background_box = expand_box(
        box=background_box,
        frame_width=frame_width,
        frame_height=frame_height,
        pad_x=margin_x,
        pad_y=margin_y,
    )

    full_mask = np.zeros((frame_height, frame_width), dtype=np.uint8)
    full_mask[sy1:sy2, sx1:sx2] = selected_local_mask

    bx1, by1, bx2, by2 = background_box
    mask_area = int(np.count_nonzero(full_mask[by1:by2, bx1:bx2]))
    box_area = max(1, get_box_area(background_box))

    if mask_area / box_area < 0.55:
        return [], np.zeros((frame_height, frame_width), dtype=np.uint8)

    return background_box, full_mask


def expand_box_for_translated_text(
    box: List[int],
    text: str,
    frame_width: int,
    frame_height: int,
    target_font_size: int = 31,
    padding_x: int = 10,
    padding_y: int = 6,
    min_side_extra_ratio: float = 0.02,
    max_width_ratio: float = 0.78,
) -> List[int]:
    """
    Mở rộng box theo độ dài text dịch.

    Lý do:
    - box OCR gốc có thể đủ cho text tiếng Anh ngắn.
    - text tiếng Việt có thể dài hơn.
    - nếu chỉ fit trong box gốc thì bị xuống dòng xấu.
    - hàm này mở rộng ngang cân đối để ưu tiên 1 dòng đẹp hơn.

    Không làm:
    - không sửa text
    - không dịch
    - không chọn caption
    """

    x1, y1, x2, y2 = box

    box_width = max(1, x2 - x1)
    box_height = max(1, y2 - y1)

    clean_text = str(text or "").strip()

    if not clean_text:
        return box

    target_text_width = get_text_width_at_font_size(
        text=clean_text,
        font_size=target_font_size,
    )

    desired_width = target_text_width + padding_x * 2

    min_extra = int(box_width * min_side_extra_ratio)

    desired_width = max(
        box_width + min_extra * 2,
        desired_width,
    )

    max_width = int(frame_width * max_width_ratio)
    desired_width = min(desired_width, max_width)

    center_x = (x1 + x2) / 2

    new_x1 = int(center_x - desired_width / 2)
    new_x2 = int(center_x + desired_width / 2)

    # OCR boxes often describe the text area, while the meme caption
    # background has extra rounded white padding/tabs around it. Add a
    # bounded coverage margin so the old white box and old glyph edges
    # do not peek out after redraw.
    coverage_extra_x = max(
        5,
        int(box_width * 0.045),
        int(frame_width * 0.007),
    )
    coverage_extra_y = max(
        3,
        int(box_height * 0.035),
        int(frame_height * 0.002),
    )

    new_x1 -= coverage_extra_x
    new_x2 += coverage_extra_x

    vertical_extra = max(2, int(box_height * 0.06)) + coverage_extra_y

    return normalize_box(
        [
            new_x1,
            y1 - vertical_extra,
            new_x2,
            y2 + vertical_extra,
        ],
        frame_width,
        frame_height,
    )


def build_centered_cover_box(
    base_box: List[int],
    expanded_box: List[int],
    text_width: int,
    text_height: int,
    padding_x: int,
    padding_y: int,
    frame_width: int,
    frame_height: int,
    detected_background: bool = False,
) -> List[int]:
    base_x1, base_y1, base_x2, base_y2 = base_box
    expanded_x1, _expanded_y1, expanded_x2, _expanded_y2 = expanded_box

    base_width = max(1, base_x2 - base_x1)
    base_height = max(1, base_y2 - base_y1)
    expanded_width = max(1, expanded_x2 - expanded_x1)

    center_x = (base_x1 + base_x2) / 2
    center_y = (base_y1 + base_y2) / 2

    cover_extra_x = max(
        padding_x,
        int(base_width * 0.045),
        int(frame_width * 0.006),
    )
    cover_extra_y = max(
        padding_y,
        int(base_height * 0.08),
        int(frame_height * 0.003),
    )

    desired_width = max(
        base_width + cover_extra_x * 2,
        expanded_width,
        text_width + padding_x * 2,
    )
    desired_width = min(desired_width, int(frame_width * 0.9))

    vertical_padding = max(
        padding_y * 2,
        int(text_height * 0.16),
        8,
    )
    desired_height = max(
        base_height + cover_extra_y * 2,
        text_height + vertical_padding * 2,
    )

    desired_height = min(desired_height, int(frame_height * 0.24))

    new_x1 = int(center_x - desired_width / 2)
    new_x2 = int(center_x + desired_width / 2)
    new_y1 = int(center_y - desired_height / 2)
    new_y2 = int(center_y + desired_height / 2)

    return normalize_box(
        [new_x1, new_y1, new_x2, new_y2],
        frame_width,
        frame_height,
    )


def build_strict_geometry_box(
    box: List[int],
    frame_width: int,
    frame_height: int,
    pad_x: int,
    pad_y: int,
) -> List[int]:
    x1, y1, x2, y2 = normalize_box(
        box=box,
        frame_width=frame_width,
        frame_height=frame_height,
    )

    box_width = max(1, x2 - x1)
    box_height = max(1, y2 - y1)

    # Follow the OCR rectangle instead of detecting a mask from pixels. Mask
    # detection can spill into bright background regions and smear the video.
    edge_pad_x = max(2, min(10, int(box_width * 0.018), pad_x))
    edge_pad_y = max(2, min(8, int(box_height * 0.035), pad_y))

    return normalize_box(
        [
            x1 - edge_pad_x,
            y1 - edge_pad_y,
            x2 + edge_pad_x,
            y2 + edge_pad_y,
        ],
        frame_width,
        frame_height,
    )


def caption_has_white_background(
    frame: np.ndarray,
    box: List[int],
) -> bool:
    frame_height, frame_width = frame.shape[:2]
    x1, y1, x2, y2 = normalize_box(
        box=box,
        frame_width=frame_width,
        frame_height=frame_height,
    )

    box_width = max(1, x2 - x1)
    box_height = max(1, y2 - y1)
    sample_box = expand_box(
        box=[x1, y1, x2, y2],
        frame_width=frame_width,
        frame_height=frame_height,
        pad_x=max(4, int(box_width * 0.04)),
        pad_y=max(4, int(box_height * 0.08)),
    )
    sx1, sy1, sx2, sy2 = sample_box
    crop = frame[sy1:sy2, sx1:sx2]

    if crop.size == 0:
        return True

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    min_channel = np.min(crop, axis=2)
    white_mask = ((value >= 210) & (saturation <= 60)) | (min_channel >= 220)
    white_ratio = float(np.count_nonzero(white_mask)) / float(white_mask.size)

    return white_ratio >= 0.42


def remove_stroked_text_from_frame(
    frame: np.ndarray,
    box: List[int],
) -> np.ndarray:
    frame_height, frame_width = frame.shape[:2]
    x1, y1, x2, y2 = normalize_box(
        box=box,
        frame_width=frame_width,
        frame_height=frame_height,
    )

    box_width = max(1, x2 - x1)
    box_height = max(1, y2 - y1)
    erase_box = expand_box(
        box=[x1, y1, x2, y2],
        frame_width=frame_width,
        frame_height=frame_height,
        pad_x=max(3, int(box_width * 0.025)),
        pad_y=max(3, int(box_height * 0.04)),
    )
    ex1, ey1, ex2, ey2 = erase_box
    crop = frame[ey1:ey2, ex1:ex2]

    if crop.size == 0:
        return frame

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    white_glyph = ((value >= 185) & (saturation <= 95)).astype(np.uint8)

    if np.count_nonzero(white_glyph) < 20:
        return frame

    component_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        white_glyph,
        connectivity=8,
    )
    outline_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = np.zeros_like(white_glyph, dtype=np.uint8)

    for component_index in range(1, component_count):
        x, y, width, height, area = stats[component_index]

        if area < 12:
            continue

        if width > crop.shape[1] * 0.85 or height > crop.shape[0] * 0.75:
            continue

        component = (labels == component_index).astype(np.uint8)
        dilated = cv2.dilate(component, outline_kernel, iterations=1)
        ring = (dilated > 0) & (component == 0)

        if np.count_nonzero(ring) == 0:
            continue

        dark_outline_ratio = float(np.count_nonzero(value[ring] <= 95)) / float(
            np.count_nonzero(ring)
        )

        if dark_outline_ratio < 0.08:
            continue

        mask[dilated > 0] = 255

    if np.count_nonzero(mask) < 20:
        return frame

    inpainted_crop = cv2.inpaint(crop, mask, 2, cv2.INPAINT_TELEA)
    output = frame.copy()
    output[ey1:ey2, ex1:ex2] = inpainted_crop

    return output


def fit_text_to_box(
    text: str,
    box_width: int,
    box_height: int,
    min_font_size: int = 13,
    max_font_size: int = 44,
    padding_x: int = 10,
    padding_y: int = 7,
) -> Tuple[ImageFont.FreeTypeFont, List[str], int]:
    """
    Fit text vào box.

    Logic mới:
    - ưu tiên ít dòng hơn
    - thử 1 dòng trước nếu có thể
    - sau đó mới wrap nhiều dòng
    """

    dummy_image = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(dummy_image)

    usable_width = max(1, box_width - padding_x * 2)
    usable_height = max(1, box_height - padding_y * 2)

    for font_size in range(max_font_size, min_font_size - 1, -1):
        font = load_font(font_size)
        line_spacing = max(2, int(font_size * 0.08))

        lines = wrap_text_to_width(
            text=text,
            draw=draw,
            font=font,
            max_width=usable_width,
        )

        if not lines:
            continue

        if len(lines) > 3 and font_size > 24:
            continue

        if len(lines) > 4:
            continue

        text_width, text_height = measure_multiline_text(
            draw=draw,
            lines=lines,
            font=font,
            line_spacing=line_spacing,
        )

        if text_width <= usable_width and text_height <= usable_height:
            return font, lines, line_spacing

    best_font = load_font(min_font_size)
    best_line_spacing = max(2, int(min_font_size * 0.08))
    best_lines = wrap_text_to_width(
        text=text,
        draw=draw,
        font=best_font,
        max_width=usable_width,
    ) or [text]

    return best_font, best_lines, best_line_spacing


def draw_rounded_rectangle(
    draw: ImageDraw.ImageDraw,
    box: List[int],
    radius: int = 8,
    fill=(255, 255, 255),
    outline=None,
    width: int = 1,
) -> None:
    x1, y1, x2, y2 = box

    try:
        draw.rounded_rectangle(
            [x1, y1, x2, y2],
            radius=radius,
            fill=fill,
            outline=outline,
            width=width,
        )
    except Exception:
        draw.rectangle(
            [x1, y1, x2, y2],
            fill=fill,
            outline=outline,
            width=width,
        )


def render_text_box_on_frame(
    frame: np.ndarray,
    text: str,
    box: List[int],
    background_color=(255, 255, 255),
    text_color=(0, 0, 0),
    padding_x: int = 10,
    padding_y: int = 7,
    radius: int = 8,
    use_background_mask: bool = True,
    fallback_background: bool = True,
    render_style: str = "auto",
) -> np.ndarray:
    """
    Render translated text vào box caption.

    Nguyên tắc:
    - renderer chỉ vẽ text đã được truyền vào
    - không sửa chính tả
    - không dịch
    - không quyết định caption nào hợp lệ
    - nếu text dịch dài hơn box gốc, mở rộng box ngang vừa đủ
    """

    if frame is None:
        raise ValueError("frame is None")

    clean_text = str(text or "").strip()

    if not clean_text:
        return frame

    frame_height, frame_width = frame.shape[:2]

    safe_box = normalize_box(
        box=box,
        frame_width=frame_width,
        frame_height=frame_height,
    )

    base_box = safe_box
    render_box = build_strict_geometry_box(
        box=base_box,
        frame_width=frame_width,
        frame_height=frame_height,
        pad_x=padding_x,
        pad_y=padding_y,
    )

    x1, y1, x2, y2 = render_box
    box_width = x2 - x1
    box_height = y2 - y1
    has_white_background = (
        caption_has_white_background(
            frame=frame,
            box=base_box,
        )
        if render_style == "auto"
        else render_style == "box"
    )
    draw_frame = frame

    rgb_frame = cv2.cvtColor(draw_frame, cv2.COLOR_BGR2RGB)
    image = Image.fromarray(rgb_frame)
    draw = ImageDraw.Draw(image)

    font, lines, line_spacing = fit_text_to_box(
        text=clean_text,
        box_width=box_width,
        box_height=box_height,
        padding_x=padding_x,
        padding_y=padding_y,
    )

    _text_width, text_height = measure_multiline_text(
        draw=draw,
        lines=lines,
        font=font,
        line_spacing=line_spacing,
    )

    draw_text_kwargs = {}

    if has_white_background:
        draw_rounded_rectangle(
            draw=draw,
            box=render_box,
            radius=radius,
            fill=background_color,
        )
        draw_fill = text_color
        draw_text_kwargs = {}
    else:
        overlay = image.convert("RGBA")
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle(
            [x1, y1, x2, y2],
            radius=radius,
            fill=(0, 0, 0, 255),
        )
        image = Image.alpha_composite(
            image.convert("RGBA"),
            overlay,
        ).convert("RGB")
        draw = ImageDraw.Draw(image)
        draw_fill = (255, 255, 255)
        draw_text_kwargs = {
            "stroke_width": max(3, int(getattr(font, "size", 24) * 0.18)),
            "stroke_fill": (0, 0, 0),
        }

    current_y = y1 + max(0, (box_height - text_height) // 2)

    for line in lines:
        line_width, line_height = measure_text(
            draw=draw,
            text=line,
            font=font,
        )

        line_x = x1 + max(0, (box_width - line_width) // 2)

        draw.text(
            (line_x, current_y),
            line,
            font=font,
            fill=draw_fill,
            **draw_text_kwargs,
        )

        current_y += line_height + line_spacing

    output_rgb = np.array(image)
    output_bgr = cv2.cvtColor(output_rgb, cv2.COLOR_RGB2BGR)

    return output_bgr


def render_translated_timelines_on_frame(
    frame: np.ndarray,
    timelines: List[dict],
    current_time: float,
) -> np.ndarray:
    output = frame

    for timeline in timelines:
        start = float(timeline.get("start", 0.0) or 0.0)
        end = float(timeline.get("end", 0.0) or 0.0)

        if current_time < start or current_time > end:
            continue

        translated_text = (
            timeline.get("translated_text")
            or timeline.get("text")
            or ""
        )

        best_sample = timeline.get("best_sample") or {}
        box = (
            timeline.get("render_box")
            or timeline.get("box")
            or best_sample.get("box")
            or timeline.get("average_box")
        )

        if not box:
            continue

        role = timeline.get("caption_role")

        output = render_text_box_on_frame(
            frame=output,
            text=translated_text,
            box=box,
            use_background_mask=False,
            fallback_background=True,
        )

    return output
