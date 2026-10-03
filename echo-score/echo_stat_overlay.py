"""OCR-row grouping and native painting for the Echo stat debug overlay."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, replace
from decimal import Decimal
import os
import math
import re
from types import SimpleNamespace

from echo_score import (
    auto_match_template, calculate_echo_score, resolve_template_name,
    substat_tier, substat_tier_label, template_names,
)
from echo_text import simplify_echo_text
from echo_probability import (
    TuningProbabilityError, calculate_tuning_probability, format_probability,
)


ECHO_STAT_PAINTER_KEY = "echo-stat-boxes"
TIER_TEXT_COLOR = (80, 185, 255)
LOWEST_TIER_TEXT_COLOR = (80, 235, 130)
HIGHEST_TIER_TEXT_COLOR = (255, 75, 75)
SUMMARY_TEMPLATE_COLOR = (110, 220, 255)
SUMMARY_CURRENT_COLOR = (255, 220, 80)
SUMMARY_POTENTIAL_COLOR = (120, 235, 150)
SUMMARY_LEFT_RATIO = 0.43
SUMMARY_TOP_RATIO = 0.24
SUMMARY_RIGHT_RATIO = 0.75
SUMMARY_MAX_LINES = 10
_STAT_TEXT = re.compile(
    r"攻击|生命|防御|暴击|共鸣效率|伤害加成|治疗效果|ATK|HP|DEF|Crit|Energy|DMG|Heal",
    re.IGNORECASE,
)
_VALUE_TEXT = re.compile(
    r"^\s*(?:[+＋]?\d+(?:[.,]\d+)?|[.·。]\d{2,4})\s*[%％]?\s*$"
)


@dataclass(frozen=True)
class StatRectangle:
    x: int
    y: int
    width: int
    height: int
    color: tuple[int, int, int]
    tier_x: int = 0
    tier_y: int = 0
    tier_font_size: int = 18


@dataclass(frozen=True)
class RecognizedStatRow:
    x: int
    y: int
    width: int
    height: int
    stat_name: str
    value: float
    value_text: str
    tier_x: int
    tier_y: int
    recognition_valid: bool = True
    raw_stat_name: str = ""
    label_bounds: tuple = ()
    value_bounds: tuple = ()

    def rectangle(self, color):
        return StatRectangle(
            self.x, self.y, self.width, self.height, color, self.tier_x, self.tier_y
        )


@dataclass(frozen=True)
class EchoStatAnalysis:
    rectangles: tuple[StatRectangle, ...]
    row_scores: tuple[float, ...]
    summary: str
    tier_labels: tuple[str, ...] = ()
    tier_colors: tuple[tuple[int, int, int], ...] = ()
    selected_template: str = ""
    raw_rows: tuple[RecognizedStatRow, ...] = ()
    read_rows: tuple[RecognizedStatRow, ...] = ()


def find_echo_stat_rectangles(ocr_boxes, screen_width, screen_height):
    """Build rows from the exact OCR Boxes rendered by the debug overlay."""
    return list(analyze_echo_stats(ocr_boxes, screen_width, screen_height, "通用", show_probability=False).rectangles)


def analyze_echo_stats(ocr_boxes, screen_width, screen_height, template_name,
                       auto_match=False, remembered_template=None, show_probability=True,
                       target_score=40.0, probability_service=None):
    """Recognize one Echo panel from this frame's raw OCR boxes."""
    if not screen_width or not screen_height:
        return EchoStatAnalysis((), (), "")

    # Keep the OCR geometry unchanged. Only labels are normalized; OKWW's
    # auto_simplify depends on the application locale, not the game's locale.
    ocr_boxes = [SimpleNamespace(
        x=box.x, y=box.y, width=box.width, height=box.height,
        name=simplify_echo_text(box.name),
        raw_stat_name=str(box.name),
    ) for box in ocr_boxes]

    screen_text = " ".join(str(box.name) for box in ocr_boxes)
    matched_template = auto_match_template(ocr_boxes) if auto_match else None
    automatic_template = matched_template or (remembered_template if auto_match else None)
    if automatic_template:
        template_name = automatic_template
    if template_name == "通用" or any(name.startswith(f"{template_name}-") for name in template_names()):
        template_name = resolve_template_name(template_name)
    is_tuning_page = any(marker in screen_text for marker in (
        "声骸强化", "强化并调谐", "已完成全部调谐", "Echo Enhancement",
    ))
    is_single_echo_page = any(marker in screen_text for marker in (
        "声骸技能", "合鸣效果", "Echo Skill", "Sonata Effect",
    ))

    left_rows, left_problem = _find_ocr_rows(
        ocr_boxes, screen_width * 0.09, screen_width * 0.38,
        screen_height * 0.20, screen_height * 0.54, with_diagnostics=True,
    )
    right_rows, right_problem = _find_ocr_rows(
        ocr_boxes, screen_width * 0.76, screen_width * 0.99,
        screen_height * 0.18, screen_height * 0.47, with_diagnostics=True,
    )
    # Restrict raw stat pairing to the recognized Echo page, avoiding ordinary
    # Resonator Attribute Details and multi-Echo summary panels.
    if is_tuning_page and len(left_rows) >= 2:
        rows, recognition_problem = left_rows, left_problem
    elif is_single_echo_page and len(right_rows) >= 2:
        rows, recognition_problem = right_rows, right_problem
    else:
        return EchoStatAnalysis((), (), "", selected_template=matched_template or "")
    raw_rows = tuple(rows)
    if recognition_problem:
        return EchoStatAnalysis((), (), f"{'概率' if show_probability else '识别'}暂不可用：{recognition_problem}",
                                selected_template=matched_template or '', raw_rows=raw_rows)

    rows = rows[:7]
    main_rows, sub_rows = rows[:2], rows[2:]
    cost = _find_cost(ocr_boxes, main_rows)
    cost_key = _cost_key(cost, main_rows)
    rectangles = tuple(row.rectangle((255, 0, 0) if i<2 else (255, 255, 255))
                       for i,row in enumerate(rows))
    rectangles = _badge_column(rectangles, raw_rows, screen_width)
    tier_labels = ("", "") + tuple(substat_tier_label(row.stat_name, row.value) for row in rows[2:])
    tier_colors = ((255, 0, 0), (255, 0, 0)) + tuple(
        _tier_text_color(substat_tier(row.stat_name, row.value)) for row in sub_rows
    )
    try:
        score = calculate_echo_score(template_name, cost, cost_key, main_rows, sub_rows)
    except (OverflowError, ValueError, TypeError):
        return EchoStatAnalysis(rectangles, (), '概率暂不可用：词条数值识别异常' if show_probability else '',
                                selected_template=matched_template or '',raw_rows=raw_rows,read_rows=tuple(rows),
                                tier_labels=tier_labels,tier_colors=tier_colors)
    if score is None:
        return EchoStatAnalysis(rectangles, (), "", selected_template=matched_template or "",raw_rows=raw_rows,read_rows=tuple(rows),
                                tier_labels=tier_labels,tier_colors=tier_colors)
    summary = (
        f"评分模板：{template_name}{' (自动匹配)' if automatic_template else ''}\n"
        f"当前评分：{score.current_score:.2f}\n"
        f"理论最高：{score.potential_score:.2f}"
    )
    if show_probability:
        if any(marker in screen_text for marker in ('重构', '重塑', 'Reconstruction', 'Reconstruct')):
            recognition_problem = '重构/锁定重抽不适用'
        summary += '\n' + _probability_summary(
            template_name, cost, main_rows, sub_rows, target_score,
            recognition_problem, probability_service,
        )
    return EchoStatAnalysis(
        rectangles, score.row_scores, summary, tier_labels, tier_colors,
        matched_template or "", raw_rows, tuple(rows),
    )


