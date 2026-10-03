"""A geometry-only cache: fixed OCR rectangles and fixed rendering anchors."""
from dataclasses import dataclass, replace
import math
import re
from types import SimpleNamespace

from echo_score import SUBSTAT_TIERS
from echo_text import simplify_echo_text
from echo_stat_overlay import _find_ocr_rows

_TUNING = ('声骸强化','强化并调谐','已完成全部调谐','Echo Enhancement')
_DETAIL = ('声骸技能','合鸣效果','Echo Skill','Sonata Effect')


def _page(boxes):
    text = ' '.join(simplify_echo_text(str(b.name)) for b in boxes)
    return 'tuning' if any(m in text for m in _TUNING) else 'detail' if any(m in text for m in _DETAIL) else None


def _cost_boxes(boxes):
    """Find the same explicit COST source as scoring, without retaining its value."""
    for box in boxes:
        if re.search(r'COST\s*[134]',str(box.name),re.I):
            return (box,)
    digits=[b for b in boxes if str(b.name).strip() in {'1','3','4'}]
    for label in boxes:
        if not re.search('COST',str(label.name),re.I):
            continue
        nearby=[b for b in digits if label.x-10<=b.x<=label.x+label.width+150
                and abs((b.y+b.height/2)-(label.y+label.height/2))<35]
        if nearby:
            return label,min(nearby,key=lambda b:abs(b.x-label.x))
    return ()


def valid_read_rows(rows):
    """Reading success needs complete names, units, numbers and substat rolls."""
    if not 2<=len(rows)<=7:
        return False
    names = set()
    for i,row in enumerate(rows):
        if not row.recognition_valid or not math.isfinite(row.value) or row.value<=0:
            return False
        percent = '%' in row.value_text or '％' in row.value_text
        if percent == (row.stat_name in {'攻击','防御','生命'}):
            return False
        if i>=2:
            tiers = SUBSTAT_TIERS.get(row.stat_name,())
            if row.stat_name in names or not any(math.isclose(row.value,v,rel_tol=0,abs_tol=1e-9) for v in tiers):
                return False
            names.add(row.stat_name)
    return True


@dataclass(frozen=True)
class EchoRegionCache:
    width: int
    height: int
    page: str
    guard_roi: tuple
    count_roi: tuple
    cost_roi: tuple | None
    row_rois: tuple
    rectangles: tuple

    @classmethod
    def acquire(cls, boxes, analysis, width, height):
        rows = analysis.read_rows
        page = _page(boxes)
        if not page or not valid_read_rows(rows) or len(analysis.rectangles)!=len(rows):
            return None
        # This guard spans every supported slot, not just currently unlocked rows.
        count = ((width*.09,height*.20,width*.38,height*.54) if page=='tuning' else
                 (width*.76,height*.18,width*.99,height*.47))
        # Fixed sidebars, independent of unrelated inventory COST filters or
        # metadata found elsewhere. Newly appearing page/context text is read.
        guard = ((0,0,math.ceil(width*.42),height) if page=='tuning' else
                 (math.floor(width*.74),0,width,height))
        pad = max(3,width*.002)
        rois=[]
        for row,anchor in zip(rows,analysis.rectangles):
            x,y,w,h = row.label_bounds
            vx,vy,vw,vh = row.value_bounds
            rois.append((max(0,math.floor(anchor.x-pad)),max(0,math.floor(min(y,vy)-pad)),
                         min(width,math.ceil(max(anchor.x+anchor.width,vx+vw)+pad)),
                         min(height,math.ceil(max(y+h,vy+vh)+pad))))
        cost = _cost_boxes(boxes)
        if not cost:
            # Do not lock an inferred COST while its actual metadata location
            # is unknown; the next acquisition may recover that missing text.
            return None
        cost_roi = ((max(0,math.floor(min(b.x for b in cost)-pad)),
                     max(0,math.floor(min(b.y for b in cost)-pad)),
                     min(width,math.ceil(max(b.x+b.width for b in cost)+pad)),
                     min(height,math.ceil(max(b.y+b.height for b in cost)+pad))) if cost else None)
        # A metadata crop is deliberately small; never disguise a whole frame
        # as one COST ROI when an unrelated paragraph happens to mention it.
        if cost_roi and (cost_roi[2]-cost_roi[0]>width*.35 or cost_roi[3]-cost_roi[1]>height*.12):
            return None
        if any(not all(math.isfinite(v) for v in roi) or roi[2]<=roi[0] or roi[3]<=roi[1]
               for roi in [guard,*rois]):
            return None
        return cls(width,height,page,guard,count,cost_roi,tuple(rois),tuple(analysis.rectangles))

    def read(self, ocr):
        """Return only current-frame content, or fail without partial old rows."""
        def crop(roi):
            x,y,right,bottom=roi
            boxes=ocr(x=x/self.width,y=y/self.height,to_x=right/self.width,to_y=bottom/self.height)
            # Host OCR boxes use screen coordinates. Reject out-of-crop results.
            if any(not all(math.isfinite(v) for v in (b.x,b.y,b.width,b.height))
                   or b.width<=0 or b.height<=0 or b.x<x-.01 or b.y<y-.01
                   or b.x+b.width>right+.01 or b.y+b.height>bottom+.01 for b in boxes):
                raise ValueError('OCR outside cached region')
            return boxes
        try:
            guard = crop(self.guard_roi)
            if _page(guard)!=self.page:
                return None
            normalize = lambda boxes: [SimpleNamespace(x=b.x,y=b.y,width=b.width,height=b.height,
                name=simplify_echo_text(str(b.name)),raw_stat_name=str(b.name)) for b in boxes]
            x,y,right,bottom=self.count_roi
            guard_rows,problem=_find_ocr_rows(normalize(guard),x,right,y,bottom,with_diagnostics=True)
            # A guard may include one icon prefix. It supplies a candidate only;
            # the dedicated row crop must independently confirm the exact name.
            if (problem or len(guard_rows)!=len(self.row_rois)
                    or any(not row.clean_label for row in guard_rows)
                    or not valid_read_rows([replace(row,recognition_valid=True) for row in guard_rows])):
                return None
            rows=[]
            for roi,guard_row in zip(self.row_rois,guard_rows):
                boxes=crop(roi)
                # Normalize this fresh read, never copy the previous label.
                boxes=normalize(boxes)
                found,problem=_find_ocr_rows(boxes,*[roi[i] for i in (0,2,1,3)],with_diagnostics=True)
                if problem or len(found)!=1:
                    return None
                row=found[0]
                if (row.clean_label!=guard_row.clean_label or row.stat_name!=guard_row.stat_name
                        or row.value!=guard_row.value
                        or (('%' in row.value_text or '％' in row.value_text) !=
                            ('%' in guard_row.value_text or '％' in guard_row.value_text))):
                    return None
                rows.append(row)
            if not valid_read_rows(rows):
                return None
            metadata = ()
            if self.cost_roi:
                x,y,right,bottom=self.cost_roi
                gx,gy,gr,gb=self.guard_roi
                if gx<=x and gy<=y and right<=gr and bottom<=gb:
                    boxes=[b for b in guard if x<=b.x and y<=b.y
                           and b.x+b.width<=right and b.y+b.height<=bottom]
                else:
                    boxes=crop(self.cost_roi)
                metadata=_cost_boxes(boxes)
                if not metadata:
                    return None
            return tuple(rows),list(metadata)+guard
        except Exception:
            return None
