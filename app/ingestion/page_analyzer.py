from dataclasses import dataclass

import pymupdf


@dataclass
class PageAnalysis:
    page_number: int
    text_chars: int
    native_table_count: int

    # Image statistics
    image_instance_count: int
    unique_image_count: int
    image_area_ratio: float

    # Decision signals
    full_page_image: bool
    vision_candidate: bool


def rectangle_union_area(
    rects: list[pymupdf.Rect],
) -> float:
    """
    Calculate the union area of axis-aligned rectangles.

    This avoids counting overlapping image areas multiple times.
    """

    if not rects:
        return 0.0

    # Collect all unique X coordinates
    x_coords = sorted(
        {
            x
            for rect in rects
            for x in (rect.x0, rect.x1)
        }
    )

    total_area = 0.0

    for i in range(len(x_coords) - 1):
        x_left = x_coords[i]
        x_right = x_coords[i + 1]

        if x_right <= x_left:
            continue

        # Find rectangles covering this vertical strip
        y_intervals = []

        for rect in rects:
            if rect.x0 <= x_left and rect.x1 >= x_right:
                y_intervals.append((rect.y0, rect.y1))

        if not y_intervals:
            continue

        # Merge overlapping Y intervals
        y_intervals.sort()

        merged = []
        current_start, current_end = y_intervals[0]

        for start, end in y_intervals[1:]:
            if start <= current_end:
                current_end = max(current_end, end)
            else:
                merged.append((current_start, current_end))
                current_start = start
                current_end = end

        merged.append((current_start, current_end))

        covered_y = sum(
            end - start
            for start, end in merged
        )

        strip_width = x_right - x_left

        total_area += strip_width * covered_y

    return total_area


def analyze_page(
    page: pymupdf.Page,
) -> PageAnalysis:

    # -------------------------------------------------
    # 1. Text
    # -------------------------------------------------

    text = page.get_text("text", sort=True).strip()
    text_chars = len(text)

    # -------------------------------------------------
    # 2. Native tables
    # -------------------------------------------------

    tables = page.find_tables()
    native_table_count = len(tables.tables)

    # -------------------------------------------------
    # 3. Images
    # -------------------------------------------------

    image_infos = page.get_image_info(hashes=True)

    image_instance_count = len(image_infos)

    unique_digests = {
        info["digest"]
        for info in image_infos
        if info.get("digest") is not None
    }

    unique_image_count = len(unique_digests)

    # -------------------------------------------------
    # 4. Image coverage
    # -------------------------------------------------

    page_rect = page.rect

    image_rects = []

    for info in image_infos:

        bbox = info.get("bbox")

        if not bbox:
            continue

        rect = pymupdf.Rect(bbox)

        # Keep only the part inside the page
        rect = rect & page_rect

        if rect.width <= 0 or rect.height <= 0:
            continue

        image_rects.append(rect)

    union_area = rectangle_union_area(image_rects)

    page_area = page_rect.width * page_rect.height

    if page_area > 0:
        image_area_ratio = union_area / page_area
    else:
        image_area_ratio = 0.0

    # Safety clamp
    image_area_ratio = min(max(image_area_ratio, 0.0), 1.0)

    # -------------------------------------------------
    # 5. Full-page image signal
    # -------------------------------------------------

    full_page_image = any(
        (
            rect.width / page_rect.width >= 0.85
            and rect.height / page_rect.height >= 0.85
        )
        for rect in image_rects
    )

    # -------------------------------------------------
    # 6. Decide whether page is a Vision candidate
    # -------------------------------------------------

    vision_candidate = (
        # A. Very little extracted text but images exist
        (
            text_chars < 150
            and image_instance_count > 0
        )

        # B. Image covers most of page
        or image_area_ratio >= 0.70

        # C. Many images on the page
        or image_instance_count >= 5

        # D. Native table + images
        or (
            native_table_count > 0
            and image_instance_count > 0
        )

        # E. Full-page visual
        or full_page_image
    )

    return PageAnalysis(
        page_number=page.number + 1,
        text_chars=text_chars,
        native_table_count=native_table_count,
        image_instance_count=image_instance_count,
        unique_image_count=unique_image_count,
        image_area_ratio=image_area_ratio,
        full_page_image=full_page_image,
        vision_candidate=vision_candidate,
    )