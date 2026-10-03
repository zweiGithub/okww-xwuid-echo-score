"""A geometry-only cache: fixed OCR rectangles and fixed rendering anchors."""
from dataclasses import dataclass, replace
import math
import re
from types import SimpleNamespace

from echo_score import SUBSTAT_TIERS
from echo_text import simplify_echo_text
from echo_stat_overlay import (_find_ocr_rows, _STAT_TEXT, _VALUE_TEXT, RecognizedStatRow,
    _exact_stat_label, _normalize_stat_name, _numeric_value, _label_geometry)

_TUNING = ('声骸强化','强化并调谐','已完成全部调谐','Echo Enhancement')
_DETAIL = ('声骸技能','合鸣效果','Echo Skill','Sonata Effect')


def _page(boxes):
    text = ' '.join(simplify_echo_text(str(b.name)) for b in boxes)
    return 'tuning' if any(m in text for m in _TUNING) else 'detail' if any(m in text for m in _DETAIL) else None


def _cost_sources(boxes):
    sources=[]
    digits=[b for b in boxes if str(b.name).strip() in {'1','3','4'}]
    for box in boxes:
        text=str(box.name)
        for value in re.findall(r'COST\s*([134])(?=\s|$)',text,re.I):
            sources.append(((box,),int(value)))
        if re.fullmatch(r'\s*COST\s*[:：]?\s*',text,re.I):
            nearby=[b for b in digits if box.x-10<=b.x<=box.x+box.width+150
                    and abs((b.y+b.height/2)-(box.y+box.height/2))<35]
            if nearby:
                digit=min(nearby,key=lambda b:abs(b.x-box.x))
                sources.append(((box,digit),int(str(digit.name).strip())))
    return sources


def _cost_boxes(boxes):
    sources=_cost_sources(boxes)
    return sources[0][0] if len({value for _,value in sources})==1 else ()


def explicit_cost(boxes):
    values={value for _,value in _cost_sources(boxes)}
    return next(iter(values)) if len(values)==1 else None


def metadata_problem(boxes, expected_page=None):
    page=_page(boxes)
    if page is None or (expected_page is not None and page!=expected_page):
        return '页面信息未确认'
    if explicit_cost(boxes) is None:
        return 'COST 未确认'
    return ''


