"""Optional horizontal references. Raw per-row reading never depends on a fit."""
from dataclasses import dataclass, replace
import math
import re
from statistics import median

from echo_text import simplify_echo_text


def _consensus(values, tolerance, minimum=2):
    values = [float(v) for v in values if v is not None and math.isfinite(v)]
    if len(values) < minimum:
        return None
    clusters = [[v for v in values if abs(v-anchor) <= tolerance] for anchor in values]
    best = max(clusters, key=len)
    if len(best) < minimum or len(best)*2 <= len(values):
        return None
    return float(median(best))


@dataclass(frozen=True)
class ColumnLayout:
    left: float | None
    main_right: float | None
    sub_right: float | None
    text_left: float | None = None
    witnesses: tuple = ()
    text_validated: bool = False


class EchoLayoutTracker:
    """Retain only X references, never old names, numbers, Y or row spacing."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.key = None
        self.layout = None

    def locate(self, rows, width, height, page):
        key = (page, width, height)
        if key != self.key:
            self.reset()
            self.key = key
        tolerance = max(2, width*.0015)
        left = _consensus((r.label_bounds[0] for r in rows), tolerance*1.5)
        right = lambda group: _consensus((r.value_bounds[0]+r.value_bounds[2] for r in group), tolerance)
        # A valid short label can still have an icon-inclusive OCR box. Text
        # anchors require a majority among complete, unprefixed long names,
        # with at least two distinct names. No glyph-width/icon-width guessing.
        evidence = [(i,r) for i,r in enumerate(rows) if len(r.clean_label)>=4
                    and r.recognition_valid and r.clean_label == re.sub(
                        r'\s+', '', simplify_echo_text(r.raw_stat_name))]
        text_left = _consensus((r.label_bounds[0] for i,r in evidence), tolerance)
        witnesses = tuple(i for i,r in evidence if text_left is not None
                          and abs(r.label_bounds[0]-text_left)<=tolerance)
        if len({rows[i].clean_label for i in witnesses}) < 2:
            text_left, witnesses = None, ()
        candidate = ColumnLayout(left,right(rows[:2]),right(rows[2:]),text_left,witnesses)
        old = self.layout
        if old is not None:
            # Detect coherent horizontal movement independently of row Y/count.
            pairs = [(getattr(old,k),getattr(candidate,k)) for k in ('left','main_right','sub_right')]
            moved = any(a is not None and b is not None and abs(a-b)>tolerance*2 for a,b in pairs)
            if not moved:
                held = {}
                for name in ('left','main_right','sub_right','text_left'):
                    a,b = getattr(old,name),getattr(candidate,name)
                    if a is not None and (b is None or abs(a-b)<=tolerance):
                        held[name] = a
                candidate = replace(candidate,**held)
                if candidate.text_left == old.text_left:
                    candidate = replace(candidate,text_validated=old.text_validated)
        self.layout = candidate
        return candidate, ''

    def confirm_text(self):
        """Remember only a validated X boundary for display, never OCR values."""
        self.layout = replace(self.layout,text_validated=True)
        return self.layout