def _probability_summary(template_name, cost, main_rows, sub_rows, target_score,
                         recognition_problem, service):
    scope = f'五星普通估算 · 已识别{len(sub_rows)}/5'
    caveat = '核对完整词条；重构不适用'
    if recognition_problem:
        return f'{scope}\n概率暂不可用：{recognition_problem}'
    if service is not None:
        state = service.request(template_name, cost, main_rows, sub_rows, target_score)
        if state.status == 'pending':
            return f'{scope}\n概率计算中…\n{caveat}'
        if state.status != 'ready':
            return f'{scope}\n概率暂不可用：{state.reason}'
        projection = state.result
    else:
        try:
            projection = calculate_tuning_probability(template_name, cost, main_rows, sub_rows, target_score)
        except TuningProbabilityError as error:
            return f'{scope}\n概率暂不可用：{error}'
    precise_target = Decimal(str(target_score))
    target_label = (f'{precise_target:.2f}'
                    if precise_target < 1e6 and precise_target == precise_target.quantize(Decimal('.01'))
                    else str(precise_target))
    return (
        f'{scope}\n'
        f'期望终分：{projection.expected_score:.2f}\n'
        f'达理论最高：{format_probability(projection.probability_at_potential)}\n'
        f'目标≥{target_label}：{format_probability(projection.probability_at_target)}\n'
        f'{caveat}'
    )


