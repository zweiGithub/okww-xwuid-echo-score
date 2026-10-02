"""Small, geometry-only consensus tracker for the two supported Echo panels.

No recognized label or number is replayed. Every usable result comes from OCR
of the current frame; this module only retains the panel's text-only regions.
"""
from dataclasses import dataclass
from statistics import median


def _consensus(values, tolerance, minimum=2):
    values = list(values)
    if len(values) < minimum:
        return None
    clusters = [[v for v in values if abs(v-anchor) <= tolerance] for anchor in values]
    best = max(clusters, key=len)
    if len(best) < minimum or len(best)*2 <= len(values):
        return None
    return float(median(best))


def _grid(centers, tolerance):
    """Fit main and substat spacing independently; one row defines no spacing."""
    if len(centers) < 2:
        return tuple(centers)
    slopes = [(b-a)/(j-i) for i,a in enumerate(centers)
              for j,b in enumerate(centers) if j > i]
    step = float(median(slopes))
    origin = float(median(c-i*step for i,c in enumerate(centers)))
    fit = tuple(origin+i*step for i in range(len(centers)))
    if step <= tolerance*2 or sum(abs(a-b) <= tolerance for a,b in zip(centers,fit))*2 <= len(centers):
        return None
    return fit


@dataclass(frozen=True)
class PanelLayout:
    left: int
    value_left: int
    right: int
    main_centers: tuple
    sub_centers: tuple
    main_height: int
    sub_height: int
    glyph_width: float

    @property
    def centers(self):
        return self.main_centers + self.sub_centers

    def regions(self, width, height):
        return tuple((self.left, max(0,round(centers[0]-row_height/2)),
                      min(width,self.right), min(height,round(centers[-1]+row_height/2)))
                     for centers,row_height in ((self.main_centers,self.main_height),
                                                 (self.sub_centers,self.sub_height)) if centers)


class EchoLayoutTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self.key = None
        self.layout = None
        self.signatures = ()

    def locate(self, rows, width, height, page):
        key = (page, width, height)
        if key != self.key:
            self.reset()
            self.key = key
        if len(rows) < 2:
            self.layout = None
            return None, '词条布局证据不足'
        glyph_height = float(median(row.label_bounds[3] for row in rows))
        tolerance = max(3, glyph_height*.25)
        left = _consensus((row.text_start for row in rows if row.text_start is not None), tolerance)
        right = _consensus((row.value_bounds[0]+row.value_bounds[2] for row in rows), tolerance)
        vertical = [(min(row.label_bounds[1],row.value_bounds[1]),
                     max(row.label_bounds[1]+row.label_bounds[3],
                         row.value_bounds[1]+row.value_bounds[3])) for row in rows]
        centers = tuple((top+bottom)/2 for top,bottom in vertical)
        main = _grid(centers[:2], tolerance)
        subs = _grid(centers[2:], tolerance)
        if left is None or right is None or main is None or subs is None:
            self.layout = None
            return None, '词条布局正在重新定位'
        main_height = round(median(bottom-top for top,bottom in vertical[:2])+max(4,glyph_height/3))
        sub_height = round(median(bottom-top for top,bottom in vertical[2:])+max(4,glyph_height/3)) if len(rows)>2 else main_height
        glyph_widths = [row.text_width/len(row.clean_label) for row in rows if row.clean_label and row.text_width > 0]
        glyph_width = float(median(glyph_widths)) if glyph_widths else glyph_height
        # Values are right-aligned; do not let a shorter new value narrow its ROI.
        value_left = round(right-max(glyph_height*4.5, max(row.value_bounds[2] for row in rows)))
        candidate = PanelLayout(round(left-3), value_left, round(right+4), main, subs,
                                main_height, sub_height, glyph_width)
        if candidate.left >= candidate.value_left or candidate.main_height >= main[1]-main[0]:
            self.layout = None
            return None, '词条布局正在重新定位'
        old = self.layout
        # Candidate identity is used only to detect a transition, never to score.
        # Icon-prefixed main rows still have fresh values that can prove this
        # is a different Echo; their crop must verify the candidate later.
        signatures = tuple((row.clean_label,row.value_text) if row.clean_label else None for row in rows)
        if old is not None:
            # A strict subset with unchanged values may be a dropped OCR row.
            # Keep the missing-row diagnostic until evidence changes or the page
            # is reacquired; never silently reinterpret it as an unlocked slot.
            if len(rows) < len(old.centers):
                matches = [next((i for i,c in enumerate(old.centers) if abs(c-y)<=tolerance),None) for y in centers]
                if (all(i is not None for i in matches)
                        and all(s is None or s == self.signatures[i] for s,i in zip(signatures,matches))):
                    return None, '词条行缺失，请重新打开声骸页面'
            # Hold only within the crop margin; wider motion must reacquire
            # before the old ROI can clip the first glyph or the last digit.
            hold_tolerance = min(3, glyph_height*.125)
            same_count = len(old.centers) == len(candidate.centers)
            same_columns = all(abs(a-b)<=hold_tolerance for a,b in (
                (old.left,candidate.left),(old.right,candidate.right),
                (old.main_height,candidate.main_height),(old.sub_height,candidate.sub_height)))
            old_regions = old.regions(width,height)
            enclosed = all(old_regions[0 if i<2 else 1][1] <= top
                           and bottom <= old_regions[0 if i<2 else 1][3]
                           for i,(top,bottom) in enumerate(vertical)) if same_count else False
            if same_count and same_columns and enclosed and all(abs(a-b)<=hold_tolerance for a,b in zip(old.centers,candidate.centers)):
                candidate = old
        self.layout = candidate
        self.signatures = signatures
        return candidate, ''
