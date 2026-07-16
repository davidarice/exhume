"""Assemble extracted sequences into FCP7 xmeml (task a-emit-xmeml, scope §10 Phase 5).

OUTPUT side of the pipeline. The shape is modelled byte-for-structure on FCP7's OWN
single-sequence export (studied against the oracle `MONTAGE FINAL .xml`), because
FCP will only *build a timeline* from a document that gives it enough to instantiate
each clip:

  <xmeml version="5">
    <sequence> … timecode(01:00:00:00) … <media><video/><audio/></media> </sequence>
    <bin><name>Master Clips</name><children><clip/>…</bin>   # one master per source file
  </xmeml>

Every timeline <clipitem> carries a full <file> (pathurl + <media> samplecharacteristics)
and a <masterclipid> that resolves to a <clip> in the Master Clips bin.  Files are
deduped by id (full definition on first appearance in document order, `<file id=".."/>`
reference thereafter).  Clips that share a source share one masterclipid + one file id;
each clipitem gets a unique id.  This is what makes FCP create the clips (offline is fine
— it still builds the timeline as long as the <file>/<media> block is present).
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field as dfield
from urllib.parse import unquote
from xml.sax.saxutils import escape


def _attr(s):
    """Escape a value for a double-quoted XML attribute (escape() alone
    leaves `"` literal, which breaks ids built from recovered names)."""
    return escape(str(s), {'"': '&quot;'})


@dataclass
class File:
    id: str
    name: str
    pathurl: str | None = None
    duration: int | None = None
    timebase: int = 25
    ntsc: str = "FALSE"
    width: int | None = None
    height: int | None = None
    samplerate: int = 48000
    depth: int = 16
    channels: int = 2
    mediatype: str = "video"          # video | audio (primary — master-clip wrapper)
    has_video: bool | None = None     # override; else derived from mediatype
    has_audio: bool | None = None     # a synced .MOV needs BOTH blocks
    stillframe: bool = False          # still image (.jpg/.png/…) — FCP needs the flag
    source_tc: dict | None = None     # media start timecode {frame, displayformat} for relink
    audio_master_tracks: int | None = None  # indexed master audio tracks to expose:
    #  max(channels, max timeline trackindex) — mono dual-mono needs 2 (FCP oracle)
    meta: dict = dfield(default_factory=dict)  # Browser-column metadata


@dataclass
class Clip:
    name: str
    in_: int
    out: int
    start: int
    end: int
    file_id: str
    subclip: tuple | None = None      # (startoffset, endoffset) — the clip is a
    #  subclip of its source; in/out stay subclip-relative (FCP's own shape)
    masterclipid: str = ""
    itemid: str = ""                  # unique per clipitem (FCP element id)
    duration: int | None = None       # source file duration (not out-in)
    timebase: int = 25
    ntsc: str = "FALSE"
    mediatype: str = "video"
    enabled: bool = True
    trackindex: int = 1               # audio: source channel/track index
    stillframe: bool = False
    speed: dict | None = None         # constant-speed retime {speed,ratio,anchorOffset}
    alphatype: str = "none"           # <alphatype> token (none/straight/black/white)
    alphareverse: bool = False        # <alphareverse>TRUE</alphareverse> when set
    anamorphic: bool = False          # recovered per-clip <anamorphic>
    compositemode: str | None = None  # blend mode token; None = omitted
    meta: dict = dfield(default_factory=dict)  # Browser-column metadata
    filters: list = dfield(default_factory=list)   # emit.Filter, in emit order
    color: list = dfield(default_factory=list)     # Color Corrector value-dicts
    named_filters: list = dfield(default_factory=list)  # library effect-inner XML strings
    links: list = dfield(default_factory=list)     # sync-group members: dicts
    #  {linkclipref, mediatype, trackindex, clipindex}
    markers: list = dfield(default_factory=list)   # [{'name','in','out'}] source-time


@dataclass
class Keyframe:
    when: float                       # timeline sample position (identity from binary)
    value: object                     # scalar float, or (horiz, vert) tuple for points


@dataclass
class Parameter:
    name: str                         # display label, e.g. "Level" / "Pan" / "Center"
    parameterid: str                  # "level" / "pan" / "scale" / "center"
    valuemin: float | None = None     # None -> no <valuemin> (e.g. center point param)
    valuemax: float | None = None
    value: object = None              # static value (scalar float or (h,v) point)
    keyframes: list = dfield(default_factory=list)   # emit.Keyframe, time order
    point: bool = False               # value/keyframes are (horiz, vert) points
    idfirst: bool = False             # emit <parameterid> before <name> (motion/opacity)


@dataclass
class Filter:
    effectid: str                     # "audiolevels" / "audiopan"
    name: str                         # "Audio Levels" / "Audio Pan"
    category: str                     # <effectcategory>
    mediatype: str                    # audio | video
    parameters: list = dfield(default_factory=list)  # emit.Parameter
    effecttype: str = ""              # <effecttype>; defaults to effectid


@dataclass
class Transition:
    start: int
    end: int
    alignment: str = "center"         # center | start-black | end-black
    mediatype: str = "video"
    effectid: str = "Cross Dissolve"
    name: str = "Cross Dissolve"
    effectcategory: str = "Dissolve"
    params: str = ""                  # pre-rendered <parameter> block(s), if any
    timebase: int = 25
    ntsc: str = "FALSE"


@dataclass
class Generator:
    name: str
    in_: int
    out: int
    start: int
    end: int
    duration: int = 0
    itemid: str = ""
    text: str = ""                    # recovered title string (empty = generic shell)
    mediatype: str = "video"
    timebase: int = 25
    ntsc: str = "FALSE"


@dataclass
class Track:
    mediatype: str                    # video | audio
    clips: list = dfield(default_factory=list)   # Clip | Transition | Generator


@dataclass
class Sequence:
    name: str
    duration: int
    uuid: str = "00000000-0000-0000-0000-000000000000"
    timebase: int = 25
    ntsc: str = "FALSE"
    width: int = 1920
    height: int = 1080
    video_tracks: list[Track] = dfield(default_factory=list)
    audio_tracks: list[Track] = dfield(default_factory=list)
    files: dict[str, File] = dfield(default_factory=dict)
    markers: list = dfield(default_factory=list)   # sequence markers [{'name','in','out'}]
    start_tc: object = None           # sequence start tc: None (1h default), bare
    #  NDF frame int, or {'frame', 'displayformat'} (keyg_grouper.sequence_timecode)


def _rate(tb: int, ntsc: str) -> str:
    return f"<rate><ntsc>{ntsc}</ntsc><timebase>{tb}</timebase></rate>"


def _g(x: float) -> str:
    """FCP's own numeric formatting for filter values/whens: %g at 6 significant
    figures (validated byte-exact against the oracle's <when>/<value>/<valuemax>)."""
    return "%g" % x


def _pval(v, point: bool) -> str:
    """<value> body: scalar %g, or a <horiz>/<vert> point for center/anchor params."""
    if point:
        h, vv = v if v is not None else (0, 0)
        return f"<value><horiz>{_g(h)}</horiz><vert>{_g(vv)}</vert></value>"
    return f"<value>{_g(v if v is not None else 0)}</value>"


def _parameter(p: "Parameter") -> str:
    nm, pid = f"<name>{escape(p.name)}</name>", f"<parameterid>{escape(p.parameterid)}</parameterid>"
    body = [pid, nm] if p.idfirst else [nm, pid]
    if p.valuemin is not None:
        body.append(f"<valuemin>{_g(p.valuemin)}</valuemin>")
    if p.valuemax is not None:
        body.append(f"<valuemax>{_g(p.valuemax)}</valuemax>")
    if p.keyframes:
        for k in p.keyframes:
            body.append(f"<keyframe><when>{_g(k.when)}</when>{_pval(k.value, p.point)}</keyframe>")
        body.append("<interpolation><name>FCPCurve</name></interpolation>")
        if not p.point:               # scalar params carry a trailing static value; points don't
            tv = p.value if p.value is not None else p.keyframes[-1].value
            body.append(_pval(tv, False))
    else:
        body.append(_pval(p.value, p.point))
    return "<parameter>" + "".join(body) + "</parameter>"


def _timeremap_filter(c: "Clip") -> str:
    """The Time Remap <filter> for a constant-speed clip (effectid=timeremap), placed
    after <sourcetrack> as FCP writes it.  The graphdict is the source-time mapping at
    x in {0, in, out, duration}; DaVinci/Premiere read this to apply the retime (they
    ignore the plain <speed> value).

    Byte-exact against FCP's own graphdict (validated on all 556 EPK/managed retimes):
    the slope is s = (inputUsed-1)/(outputDuration-1) — the segment maps od output
    frames onto iu source frames inclusive of both endpoints.
    Forward: y(x) = anchorOffset + s*x; start(0)=ao, end(duration)=ao+iu exactly; the
    out keyframe is line(out), EXCEPT out==od-1 which is a REAL keyframe (no
    speedvirtualkf) pinned to media_duration-1.
    Reverse: y(x) = (ao+iu) - s*x with start(0)=ao+iu+1 and end(duration)=ao+1 pinned;
    the trailing <value> is line(in)-1.
    valuemax = media_duration-1 (the source file's F64 duration)."""
    sp = c.speed
    ao = sp["anchorOffset"]
    dur = sp.get("duration") or c.duration or c.out
    reverse = sp.get("reverse")
    iu = sp.get("input_used") or (sp["ratio"] * dur)
    od = sp.get("output_duration") or dur
    s = sp.get("slope")
    if s is None:
        s = (iu - 1.0) / (od - 1.0) if od > 1 else sp["ratio"]
    md = sp.get("media_duration")
    # A non-finite retime value would emit '<value>nan</value>' or crash the whole
    # document at int(v_start) below; drop the retime instead and keep the cut.
    if not all(math.isfinite(x) for x in (ao, iu, od, s)):
        return ""
    if reverse:
        y = lambda x: (ao + iu) - s * x
    else:
        y = lambda x: ao + s * x

    def _kf(when, kind, virtual, value, anchor=False):
        # FCP omits the anchorOffset element when it is zero (Aaron oracle;
        # every EPK/managed oracle anchorOffset is nonzero, 47/47)
        extra = f"<anchorOffset>{_g(ao)}</anchorOffset>" if anchor and ao else ""
        v = "<speedvirtualkf>TRUE</speedvirtualkf>" if virtual else ""
        return (f"<keyframe><when>{when}</when><value>{_g(value)}</value>"
                f"<{kind}>TRUE</{kind}>{v}{extra}</keyframe>")

    # FCP's graphdict is the curve [start(0), in, out, end(duration)] but with
    # coincident points merged: when in==0 the start & in keyframes are one
    # (speedkfin, no anchorOffset); when out==duration the out & end are one.
    # The start/end values are PINNED (ao / ao+iu forward, ao+iu+1 / ao+1
    # reverse), not evaluated on the line — FCP's spline overshoots there.
    v_start = (ao + iu + 1) if reverse else ao
    v_end = (ao + 1) if reverse else (ao + iu)
    kfs = []
    if c.in_ == 0:
        kfs.append(_kf(0, "speedkfin", False, v_start))
    else:
        kfs.append(_kf(0, "speedkfstart", True, v_start, anchor=True))
        kfs.append(_kf(c.in_, "speedkfin", True, y(c.in_)))
    if c.out == dur:
        kfs.append(_kf(c.out, "speedkfout", True, v_end))
    else:
        if not reverse and md is not None and c.out == od - 1:
            kfs.append(_kf(c.out, "speedkfout", False, md - 1))
        else:
            kfs.append(_kf(c.out, "speedkfout", True, y(c.out)))
        kfs.append(_kf(dur, "speedkfend", True, v_end))
    vmax = (md - 1) if md is not None else max(int(v_start), int(v_end)) - 1
    trail = (y(c.in_) - 1) if reverse else y(c.in_)
    graph = (f"<parameter><parameterid>graphdict</parameterid><name>graphdict</name>"
             f"<valuemin>0</valuemin><valuemax>{_g(vmax)}</valuemax>"
             + "".join(kfs)
             + "<interpolation><name>FCPCurve</name></interpolation>"
             + f"<value>{_g(trail)}</value></parameter>")
    mapped = ("<parameter><parameterid>mappedduration</parameterid><name>mappedduration</name>"
              "<value><timecode><rate><timebase>0</timebase></rate><string>0</string>"
              "<frame>0</frame><displayformat>NDF</displayformat></timecode></value></parameter>")
    return ("<filter><effect><name>Time Remap</name><effectid>timeremap</effectid>"
            "<effectcategory>motion</effectcategory><effecttype>motion</effecttype>"
            f"<mediatype>{c.mediatype}</mediatype>"
            "<parameter><parameterid>variablespeed</parameterid><name>variablespeed</name>"
            "<valuemin>0</valuemin><valuemax>1</valuemax><value>0</value></parameter>"
            f"{mapped}"
            "<parameter><parameterid>speed</parameterid><name>speed</name>"
            f"<valuemin>-10000</valuemin><valuemax>10000</valuemax><value>{sp['speed']}</value></parameter>"
            "<parameter><parameterid>reverse</parameterid><name>reverse</name>"
            f"<value>{'TRUE' if reverse else 'FALSE'}</value></parameter>"
            "<parameter><parameterid>frameblending</parameterid><name>frameblending</name><value>TRUE</value></parameter>"
            f"{graph}</effect></filter>")


def _filter(f: "Filter") -> str:
    et = f.effecttype or f.effectid
    eff = (f"<effect><name>{escape(f.name)}</name>"
           f"<effectid>{escape(f.effectid)}</effectid>"
           f"<effectcategory>{escape(f.category)}</effectcategory>"
           f"<effecttype>{escape(et)}</effecttype>"
           f"<mediatype>{escape(f.mediatype)}</mediatype>"
           + "".join(_parameter(p) for p in f.parameters) + "</effect>")
    return f"<filter>{eff}</filter>"


# Color Corrector (3-way grade) parameter template — fixed structure, variable values.
# (id, display name, min, max, kind); kind: num | bool | label | valuelist(dispmode).
_CC_PARAMS = [
    ("dispmode", "Mode d'affichage", "1", "3", "valuelist"),
    ("label1", "Contrôles de niveau", None, None, "label"),
    ("highlights", "Clairs", "64", "509", "num"),
    ("mids", "Moyens", "0", "200", "num"),
    ("blacklevel", "Noirs", "-196", "254", "num"),
    ("label2", "Balance des couleurs", None, None, "label"),
    ("hue", "Angle", "-180", "180", "num"),
    ("mag", "Ampleur", "0", "200", "num"),
    ("label4", "Contrôles des couleurs", None, None, "label"),
    ("chroma", "Saturation", "0", "200", "num"),
    ("phase", "Décal. de phase", "-180", "180", "num"),
    ("label5", "Contrôles d'effet de limite", None, None, "label"),
    ("dochroma", "Limiter la chrominance", None, None, "bool"),
    ("centerang", "Centre chromatique", "-760", "760", "num"),
    ("chromawidth", "Largeur chromatique", "0", "360", "num"),
    ("chromasoft", "Atténuation chromatique", "0", "180", "num"),
    ("dosat", "Limiter la saturation", None, None, "bool"),
    ("satmin", "Sat. minimale", "0", "120", "num"),
    ("satwidth", "Largeur de sat.", "0", "120", "num"),
    ("satsoft", "Atténuation de sat.", "0", "120", "num"),
    ("doluma", "Limiter la luminance", None, None, "bool"),
    ("lumamin", "Luminance minimale", "0", "125", "num"),
    ("lumawidth", "Largeur de luminance", "0", "125", "num"),
    ("lumasoft", "Atténuation de luminance", "0", "125", "num"),
    ("label6", "Contrôle du bord", None, None, "label"),
    ("edgethin", "Fin/Élargi", "-100", "100", "num"),
    ("edgefeather", "Atténué", "0", "100", "num"),
    ("label7", "Contrôle de masque", None, None, "label"),
    ("invertsel", "Inverser", None, None, "bool"),
    ("debugshow", "Débogage affiché", None, None, "bool"),
]
_CC_DEFAULT = {p[0]: (255 if p[0] == "highlights" else 0) for p in _CC_PARAMS}
_CC_DISPMODE_VL = ("<valuelist><valueentry><name>Final</name><value>1</value></valueentry>"
                   "<valueentry><name>Cache</name><value>2</value></valueentry>"
                   "<valueentry><name>Source</name><value>3</value></valueentry></valuelist>")


def _color_corrector(vals: dict) -> str:
    """Render one Color Corrector <filter> from recovered grade values (missing values
    fall back to the parameter default); a fixed 30-parameter template."""
    parts = []
    for pid, name, mn, mx, kind in _CC_PARAMS:
        body = [f"<parameterid>{pid}</parameterid>", f"<name>{escape(name)}</name>"]
        if kind == "label":
            body.append("<value/>")
        elif kind == "bool":
            body.append(f"<value>{'TRUE' if vals.get(pid) else 'FALSE'}</value>")
        else:
            body.append(f"<valuemin>{mn}</valuemin><valuemax>{mx}</valuemax>")
            if kind == "valuelist":
                body.append(_CC_DISPMODE_VL)
            v = vals.get(pid)
            if v is None or (isinstance(v, float) and not math.isfinite(v)):
                v = 1 if pid == "dispmode" else _CC_DEFAULT.get(pid, 0)
            body.append(f"<value>{int(round(v))}</value>")
        parts.append("<parameter>" + "".join(body) + "</parameter>")
    eff = ("<effect><name>Color Corrector</name><effectid>Color Corrector</effectid>"
           "<effectcategory>Color Corrector</effectcategory><effecttype>filter</effecttype>"
           "<mediatype>video</mediatype>" + "".join(parts) + "</effect>")
    return f"<filter><enabled>TRUE</enabled><start>-1</start><end>-1</end>{eff}</filter>"


def _logging_blocks(meta: dict | None = None) -> str:
    """The Browser-column metadata blocks (Description/Scene/Shot-Take/Log Note/Good in
    logginginfo; Label colour + Label 2 in labels; Master Comment 1-4 + Comment A/B in
    comments). Recovered values where present, else the empty field FCP still writes."""
    m = meta or {}

    def fld(tag, key):      # always written (empty tag when absent) — matches FCP
        v = m.get(key)
        return f"<{tag}>{escape(str(v))}</{tag}>" if v else f"<{tag}/>"

    def opt(tag, key):      # FCP omits these entirely when empty
        v = m.get(key)
        return f"<{tag}>{escape(str(v))}</{tag}>" if v else ""

    return (f"<logginginfo>{opt('description','description')}{fld('scene','scene')}"
            f"{fld('shottake','shottake')}{fld('lognote','lognote')}"
            f"<good>{'TRUE' if m.get('good') else 'FALSE'}</good></logginginfo>"
            f"<labels>{opt('label','label_color')}{fld('label2','label2')}</labels>"
            f"<comments>{fld('mastercomment1','mastercomment1')}{fld('mastercomment2','mastercomment2')}"
            f"{fld('mastercomment3','mastercomment3')}{fld('mastercomment4','mastercomment4')}"
            f"{opt('clipcommenta','clipcommenta')}{opt('clipcommentb','clipcommentb')}</comments>")


def _uuid_from(s: str) -> str:
    """Deterministic UUID from a string (stable across runs; no randomness)."""
    h = hashlib.md5(s.encode("utf-8")).hexdigest().upper()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _file_media(f: File) -> str:
    hv = f.has_video if f.has_video is not None else (f.mediatype == "video")
    ha = f.has_audio if f.has_audio is not None else (f.mediatype == "audio")
    blocks = []
    if hv:
        chars = (f"<samplecharacteristics><width>{f.width or 1920}</width>"
                 f"<height>{f.height or 1080}</height></samplecharacteristics>")
        still = "<stillframe>TRUE</stillframe>" if f.stillframe else ""
        blocks.append(f"<video><duration>{f.duration or 0}</duration>{still}{chars}</video>")
    if ha:
        chars = (f"<samplecharacteristics><samplerate>{f.samplerate}</samplerate>"
                 f"<depth>{f.depth}</depth></samplecharacteristics>"
                 f"<channelcount>{f.channels}</channelcount>")
        blocks.append(f"<audio>{chars}</audio>")
    return "<media>" + "".join(blocks) + "</media>"


def _tc_string(frame: int, tb: int, df: bool = False) -> str:
    """Frame count -> HH:MM:SS:FF at `tb` fps.  90000 @ 25 -> 01:00:00:00.

    df=True applies SMPTE drop-frame numbering (NTSC nominal timebases only,
    tb % 30 == 0; otherwise silently NDF — a DF string at a non-NTSC rate is
    meaningless): frame NUMBERS 0..d-1 are skipped at every minute boundary
    except minutes divisible by 10 (d = 2 per 30fps), and FCP writes the
    separator before FF as a SEMICOLON.  Verified against FCP's own export
    (107892 @30DF -> '01:00:00;00') and an exhaustive 24h round-trip."""
    fps = tb or 25
    if df and fps % 30 == 0:
        d = 2 * (fps // 30)                 # frames dropped per minute
        fpm = fps * 60 - d                  # frames per drop minute
        fp10 = fps * 600 - 9 * d            # frames per 10-minute block
        tens, rem = divmod(frame, fp10)
        extra = 0 if rem < fps * 60 else d * (1 + (rem - fps * 60) // fpm)
        n = frame + 9 * d * tens + extra    # nominal (digit) frame count
        ff = n % fps
        secs = n // fps
        return f"{secs // 3600 % 24:02d}:{secs // 60 % 60:02d}:{secs % 60:02d};{ff:02d}"
    ff = frame % fps
    secs = frame // fps
    return f"{secs // 3600 % 24:02d}:{secs // 60 % 60:02d}:{secs % 60:02d}:{ff:02d}"


def _media_timebase(f: File) -> int:
    """The media's native frame rate — from its embedded timecode track when known
    (may differ from the sequence rate), else the file's declared timebase."""
    tc = f.source_tc or {}
    return tc.get("timebase") or f.timebase


def _file_timecode(f: File) -> str:
    """The media's embedded source start timecode.  Resolve matches this against the
    real media file on relink; omitting it makes an offset/retimed clip's source
    extents fall outside the media -> 'timecode extents do not match any clip in the
    Media Pool'.  Recovered from the binary's tcData/segStart (see keyg_grouper).
    Formatted at the MEDIA rate (not the sequence rate) so the string is correct for
    a media whose fps differs from the timeline's."""
    tc = f.source_tc
    if not tc or tc.get("frame") is None:
        return ""
    frame = int(tc["frame"])
    tb = _media_timebase(f)
    df = tc.get("displayformat") == "DF" and tb % 30 == 0
    disp = "DF" if df else "NDF"
    # rate block: timebase first, then ntsc when the media is NTSC — FCP's
    # own file-tc shape (Aaron oracle: <timebase>30</timebase><ntsc>TRUE</ntsc>;
    # the EPK oracle omits ntsc on its film-24 sources, so Intel output is
    # unchanged — their recovered ntsc is FALSE)
    ntsc_el = "<ntsc>TRUE</ntsc>" if tc.get("ntsc") == "TRUE" else ""
    # <reel> is the last child of <timecode> (after <source>); it carries the
    # camera/tape reel name so an NLE can relink by reel as well as by pathurl.
    reel = tc.get("reel")
    reel_el = f"<reel><name>{escape(reel)}</name></reel>" if reel else ""
    return (f"<timecode><rate><timebase>{tb}</timebase>{ntsc_el}</rate>"
            f"<string>{_tc_string(frame, tb, df)}</string><frame>{frame}</frame>"
            f"<displayformat>{disp}</displayformat><source>source</source>"
            f"{reel_el}</timecode>")


def _file_name(f: File) -> str:
    """FCP's <file><name> is the media file's basename (e.g. 'bars.mov'), which
    Resolve matches on relink — not the clip/master name (which may drop the
    extension).  Derive it from the pathurl when present."""
    if f.pathurl:
        base = unquote(f.pathurl.rstrip("/").rsplit("/", 1)[-1])
        if base:
            return base
    return f.name


def _file(f: File, emitted: set[str]) -> str:
    """Full <file> definition on first use of the id; a bare reference thereafter."""
    if f.id in emitted:
        return f'<file id="{_attr(f.id)}"/>'
    emitted.add(f.id)
    inner = [f"<name>{escape(_file_name(f))}</name>"]
    if f.pathurl:
        inner.append(f"<pathurl>{escape(f.pathurl)}</pathurl>")
    # the file's EDIT rate (matches the sequence/media fps), NOT the source-TC rate:
    # FCP writes e.g. <timebase>24</timebase><ntsc>TRUE</ntsc>. _media_timebase prefers
    # the camera TC rate (e.g. 60), which is wrong for the file's own rate element.
    f_ntsc = "<ntsc>TRUE</ntsc>" if f.ntsc == "TRUE" else ""
    inner.append(f"<rate><timebase>{f.timebase}</timebase>{f_ntsc}</rate>")
    if f.duration is not None:
        inner.append(f"<duration>{f.duration}</duration>")
    inner.append(_file_timecode(f))
    if f.stillframe:                 # stills carry file-level dims (oracle: 20/20 stills)
        inner.append(f"<width>{f.width or 1920}</width><height>{f.height or 1080}</height>")
    inner.append(_file_media(f))
    return f'<file id="{_attr(f.id)}">' + "".join(inner) + "</file>"


def _marker(m) -> str:
    """One <marker> block, FCP's shape: empty comment, default red color, source-
    time in/out (out=-1 for a point marker)."""
    return (f"<marker><name>{escape(m.get('name') or '')}</name><comment/>"
            "<color><alpha>0</alpha><red>255</red><green>0</green><blue>0</blue></color>"
            f"<in>{m['in']}</in><out>{m.get('out', -1)}</out></marker>")


def _clipitem(c: Clip, files: dict[str, File], emitted: set[str]) -> str:
    f = files.get(c.file_id)
    dur = c.duration if c.duration is not None else (c.out - c.in_)
    parts = [
        f"<name>{escape(c.name)}</name>",
        f"<duration>{dur}</duration>",
        _rate(c.timebase, c.ntsc),
        f"<in>{c.in_}</in>", f"<out>{c.out}</out>",
        f"<start>{c.start}</start>", f"<end>{c.end}</end>",
    ]
    if c.subclip:
        # oracle order: right after <end>; in/out stay subclip-relative and
        # the offsets map them onto the source media (99/99 in FCP's export)
        so, eo = c.subclip
        parts.append(f"<subclipinfo><startoffset>{so}</startoffset>"
                     f"<endoffset>{eo}</endoffset></subclipinfo>")
    enabled = f"<enabled>{'TRUE' if c.enabled else 'FALSE'}</enabled>"
    if c.mediatype == "video":
        # FCP's clipitem child order: pixelaspectratio, [stillframe], enabled,
        # anamorphic, alphatype (a strict importer like Premiere rejects the
        # inverted enabled/pixelaspectratio order; Resolve tolerates it).
        parts.append("<pixelaspectratio>Square</pixelaspectratio>")
        if c.stillframe:
            parts.append("<stillframe>TRUE</stillframe>")
        parts.append(enabled)
        parts += [f"<anamorphic>{'TRUE' if c.anamorphic else 'FALSE'}</anamorphic>",
                  f"<alphatype>{c.alphatype}</alphatype>"]
    else:
        parts.append(enabled)
        if c.alphareverse:
            parts.append("<alphareverse>TRUE</alphareverse>")
        if c.compositemode:                       # present only when FCP wrote keytype
            parts.append(f"<compositemode>{c.compositemode}</compositemode>")
    if c.masterclipid:
        parts.append(f"<masterclipid>{escape(c.masterclipid)}</masterclipid>")
    parts.append(_logging_blocks(c.meta))
    if f is not None:
        parts.append(_file(f, emitted))
    for m in c.markers:                # <marker> blocks: after <file> (oracle order)
        parts.append(_marker(m))
    # <filter> blocks sit between <file> and <sourcetrack> (oracle order). Only
    # filters carrying real values are attached upstream (default/noise skipped),
    # so missing filters are safe for import and present ones never default-noise.
    for filt in c.filters:
        parts.append(_filter(filt))
    for cc in c.color:                # Color Corrector grades (recovered per clip)
        parts.append(_color_corrector(cc))
    for inner in c.named_filters:     # library-recovered filters (blurs, stylize, …)
        parts.append("<filter><enabled>TRUE</enabled><start>-1</start><end>-1</end>"
                     f"<effect>{inner}</effect></filter>")
    st = f"<mediatype>{c.mediatype}</mediatype>"
    if c.mediatype == "audio":
        st += f"<trackindex>{c.trackindex}</trackindex>"
    parts.append(f"<sourcetrack>{st}</sourcetrack>")
    for lk in c.links:                         # sync-group <link> blocks (after sourcetrack)
        gi = ("<groupindex>1</groupindex>" if lk.get("groupindex") else "")
        parts.append(
            f"<link><linkclipref>{_attr(lk['linkclipref'])}</linkclipref>"
            f"<mediatype>{lk['mediatype']}</mediatype>"
            f"<trackindex>{lk['trackindex']}</trackindex>"
            f"<clipindex>{lk['clipindex']}</clipindex>{gi}</link>")
    if c.speed:                                # Time Remap goes after <sourcetrack>,
        parts.append(_timeremap_filter(c))     # on the audio clips too (retimes audio)
    return f'<clipitem id="{_attr(c.itemid or c.name)}">' + "".join(parts) + "</clipitem>"


def _transitionitem(t: Transition) -> str:
    if t.mediatype == "audio":         # stock cross-fade: 0 dB or +3 dB (no wipe fields)
        nm = "Cross Fade (+3dB)" if str(t.effectid).endswith("3dB") else "Cross Fade ( 0dB)"
        eff = (f"<effect><name>{escape(nm)}</name><effectid>{escape(t.effectid)}</effectid>"
               "<effecttype>transition</effecttype><mediatype>audio</mediatype></effect>")
    else:
        from .fcp_transitions import TRANSITION_EFFECTS
        inner = TRANSITION_EFFECTS.get(t.effectid) or TRANSITION_EFFECTS["Cross Dissolve"]
        eff = f"<effect>{inner}</effect>"
    return (f"<transitionitem>{_rate(t.timebase, t.ntsc)}"
            f"<start>{t.start}</start><end>{t.end}</end>"
            f"<alignment>{escape(t.alignment)}</alignment>{eff}</transitionitem>")


def _generatoritem(g: Generator) -> str:
    param = ""
    if g.text:                        # recovered title -> the Text generator's str param
        param = (f"<parameter><parameterid>str</parameterid><name>Text</name>"
                 f"<value>{escape(g.text)}</value></parameter>")
    disp = g.text or g.name or "Text"
    return (f'<generatoritem id="{_attr(g.itemid or disp)}">'
            f"<name>{escape(disp)}</name><duration>{g.duration}</duration>"
            f"{_rate(g.timebase, g.ntsc)}<in>{g.in_}</in><out>{g.out}</out>"
            f"<start>{g.start}</start><end>{g.end}</end><enabled>TRUE</enabled>"
            "<anamorphic>FALSE</anamorphic><alphatype>black</alphatype>"
            "<effect><name>Text</name><effectid>Text</effectid>"
            "<effectcategory>Text</effectcategory><effecttype>generator</effecttype>"
            f"<mediatype>video</mediatype>{param}</effect></generatoritem>")


def _render_item(it, files, emitted) -> str:
    if isinstance(it, Transition):
        return _transitionitem(it)
    if isinstance(it, Generator):
        return _generatoritem(it)
    return _clipitem(it, files, emitted)


def _track(t: Track, files, emitted, *, audio_ch: int | None = None) -> str:
    body = "".join(_render_item(c, files, emitted) for c in t.clips)
    body += "<enabled>TRUE</enabled><locked>FALSE</locked>"
    if audio_ch is not None:
        body += f"<outputchannelindex>{audio_ch}</outputchannelindex>"
    return f"<track>{body}</track>"


def _master_clip(f: File, emitted: set[str]) -> str:
    """A Master Clips bin entry: <clip> wrapping media/track/clipitem for the file.

    A synced source (video + audio) yields ONE master with both a <video> and an
    <audio> media block, mirroring FCP.  Timeline audio clips reference this same
    master, so it must carry audio media or they fail to relink in Resolve.

    The audio media exposes ONE <track> per source channel, each keyed by
    <sourcetrack><trackindex>k</trackindex>: Resolve binds a timeline audio clip to
    a master channel-track by that index to derive its source range.  A single
    unindexed audio track leaves stereo channel 2 (and ambiguous channel 1)
    unbound, so the source timecode never resolves and imports as the 0xFFFF
    sentinel (-52:55:45:65535).  The media-level <in>-1</in><out>-1</out> marks the
    audio media full-extent, as FCP writes it.
    """
    rate = _rate(f.timebase, f.ntsc)
    mid = f"{f.id}1"
    dur = f.duration or 0
    hv = f.has_video if f.has_video is not None else (f.mediatype == "video")
    ha = f.has_audio if f.has_audio is not None else (f.mediatype == "audio")
    if not (hv or ha):                       # degenerate: fall back to primary type
        hv, ha = (f.mediatype == "video"), (f.mediatype == "audio")

    def inner_ci(mt: str, ti: int | None = None) -> str:
        still = "<stillframe>TRUE</stillframe>" if (mt == "video" and f.stillframe) else ""
        suffix = f"_{ti}" if ti is not None else ""
        st = f"<mediatype>{mt}</mediatype>"
        if mt == "audio" and ti is not None:
            st += f"<trackindex>{ti}</trackindex>"
        return (f'<clipitem id="{_attr(f.id)}__master_{mt}{suffix}"><name>{escape(f.name)}</name>'
                f"<duration>{dur}</duration>{rate}<in>0</in><out>{dur}</out>"
                f"<start>0</start><end>{dur}</end>{still}"
                f"<masterclipid>{escape(mid)}</masterclipid>"
                f"{_file(f, emitted)}"
                f"<sourcetrack>{st}</sourcetrack></clipitem>")

    blocks = ""
    if hv:
        blocks += f"<video><track>{inner_ci('video')}</track></video>"
    if ha:
        # one master audio track per INSTANTIATED timeline channel: FCP lays a
        # mono capture as a dual-mono pair (timeline ti=1/2 with channelcount
        # 1), so the exposure is max(channels, max timeline trackindex) — a
        # ti with no indexed track here is unbindable in Resolve (0xFFFF
        # uninitialised source-range sentinel)
        nch = max(f.channels or 1, f.audio_master_tracks or 0)
        atracks = "".join(f"<track>{inner_ci('audio', k)}</track>"
                          for k in range(1, nch + 1))
        blocks += f"<audio><in>-1</in><out>-1</out>{atracks}</audio>"
    media = f"<media>{blocks}</media>"
    return (f'<clip id="{_attr(mid)}"><uuid>{_uuid_from(mid)}</uuid>'
            f"<updatebehavior>add</updatebehavior><name>{escape(f.name)}</name>"
            f"<duration>{dur}</duration>{rate}<in>-1</in><out>-1</out>"
            f"<masterclipid>{escape(mid)}</masterclipid><ismasterclip>TRUE</ismasterclip>"
            f"{_logging_blocks(f.meta)}{media}</clip>")


def _timecode(tb: int, ntsc: str, start_tc=None) -> str:
    """Sequence <timecode>: the recovered start frame when known, else FCP's
    1-hour default.  start_tc is None (default), a bare frame int (legacy
    NDF), or the recovered dict {'frame': int, 'displayformat': 'DF'|'NDF'}
    (frame already in XML semantics, i.e. the real DF frame index)."""
    if isinstance(start_tc, dict):
        frame = start_tc.get("frame")
        df = start_tc.get("displayformat") == "DF" and tb % 30 == 0
    else:
        frame, df = start_tc, False
    if frame is None:
        frame = tb * 3600        # 01:00:00:00 start (FCP default)
        df = False
    disp = "DF" if df else "NDF"
    return (f"<timecode>{_rate(tb, ntsc)}<string>{_tc_string(frame, tb, df)}</string>"
            f"<frame>{frame}</frame><source>source</source>"
            f"<displayformat>{disp}</displayformat></timecode>")


def _video_format(seq: Sequence) -> str:
    return (f"<format><samplecharacteristics><width>{seq.width}</width>"
            f"<height>{seq.height}</height><anamorphic>FALSE</anamorphic>"
            f"<pixelaspectratio>Square</pixelaspectratio>"
            f"<fielddominance>none</fielddominance>{_rate(seq.timebase, seq.ntsc)}"
            f"<colordepth>24</colordepth></samplecharacteristics></format>")


def _audio_format() -> str:
    return ("<format><samplecharacteristics><depth>16</depth>"
            "<samplerate>48000</samplerate></samplecharacteristics></format>"
            "<outputs><group><index>1</index><numchannels>2</numchannels>"
            "<downmix>0</downmix><channel><index>1</index></channel>"
            "<channel><index>2</index></channel></group></outputs>")


def build_sequence(seq: Sequence, emitted: set[str]) -> str:
    rate = _rate(seq.timebase, seq.ntsc)
    video = ("<video>" + _video_format(seq)
             + "".join(_track(t, seq.files, emitted) for t in seq.video_tracks)
             + "</video>")
    audio = ""
    if seq.audio_tracks:
        atr = "".join(_track(t, seq.files, emitted, audio_ch=(i % 2) + 1)
                      for i, t in enumerate(seq.audio_tracks))
        audio = ("<audio>" + _audio_format()
                 + f"<in>0</in><out>{seq.duration + 1}</out>" + atr + "</audio>")
    uuid = seq.uuid
    if uuid == "00000000-0000-0000-0000-000000000000":
        uuid = _uuid_from(seq.name)     # never ship the nil UUID (FCP writes a real one)
    return (f'<sequence id="{_attr(seq.name)}"><uuid>{uuid}</uuid>'
            f"<updatebehavior>add</updatebehavior><name>{escape(seq.name)}</name>"
            f"<duration>{seq.duration}</duration>{rate}{_timecode(seq.timebase, seq.ntsc, seq.start_tc)}"
            f"<in>0</in><out>{seq.duration + 1}</out>"
            f"<media>{video}{audio}</media>"
            + "".join(_marker(m) for m in seq.markers)
            + "</sequence>")


def _master_bin(seq: Sequence, emitted: set[str]) -> str:
    clips = "".join(_master_clip(f, emitted) for f in seq.files.values())
    return (f"<bin><name>Master Clips</name><children>{clips}</children></bin>")


def build_document(seq: Sequence, *, master_bin: bool = True) -> bytes:
    """Single-sequence importable xmeml: <sequence> [+ Master Clips bin].

    master_bin=True (default) appends FCP's Master Clips <bin>, which groups synced
    A/V for Resolve's media-pool relink. master_bin=False drops the bin AND the now-
    dangling <masterclipid> refs, leaving a self-contained sequence whose clips relink
    via their own inline <file> (pathurl + source timecode) -- the leaner shape some
    importers (Premiere) accept where the full bin does not."""
    emitted: set[str] = set()
    if not master_bin:
        for tr in seq.video_tracks + seq.audio_tracks:
            for c in tr.clips:
                if isinstance(c, Clip):
                    c.masterclipid = None
    body = build_sequence(seq, emitted)
    if master_bin:
        body += _master_bin(seq, emitted)
    doc = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
           f'<xmeml version="5">{body}</xmeml>')
    return doc.encode("utf-8")


def build_project(sequences: list[Sequence], name: str = "project") -> bytes:
    """Multi-sequence project: <project><children> of <sequence>s + one shared
    Master Clips bin.  Single-sequence exports should prefer build_document()."""
    emitted: set[str] = set()
    seqs = "".join(build_sequence(s, emitted) for s in sequences)
    files: dict[str, File] = {}
    for s in sequences:
        files.update(s.files)
    masters = "".join(_master_clip(f, emitted) for f in files.values())
    bin_ = f"<bin><name>Master Clips</name><children>{masters}</children></bin>"
    doc = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n'
           f'<xmeml version="5"><project><name>{escape(name)}</name>'
           f"<children>{seqs}{bin_}</children></project></xmeml>")
    return doc.encode("utf-8")