def _clean_stat_label(text):
    # Normalize whitespace only. Icon prefixes remain part of the raw label.
    return re.sub(r'\s+', '', str(text))


def _exact_stat_label(text):
    # Retain raw-label completeness as informational metadata only. Scoring
    # and probability both consume the canonical name from the shared parser.
    compact = _clean_stat_label(text)
    return compact in {
        '攻击', '攻击力', '生命', '生命值', '防御', '防御力', '暴击', '暴击率', '暴击伤害',
        '共鸣效率', '普攻伤害加成', '重击伤害加成', '共鸣技能伤害加成', '共鸣解放伤害加成',
        '冷凝伤害加成', '热熔伤害加成', '导电伤害加成', '气动伤害加成',
        '衍射伤害加成', '湮灭伤害加成', '治疗效果加成',
    }


def _find_ocr_rows(ocr_boxes, min_x, max_x, min_y, max_y, with_diagnostics=False):
    candidates = [box for box in ocr_boxes if min_x <= box.x <= max_x and min_y <= box.y <= max_y]
    properties = [box for box in candidates if _STAT_TEXT.search(str(box.name))]
    values = [box for box in candidates if _VALUE_TEXT.match(str(box.name))]
    rows = []
    used_values = set()
    for prop in sorted(properties, key=lambda box: (box.y + box.height / 2, box.x)):
        prop_center = prop.y + prop.height / 2
        matches = [
            value for value in values
            if id(value) not in used_values
            and value.x >= prop.x + prop.width * 0.5
            and abs((value.y + value.height / 2) - prop_center)
            <= max(9, min(prop.height, value.height) * 0.60)
        ]
        if not matches:
            continue
        value = min(matches, key=lambda item: abs((item.y + item.height / 2) - prop_center))
        used_values.add(id(value))
        left, top = min(prop.x, value.x) - 5, min(prop.y, value.y) - 3
        right = max(prop.x + prop.width, value.x + value.width) + 5
        bottom = max(prop.y + prop.height, value.y + value.height) + 3
        value_text = str(value.name)
        label = str(prop.name)
        rows.append(RecognizedStatRow(
            round(left), round(top), round(right - left), round(bottom - top),
            _normalize_stat_name(label, value_text),
            _numeric_value(value_text), value_text,
            round(prop.x + prop.width + 8),
            round(prop.y + max(0, (prop.height - 18) / 2)),
            _exact_stat_label(label),
            str(getattr(prop, 'raw_stat_name', prop.name)),
            (prop.x, prop.y, prop.width, prop.height),
            (value.x, value.y, value.width, value.height),
        ))
    if with_diagnostics:
        problem = ''
        if len(rows) > 7:
            problem = '识别到过多词条'
        elif len(rows) != len(properties) or len(used_values) != len(values):
            problem = '存在未配对的名称或数值'
        return rows[:7], problem
    return rows[:7]