@dataclass(frozen=True)
class FreshRegionRead:
    rows: tuple
    boxes: tuple
    problem: str
    cost: int | None
    more_rows: bool = False


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
    cost_extra_rois: tuple
    cost_coverage_complete: bool

    @classmethod
    def acquire(cls, boxes, analysis, width, height):
        rows = analysis.read_rows
        page = _page(boxes) or ('tuning' if rows and rows[0].x<width*.5 else 'detail')
        if not valid_read_rows(rows) or len(analysis.rectangles)!=len(rows):
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
        cost_roi = ((max(0,math.floor(min(b.x for b in cost)-pad)),
                     max(0,math.floor(min(b.y for b in cost)-pad)),
                     min(width,math.ceil(max(b.x+b.width for b in cost)+pad)),
                     min(height,math.ceil(max(b.y+b.height for b in cost)+pad))) if cost else (0,0,width,math.ceil(height*.20)))
        # A metadata crop is deliberately small; never disguise a whole frame
        # as one COST ROI when an unrelated paragraph happens to mention it.
        if cost and (cost_roi[2]-cost_roi[0]>width*.35 or cost_roi[3]-cost_roi[1]>height*.12):
            cost_roi=(0,0,width,math.ceil(height*.20))
        extras=[]
        coverage_complete=True
        contains=lambda outer,inner: (outer[0]<=inner[0] and outer[1]<=inner[1]
                                      and inner[2]<=outer[2] and inner[3]<=outer[3])
        for source,value in _cost_sources(boxes):
            roi=(max(0,math.floor(min(b.x for b in source)-pad)),
                 max(0,math.floor(min(b.y for b in source)-pad)),
                 min(width,math.ceil(max(b.x+b.width for b in source)+pad)),
                 min(height,math.ceil(max(b.y+b.height for b in source)+pad)))
            if contains(guard,roi) or contains(cost_roi,roi) or roi in extras:
                continue
            if len(extras)<3 and roi[2]-roi[0]<=width*.35 and roi[3]-roi[1]<=height*.12:
                extras.append(roi)
            else:
                coverage_complete=False
        if any(not all(math.isfinite(v) for v in roi) or roi[2]<=roi[0] or roi[3]<=roi[1]
               for roi in [guard,*rois]):
            return None
        return cls(width,height,page,guard,count,cost_roi,tuple(rois),tuple(analysis.rectangles),
                   tuple(extras),coverage_complete)

    def read(self, ocr):
        """Only unprocessable row text fails geometry; metadata is separate."""
        def crop(roi):
            x,y,right,bottom=roi
            return ocr(x=x/self.width,y=y/self.height,to_x=right/self.width,to_y=bottom/self.height)
        rows=[]
        try:
            for roi,anchor in zip(self.row_rois,self.rectangles):
                boxes=crop(roi)
                labels=[b for b in boxes if _STAT_TEXT.search(simplify_echo_text(str(b.name)))]
                values=[b for b in boxes if _VALUE_TEXT.match(str(b.name))]
                if len(labels)!=1 or len(values)!=1:
                    return None
                prop,value=labels[0],values[0]
                name=simplify_echo_text(str(prop.name));value_text=str(value.name)
                normalized=SimpleNamespace(x=prop.x,y=prop.y,width=prop.width,height=prop.height,name=name)
                rows.append(RecognizedStatRow(anchor.x,anchor.y,anchor.width,anchor.height,
                    _normalize_stat_name(name,value_text),_numeric_value(value_text),value_text,
                    anchor.tier_x,anchor.tier_y,_exact_stat_label(name),str(prop.name),
                    (prop.x,prop.y,prop.width,prop.height),(value.x,value.y,value.width,value.height),
                    *_label_geometry(normalized)))
            if not valid_read_rows(rows):
                return None
        except Exception:
            return None
        # Failure/noise in these reads never replaces valid row geometry.
        try:
            guard=list(crop(self.guard_roi))
        except Exception:
            guard=[]
        metadata=[]
        try:
            x,y,right,bottom=self.cost_roi
            gx,gy,gr,gb=self.guard_roi
            if gx<=x and gy<=y and right<=gr and bottom<=gb:
                metadata=[b for b in guard if x<=b.x+b.width/2<=right and y<=b.y+b.height/2<=bottom]
            else:
                metadata=list(crop(self.cost_roi))
        except Exception:
            pass
        coverage_complete=self.cost_coverage_complete
        for roi in self.cost_extra_rois:
            try:
                extra=list(crop(roi))
                coverage_complete=coverage_complete and explicit_cost(extra) is not None
                metadata.extend(extra)
            except Exception:
                coverage_complete=False
        boxes=metadata+guard
        problem=metadata_problem(boxes,self.page)
        if not coverage_complete:
            problem=problem or 'COST 范围未确认'
        # Dedicated reads already verified both mains and five unique legal
        # substats. A broad re-read cannot reveal an additional supported slot.
        # Metadata above remains independent; partial panels still check below.
        if len(rows)==7:
            return FreshRegionRead(tuple(rows),tuple(boxes),problem,explicit_cost(boxes))
        more_rows=False
        try:
            normalize=lambda bs:[SimpleNamespace(x=b.x,y=b.y,width=b.width,height=b.height,
                name=simplify_echo_text(str(b.name)),raw_stat_name=str(b.name)) for b in bs]
            x,y,right,bottom=self.count_roi
            observed,pairing=_find_ocr_rows(normalize(guard),x,right,y,bottom,with_diagnostics=True)
            candidates=[replace(r,recognition_valid=bool(r.clean_label)) for r in observed]
            valid=not pairing and valid_read_rows(candidates)
            identity=lambda r:(r.clean_label,r.stat_name,r.value)
            prefix=valid and [identity(r) for r in candidates[:len(rows)]]==[identity(r) for r in rows]
            more_rows=bool(prefix and len(candidates)>len(rows)
                           and all(r.recognition_valid for r in observed[len(rows):]))
            if not valid or len(candidates)!=len(rows) or not prefix:
                problem=problem or '词条完整性未确认'
        except Exception:
            problem=problem or '词条完整性未确认'
        return FreshRegionRead(tuple(rows),tuple(boxes),problem,explicit_cost(boxes),more_rows)