def _badge_column(rectangles, raw_rows, screen_width):
    """Reserve a fixed strip outside the names/icons, away from score text.

    The strip uses current panel geometry, never a previous name length.
    Its font shrinks for narrow margins/short rows rather than hiding a tier.
    """
    if len(rectangles)<3:
        return rectangles
    left = min(min(row.x,row.label_bounds[0]) for row in raw_rows)
    # The same supported panel-column boundary used by row acquisition keeps
    # badges away from icons even when every OCR label excludes the icon.
    panel_left = screen_width * (.09 if left<screen_width*.5 else .76)
    right = max(2, math.floor(min(left,panel_left)-4))
    size = max(1, min(18, right//2, min(r.height-2 for r in rectangles[2:])))
    x = right-2*size
    return tuple(replace(r,tier_x=x,tier_y=round(r.y+(r.height-size)/2),tier_font_size=size)
                 if i>=2 else r for i,r in enumerate(rectangles))


def _numeric_value(text):
    match = re.search(r"\d+(?:[.,]\d+)?", str(text).replace("，", "."))
    return float(match.group(0).replace(",", ".")) if match else 0.0


def _normalize_stat_name(text, value_text):
    compact = _clean_stat_label(text)
    is_percent = "%" in value_text or "％" in value_text
    if "暴击伤害" in compact:
        return "暴击伤害"
    if "暴击" in compact:
        return "暴击"
    if "共鸣效率" in compact:
        return "共鸣效率"
    if "普攻" in compact:
        return "普攻"
    if "重击" in compact:
        return "重击"
    if "共鸣技能" in compact:
        return "共鸣技能"
    if "共鸣解放" in compact:
        return "共鸣解放"
    for name in ("攻击", "防御", "生命"):
        if name in compact:
            # XW-UID names percentage rolls with a trailing percent marker;
            # the unmarked name is the fixed companion/main property.
            return f"{name}%" if is_percent else name
    return compact


def _find_cost(ocr_boxes, main_rows):
    for box in ocr_boxes:
        match = re.search(r"COST\s*([134])", str(box.name), re.IGNORECASE)
        if match:
            return int(match.group(1))

    cost_labels = [box for box in ocr_boxes if re.search(r"COST", str(box.name), re.IGNORECASE)]
    digits = [box for box in ocr_boxes if str(box.name).strip() in {"1", "3", "4"}]
    for label in cost_labels:
        nearby = [
            box for box in digits
            if box.x >= label.x - 10 and box.x <= label.x + label.width + 150
            and abs((box.y + box.height / 2) - (label.y + label.height / 2)) < 35
        ]
        if nearby:
            return int(min(nearby, key=lambda box: abs(box.x - label.x)).name)

    first = main_rows[0]
    name, value = first.stat_name, first.value
    if "伤害加成" in name or name == "共鸣效率":
        return 3
    if name in {"暴击", "暴击伤害"} or "治疗" in name:
        return 4
    targets = (22.8, 38.0, 41.5) if name == "防御%" else (18.0, 30.0, 33.0)
    return (1, 3, 4)[min(range(3), key=lambda index: abs(value - targets[index]))]


def _cost_key(cost, main_rows):
    if cost != 3:
        return f"{cost}C"
    main_name = main_rows[0].stat_name
    elemental_names = ("冷凝", "热熔", "导电", "气动", "衍射", "湮灭")
    if any(name in main_name for name in elemental_names) and "伤害加成" in main_name:
        return "3C属伤"
    if "攻击" in main_name:
        return "3C攻击"
    return "3C其它"


def _tier_text_color(tier):
    if not tier:
        return TIER_TEXT_COLOR
    index, total = tier
    if index == 1:
        return LOWEST_TIER_TEXT_COLOR
    if index == total:
        return HIGHEST_TIER_TEXT_COLOR
    return TIER_TEXT_COLOR


class EchoStatBoxPainter:
    def __init__(self):
        self.rectangles = []
        self.row_scores = []
        self.summary = ""
        self.tier_labels = []
        self.tier_colors = []

    def update(self, rectangles, row_scores=(), summary="", tier_labels=(), tier_colors=()):
        self.rectangles = list(rectangles)
        self.row_scores = list(row_scores)
        self.summary = summary
        self.tier_labels = list(tier_labels)
        self.tier_colors = list(tier_colors)

    def paint(self, canvas, _overlay):
        for index, rectangle in enumerate(self.rectangles):
            canvas.rectangle(
                rectangle.x, rectangle.y, rectangle.width, rectangle.height,
                color=rectangle.color, line_width=1,
            )
            if index < len(self.row_scores):
                score_x = rectangle.x + rectangle.width + 8
                score_lines = _score_lines(rectangle, self.row_scores[index])
                line_height = max(13, min(18, rectangle.height // 2))
                for line_index, line in enumerate(score_lines):
                    if not line:
                        continue
                    canvas.text(
                        score_x,
                        rectangle.y + line_index * line_height,
                        line,
                        color=rectangle.color,
                    )
            tier_label = self.tier_labels[index] if index < len(self.tier_labels) else ""
            if tier_label:
                tier_color = self.tier_colors[index] if index < len(self.tier_colors) else TIER_TEXT_COLOR
                _paint_bold_text(
                    canvas,
                    rectangle.tier_x,
                    rectangle.tier_y,
                    tier_label,
                    tier_color,
                    rectangle.tier_font_size,
                )
        if self.summary:
            _paint_score_summary(canvas, _overlay, self.summary)


def _score_lines(rectangle, score):
    if abs(score) < 0.005:
        return ()
    if rectangle.color == (255, 0, 0):
        return (f"+{score:.2f}",)
    return (f"+{score:.2f}",)


def _paint_bold_text(canvas, x, y, text, color, font_size=18):
    """Paint an OCR-adjacent tier label with a readable bold native font."""
    if os.name != "nt":
        canvas.text(x, y, text, color=color)
        return
    from ok.ui.overlay import win32_gdi

    font = win32_gdi.gdi32.CreateFontW(
        -max(1, round(font_size * canvas.ratio)), 0, 0, 0, 700, 0, 0, 0,
        1, 0, 0, 5, 0, "Microsoft YaHei UI",
    )
    old_font = win32_gdi.gdi32.SelectObject(canvas.hdc, font)
    try:
        win32_gdi.gdi32.SetBkMode(canvas.hdc, 1)
        win32_gdi.gdi32.SetTextColor(canvas.hdc, win32_gdi._rgb(*color))
        win32_gdi.gdi32.TextOutW(
            canvas.hdc, round(x * canvas.ratio), round(y * canvas.ratio), text, len(text)
        )
    finally:
        win32_gdi.gdi32.SelectObject(canvas.hdc, old_font)
        win32_gdi.gdi32.DeleteObject(font)


def _fit_summary_lines(text, measure, max_width, max_lines):
    """Wrap within a fixed area; bound arbitrary OCR diagnostic length."""
    result = []
    source = text.splitlines()
    for source_index, line in enumerate(source):
        for part_index in range(2):
            if len(result) >= max_lines:
                return result
            remaining_slot = len(result) == max_lines - 1
            truncate = part_index == 1 or remaining_slot
            suffix = "…" if truncate and (measure(line) > max_width
                         or remaining_slot and source_index < len(source) - 1) else ""
            if measure(line + suffix) <= max_width:
                result.append((source_index, line + suffix))
                break
            cut = 0
            while cut < len(line) and measure(line[:cut + 1] + suffix) <= max_width:
                cut += 1
            result.append((source_index, line[:cut] + suffix))
            line = line[cut:]
            if truncate:
                break
    return result


def _paint_score_summary(canvas, overlay, text):
    if os.name != "nt":
        return
    from ok.ui.overlay import win32_gdi

    width = round(getattr(overlay, "_frame_width", 0) * canvas.ratio)
    height = round(getattr(overlay, "_frame_height", 0) * canvas.ratio)
    if width <= 0 or height <= 0:
        return
    font = win32_gdi.gdi32.CreateFontW(
        -max(26, round(height * 0.034)), 0, 0, 0, 700, 0, 0, 0,
        1, 0, 0, 5, 0, "Microsoft YaHei UI",
    )
    old_font = win32_gdi.gdi32.SelectObject(canvas.hdc, font)
    try:
        x = round(width * SUMMARY_LEFT_RATIO)
        y = round(height * SUMMARY_TOP_RATIO)
        max_width = max(1, round(width * SUMMARY_RIGHT_RATIO) - x)
        # Font metrics, rather than the current text, define row positions.
        size = win32_gdi.SIZE()
        win32_gdi.gdi32.GetTextExtentPoint32W(canvas.hdc, "声骸Ag", 4, ctypes.byref(size))
        line_height = size.cy + max(4, round(height * 0.008))

        def measure(line):
            extent = win32_gdi.SIZE()
            win32_gdi.gdi32.GetTextExtentPoint32W(
                canvas.hdc, line, len(line), ctypes.byref(extent))
            return extent.cx

        lines = _fit_summary_lines(text, measure, max_width, SUMMARY_MAX_LINES)
        line_colors = (SUMMARY_TEMPLATE_COLOR, SUMMARY_CURRENT_COLOR, SUMMARY_POTENTIAL_COLOR)
        for index, (source_index, line) in enumerate(lines):
            line_y = y + index * line_height
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                win32_gdi.gdi32.SetTextColor(canvas.hdc, win32_gdi._rgb(0, 0, 0))
                win32_gdi.gdi32.TextOutW(
                    canvas.hdc, x + dx, line_y + dy, line, len(line)
                )
            color = line_colors[source_index] if source_index < len(line_colors) else SUMMARY_CURRENT_COLOR
            win32_gdi.gdi32.SetTextColor(canvas.hdc, win32_gdi._rgb(*color))
            win32_gdi.gdi32.TextOutW(canvas.hdc, x, line_y, line, len(line))
    finally:
        win32_gdi.gdi32.SelectObject(canvas.hdc, old_font)
        win32_gdi.gdi32.DeleteObject(font)
