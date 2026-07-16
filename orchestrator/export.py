"""End-to-end .fcp -> xmeml export pipeline (scope §10 Phase 5).

Wires the pieces:  group clips into sequences + resolve names/timing/files
(keyg_grouper: containment-tree walk over keyg_walker2)  ->  render
(emit.build_project).

export_single_sequence(): single-track files (the synthetic corpus) via the
positional timing decoder (fcp_parser.timeline_clips) — exact on that corpus.
export_project(): full multi-sequence export via keyg_grouper.grouper
(validated: mc_* match export_single_sequence names+timing exactly; palastin
renders its 22 sequences with exact per-sequence clipitem counts vs FCP's
own xmeml export).
"""
from __future__ import annotations

import re
import struct
from pathlib import Path
from urllib.parse import unquote

from . import emit
from . import fcp_parser

_CLIP_CLS = bytes.fromhex("1454238fe4f5d611a348000393bb03ee")   # universal clipitem class GUID
_GTAG = b"\x01\x01\x00\x00\x00\x18\x00\x00\x00"


def resolve_clip_names(fcp_path: str | Path) -> list[str | None]:
    """Per-clipitem names in file order, resolved through the object-table walk
    (keyg_walker2): each clipitem class-tag span's name value is an inline string or
    a STRREF into the object table. Exact on synthetic; on real projects it is exact
    for the object table's exact region (the allocation-drift close makes it global)."""
    from . import keyg_walker2 as W
    d = Path(fcp_path).read_bytes()
    inl = d.find(_GTAG + b"\x01\x01" + _CLIP_CLS)
    if inl < 0:
        return []
    m = re.search(re.escape(_GTAG + b"\x01\x00") + rb"(....)", d[inl:inl + 400_000], re.DOTALL)
    cid = struct.unpack("<I", m.group(1))[0] if m else None
    tags = sorted({inl, *([t.start() for t in
        re.finditer(re.escape(_GTAG + b"\x01\x00" + struct.pack("<I", cid)), d)] if cid else [])})
    tbl = W.object_table(d, 0x2e, len(d) - 16)
    names: list[str | None] = []
    for k, a in enumerate(tags):
        seg = d[a:(tags[k + 1] if k + 1 < len(tags) else len(d))]
        mi = re.search(rb"\x1f\x00\x00\x00\x01\x01(....)", seg)      # inline string
        if mi:
            ln = struct.unpack("<I", mi.group(1))[0]
            try:
                names.append(seg[mi.end():mi.end() + ln].decode("utf-8")); continue
            except UnicodeDecodeError:
                pass
        mr = re.search(rb"\x1f\x00\x00\x00\x01\x00(....)", seg)      # STRREF
        names.append(tbl.get(struct.unpack("<I", mr.group(1))[0], (None, None))[1] if mr else None)
    return names


def _clip_from_timing(idx: int, t: dict, file_id: str, tb: int, name: str | None) -> emit.Clip:
    return emit.Clip(
        name=name or f"clip{idx + 1}",
        in_=int(t["in"]) if t.get("in") is not None else 0,
        out=int(t["out"]), start=int(t["start"]), end=int(t["end"]),
        file_id=file_id, timebase=tb, masterclipid=name,
    )


def export_single_sequence(fcp_path: str | Path, *, name: str = "sequence",
                           timebase: int = 25, width: int = 1920, height: int = 1080,
                           pathurl: str | None = None) -> bytes:
    """Full export for a single-track sequence (synthetic corpus). Exact timing;
    a single shared file (the master) referenced by every clip."""
    clips = fcp_parser.timeline_clips(fcp_path)
    if not clips:
        raise ValueError("no timeline clips found (needs an inlined/open sequence)")
    try:
        names = resolve_clip_names(fcp_path)
    except Exception:
        names = []
    dur = max(int(c["end"]) for c in clips)
    fid = "file01"
    f = emit.File(id=fid, name=f"{name}.mov", pathurl=pathurl, duration=dur,
                  timebase=timebase, width=width, height=height)
    track = emit.Track("video", [
        _clip_from_timing(i, c, fid, timebase, names[i] if i < len(names) else None)
        for i, c in enumerate(clips)
    ])
    seq = emit.Sequence(name=name, duration=dur, timebase=timebase, width=width,
                        height=height, files={fid: f}, video_tracks=[track])
    return emit.build_project([seq], name=name)


# --- multi-sequence export (object-table walker grouper) ----------------------

def _enriched_sequences(fcp_path):
    """Per-sequence rich structure for faithful xmeml: real rate (framebase/ntscrate)
    and dims (vidm.width/height), and the video/audio TRACK split restored. Reuses the
    validated grouper's resolved names+timing (its flat `items` are in vidm-then-audm
    track order, effects filtered) and re-derives the track boundaries from the tree."""
    from . import keyg_grouper as G
    out, doc = G.grouper(fcp_path, with_meta=True)
    tops = G._find_sequences(doc)
    resolve_pathurl = G.build_pathurl_resolver(doc)   # el -> (master_uuid, path, subclip)
    tc_by_path = G.build_source_tc_map(doc)           # pathurl -> media start timecode
    media_by_path, media_by_name = G.build_source_media_map(doc)  # -> native media chars
    # media duration per source NAME (the F64 `duration` of a clip's inline file
    # T0C; unique per source) — the fallback join for a retimed clip whose own
    # file object is a bare reference.  valuemax of FCP's timeremap graphdict is
    # exactly this - 1 (oracle-verified 834/834).
    name_md = {}
    for nd in doc.root.walk():
        fno = doc.get(nd, "file")
        if fno is None or not fno.children:
            continue
        du = doc.get(fno, "duration")
        nm = doc.resolve_str(doc.get(nd, "name"))
        if du is not None and du.value is not None and nm:
            name_md.setdefault(nm, float(du.value))
    result = []
    for seq, flat in zip(tops, out):
        fb, nr = doc.get(seq, "framebase"), doc.get(seq, "ntscrate")
        tb = int(fb.value) if fb is not None else 25
        ntsc = "TRUE" if (nr is not None and nr.value) else "FALSE"
        med = doc.get(seq, "media")
        vidm = doc.get(med, "vidm") if med is not None else None
        w = doc.get(vidm, "width") if vidm is not None else None
        h = doc.get(vidm, "height") if vidm is not None else None
        width = int(w.value) if w is not None else 1920
        height = int(h.value) if h is not None else 1080
        # Walk the tree track-by-track (vidm then audm) and build each track as an
        # ORDERED, kind-tagged item list: clips are pulled from the grouper's flat
        # `items` (its resolved names/timing) one-per-clip-element — matching the
        # grouper's own effect-filtered walk order — while transitions/generators are
        # surfaced directly from the tree and interleaved in place.
        items, pos = flat["items"], 0
        vtracks, atracks = [], []
        for mk, mt in (("vidm", "video"), ("audm", "audio")):
            m = doc.get(med, mk) if med is not None else None
            trk = doc.get(m, "track") if m is not None else None
            if trk is None:
                continue
            for te in trk.elements():
                cl = doc.get(te, "clip")
                if cl is None:
                    continue
                chunk = []
                els = cl.elements()
                for eli, el in enumerate(els):
                    kind = G._elem_kind(doc, el)
                    if kind == "clip":
                        if pos < len(items):
                            it = dict(items[pos]); pos += 1
                            it["kind"] = "clip"
                            it["_el"] = el              # for link sync-group resolution
                            it["link_members"] = G.clip_link_members(doc, el)
                            (it["master_uuid"], it["pathurl"],
                             it["subclip"]) = resolve_pathurl(el)
                            it["source_tc"] = tc_by_path.get(it["pathurl"])
                            if not it.get("name") and it["pathurl"]:
                                # FCP substitutes the master name for empty/unresolved
                                # clip names; the master defaults to the source stem.
                                base = unquote(it["pathurl"].rstrip("/").rsplit("/", 1)[-1])
                                it["name"] = base.rsplit(".", 1)[0] or None
                            it["meta"] = G.clip_metadata(doc, el, te)
                            it["compositemode"] = G.clip_composite_mode(doc, el)
                            it["alphatype"] = G.clip_alphatype(doc, el)
                            it["alphareverse"] = G.clip_alpha_reverse(doc, el)
                            an = doc.get(el, "anamorphic")
                            it["anamorphic"] = bool(an is not None and an.value)
                            it["speed"] = G.clip_speed(doc, el)
                            if it["speed"]:
                                # media (source file) length for the retime graph's
                                # valuemax and the real out-keyframe: the clip's own
                                # inline file duration, else the per-name map.
                                md = None
                                fno = doc.get(el, "file")
                                if fno is not None and fno.children:
                                    du = doc.get(fno, "duration")
                                    if du is not None and du.value is not None:
                                        md = float(du.value)
                                if md is None:
                                    md = name_md.get(it.get("name"))
                                it["speed"]["media_duration"] = md
                            dur = doc.get(el, "duration")   # clip's real duration (FCP's
                            if dur is not None:             # <duration>), not max-out
                                it["duration"] = int(dur.value)
                            if it["speed"] is None:
                                # v0x13 reverse remap (no 14FCSpeedSegment on
                                # that dialect): FCP exports the clip's
                                # in/out/duration one frame LOWER than stored
                                # (oracle-pinned, MASTER.xml 3/3) and the
                                # graphdict in the shifted coordinates
                                rr = G.clip_reverse_remap(doc, el)
                                if rr is not None:
                                    it["speed"] = rr
                                    it["in"] -= 1
                                    it["out"] -= 1
                                    it["duration"] = rr["duration"]
                            # per-clip recovered filters — audio levels/pan and the
                            # video motion transforms (Basic Motion/Crop/Opacity, with
                            # keyframes); empty for clips with no such data.
                            it["filters"] = (G.clip_audio_filters(doc, el)
                                             + G.clip_motion_filters(doc, el))
                            it["markers"] = G.clip_markers(doc, el)
                            it["color"] = G.clip_color_correctors(doc, el)
                            it["named_filters"] = (G.clip_named_filters(doc, el)
                                                   + G.clip_audio_named_filters(doc, el))
                            chunk.append(it)
                    elif kind == "transition":
                        chunk.append(G.transition_fields(
                            doc, el, mt,
                            prev_el=els[eli - 1] if eli > 0 else None,
                            next_el=els[eli + 1] if eli + 1 < len(els) else None))
                    else:
                        chunk.append(G.generator_fields(doc, el, mt))
                (vtracks if mt == "video" else atracks).append(chunk)
        if pos < len(items):                     # any unmapped clips -> extra video track
            vtracks.append([dict(it, kind="clip") for it in items[pos:]])
        result.append({"name": flat["name"], "timebase": tb, "ntsc": ntsc,
                       "width": width, "height": height,
                       "video": vtracks, "audio": atracks,
                       "tc_by_path": tc_by_path,
                       "media_by_path": media_by_path,
                       "media_by_name": media_by_name,
                       "markers": G.clip_markers(doc, seq),
                       "start_tc": G.sequence_timecode(doc, seq)})
    return result


def export_project_rich(fcp_path) -> bytes:
    """Faithful multi-track export: real rate/dims + video/audio track split."""
    from . import keyg_grouper as G  # noqa: F401  (ensures grouper import path)
    rich = _enriched_sequences(fcp_path)
    seqs = []
    for s in rich:
        tb, ntsc = s["timebase"], s["ntsc"]
        allclips = [c for tr in s["video"] + s["audio"] for c in tr]
        dur = max((int(c["end"]) for c in allclips if c.get("end") is not None), default=0)
        files: dict[str, emit.File] = {}
        by_fname: dict[str, str] = {}

        def _mk_track(chunk, mtype):
            clips = []
            for i, it in enumerate(chunk):
                if it.get("kind", "clip") != "clip":   # transitions/generators: legacy path skips
                    continue
                fname = it.get("file")
                if fname:
                    fid = by_fname.get(fname)
                    if fid is None:
                        fid = f"file{len(files) + 1:02d}"
                        by_fname[fname] = fid
                        files[fid] = emit.File(id=fid, name=fname, timebase=tb,
                                               mediatype=mtype)
                else:
                    fid = "file00"
                    files.setdefault(fid, emit.File(id=fid, name=f"{s['name']}.mov",
                                                    timebase=tb, mediatype=mtype))
                clips.append(emit.Clip(
                    name=it.get("name") or f"clip{i + 1}",
                    in_=int(it["in"]) if it.get("in") is not None else 0,
                    out=int(it["out"]) if it.get("out") is not None else 0,
                    start=int(it["start"]) if it.get("start") is not None else 0,
                    end=int(it["end"]) if it.get("end") is not None else 0,
                    file_id=fid, timebase=tb, masterclipid=it.get("name"),
                    mediatype=mtype))
            return emit.Track(mtype, clips)

        vtr = [_mk_track(ch, "video") for ch in s["video"] if ch]
        atr = [_mk_track(ch, "audio") for ch in s["audio"] if ch]
        seqs.append(emit.Sequence(
            name=s["name"] or f"sequence{len(seqs) + 1}", duration=dur,
            timebase=tb, ntsc=ntsc, width=s["width"], height=s["height"],
            files=files, video_tracks=vtr, audio_tracks=atr))
    return emit.build_project(seqs, name=Path(fcp_path).stem)


def _emit_filters(specs):
    """Map keyg_grouper.clip_audio_filters() neutral dicts to emit.Filter objects."""
    out = []
    for f in specs or []:
        params = [emit.Parameter(
            name=p["name"], parameterid=p["parameterid"],
            valuemin=p.get("valuemin"), valuemax=p.get("valuemax"), value=p.get("value"),
            keyframes=[emit.Keyframe(when=w, value=v) for w, v in p["keyframes"]],
            point=p.get("point", False), idfirst=p.get("idfirst", False))
            for p in f["parameters"]]
        out.append(emit.Filter(
            effectid=f["effectid"], name=f["name"], category=f["category"],
            mediatype=f["mediatype"], effecttype=f.get("effecttype", ""),
            parameters=params))
    return out


_IMG_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".gif", ".bmp", ".psd", ".tga", ".ai")


def _is_still(name: str) -> bool:
    return name.lower().endswith(_IMG_EXT)


def _pathurl(name: str) -> str:
    """A well-formed offline pathurl from a source name (Tier 1 — enough for FCP to
    build an offline clip; Tier 2 replaces this with the real path from the binary)."""
    from urllib.parse import quote
    return "file://localhost/offline/" + quote(name, safe="")


# Percent-encoding safe-set FCP itself uses for <pathurl> (measured against the
# oracle export): alnum plus these punctuation are left literal; space and every
# non-ASCII byte are percent-encoded, filenames stay HFS+ NFD-decomposed.
# FCP leaves '&' literal in pathurls (XML-escaped to &amp;), NOT percent-encoded as
# %26. A pathurl with %26 makes Premiere's importer silently reject the whole XML
# (Resolve tolerates it). Keeping '&' safe reproduces FCP's exact encoding.
_PATHURL_SAFE = "/():,-._&"


def _real_pathurl_index(fcp_path) -> tuple[dict, dict]:
    """Real media pathurls recovered from the embedded Mac Alias blobs, ready to
    join by filename.

    Each media reference stores an alias record whose tail carries tag 0x12 (the
    volume-relative POSIX path, HFS+ NFD) immediately followed by tag 0x13
    (``/Volumes/<volume>`` mount point). Joining them yields the exact absolute
    logical path; percent-encoding it with `_PATHURL_SAFE` reproduces FCP's own
    ``<pathurl>`` string byte-for-byte (validated: 212/212 of the oracle export's
    unique pathurls). Returns ``(by_basename, by_stem)``, each name -> set of
    candidate pathurls; a name with a single candidate is an unambiguous hit.
    """
    from urllib.parse import quote
    d = Path(fcp_path).read_bytes()
    tag13 = re.compile(rb".{0,3}\x00\x13(..)(/Volumes/[^\x00\xff]{1,60})", re.S)
    by_bn: dict[str, set] = {}
    by_stem: dict[str, set] = {}
    # zero-width lookahead + DOTALL: every 0x0012 tag position is visited even when
    # the length low byte is 0x0a (\n) or a prior tag's bytes abut it.
    for m in re.finditer(rb"(?=\x00\x12(..))", d, re.S):
        ln = int.from_bytes(m.group(1), "big")
        if not (2 <= ln <= 300):
            continue
        p = m.start() + 4
        rel_b = d[p:p + ln]
        if not rel_b.startswith(b"/"):
            continue
        try:
            rel = rel_b.decode("utf-8")
        except UnicodeDecodeError:
            continue
        v = tag13.match(d[p + ln:p + ln + 80])
        if v is None:
            continue
        lv = int.from_bytes(v.group(1), "big")
        try:
            mount = v.group(2)[:lv].decode("utf-8")          # "/Volumes/<vol>"
            vol = mount.split("/Volumes/", 1)[1]
        except (UnicodeDecodeError, IndexError):
            continue
        # FCP writes a network mount (cifs/afp/smb/nfs) with its full /Volumes/ mount
        # path, but a physical volume volume-rooted (…/disque 1/… not /Volumes/disque 1/…).
        network = any(s in d[p + ln:p + ln + 160]
                      for s in (b"cifs", b"afpfs", b"smb://", b"afp://", b"nfs", b"webdav"))
        base = mount if network else "/" + vol
        url = "file://localhost" + quote(base + rel, safe=_PATHURL_SAFE)
        bn = rel.rsplit("/", 1)[-1]
        by_bn.setdefault(bn, set()).add(url)
        stem = bn.rsplit(".", 1)[0].lower() if "." in bn else bn.lower()
        by_stem.setdefault(stem, set()).add(url)
    return by_bn, by_stem


def _resolve_pathurl(name, filek, by_bn, by_stem):
    """Real pathurl for a source, or None when it can't be pinned unambiguously.

    Joins on the media filename (the resolved ``file`` field, else the clip name):
    an exact basename with a single candidate wins; otherwise the extension-less
    stem with a single candidate (covers clip names stored without an extension,
    e.g. ``BOURGUIBA`` -> ``BOURGUIBA.mov``). Ambiguous (same basename on several
    volumes/cards) or unknown -> None, so the caller keeps the offline placeholder
    rather than guessing the wrong copy."""
    for cand in (filek, name):
        if not cand:
            continue
        bn = cand.rsplit("/", 1)[-1]
        hits = by_bn.get(bn)
        if hits and len(hits) == 1:
            return next(iter(hits))
    for cand in (filek, name):
        if not cand:
            continue
        base = cand.rsplit("/", 1)[-1]
        stem = base.rsplit(".", 1)[0].lower() if "." in base else base.lower()
        hits = by_stem.get(stem)
        if hits and len(hits) == 1:
            return next(iter(hits))
    return None


# Non-English transition display names -> canonical English effectid (extend as new
# language exports are seen; the binary `name` resolves reliably where `scriptid` drifts).
_XLATE_ALIAS = {
    "Fondu enchaîné": "Cross Dissolve", "Fondu enchainé": "Cross Dissolve",
    "Fondu": "Cross Dissolve",
    "Fondu entrant/sortant": "Fade In Fade Out Dissolve",
    "Fondu via fond uni": "Dip to Color Dissolve",
}


def _audio_transition_effect(recovered):
    """Audio transition -> the stock cross-fade effectid. FCP7 has two: 0 dB and +3 dB.
    Distinguish by the recovered name/scriptid ('+3dB' / '3dB'); default to 0 dB."""
    r = (recovered or "").replace(" ", "")
    if "3dB" in r or "+3" in r:
        return "KGAudioTransCrossFade3dB"
    return "KGAudioTransCrossFade0dB"


def _transition_effect(effectid):
    """Resolve a recovered transition name/scriptid to a known built-in effectid.
    The full effect block is looked up from the transition template library at emit
    time; unknown / plugin / drift -> Cross Dissolve so import never breaks."""
    from .fcp_transitions import TRANSITION_EFFECTS
    if effectid in TRANSITION_EFFECTS:
        return effectid
    alias = _XLATE_ALIAS.get(effectid)
    if alias in TRANSITION_EFFECTS:
        return alias
    return "Cross Dissolve"


def _resolve_links(link_reg):
    """Attach <link> sync-group members to each clip's emit.Clip (in place).

    The binary stores the group ONLY on the video clip (keyg_grouper.clip_link_members
    decodes it to [(mediatype, trackindex, clipindex)]), and the member coordinates
    resolve EXACTLY: `clipindex` is the 1-based ordinal of the member's ELEMENT in the
    target track's element list (clips + transitions + generators all counted) —
    byte-verified 56/56 on the video self-entries and 40/40 groups == FCP's own <link>
    targets on both EPK and managed (0 wrong; the earlier nearest-start heuristic
    mis-resolved ~40% because linked audio carries the -1 chained-start sentinel).
    link_reg maps (mediatype, track_idx0) -> one entry per track element, (item,
    emit.Clip) for clips and None for transitions/generators, so lst[clipindex-1]
    addresses the member directly.  FCP replicates the same link set onto every
    member, so we do too.  Correct-or-absent guards: every member must resolve to a
    distinct clip, the video self-member must be this clip, and no member may already
    belong to another group — otherwise the whole group is skipped (a wrong <link>
    mis-syncs the NLE)."""
    def _at(mt, ti, ci):
        lst = link_reg.get((mt, ti - 1))
        if not lst or not (1 <= ci <= len(lst)):
            return None
        ent = lst[ci - 1]
        return ent[1] if ent is not None else None

    for (mt, tidx0), entries in link_reg.items():
        for ent in entries:
            if ent is None:
                continue
            it, vclip = ent
            members = it.get("link_members") or []
            if not members:
                continue                        # unlinked
            resolved, seen = [], set()
            ok = False
            for m, ti, ci, gi in members:
                mkind = "video" if m == 1 else "audio"
                cand = _at(mkind, ti, ci)
                if cand is None or id(cand) in seen or cand.links:
                    resolved = []
                    break
                seen.add(id(cand))
                if cand is vclip:
                    ok = True                   # the decoded self-member matches
                resolved.append((mkind, ti, ci, gi, cand))
            if not resolved or not ok:
                continue
            linkset = [{"linkclipref": c.itemid, "mediatype": mk,
                        "trackindex": ti, "clipindex": ci, "groupindex": gi}
                       for (mk, ti, ci, gi, c) in resolved]
            for *_ignored, c in resolved:
                c.links = list(linkset)


def export_importable_sequence(fcp_path, *, seq_index=None, seq_name=None,
                               drop_stills=False, drop_generators=False,
                               master_bin=True) -> bytes:
    """Build a single sequence as an FCP-IMPORTABLE document (oracle shape): every
    clipitem gets a full <file> (offline pathurl + media chars) and a <masterclipid>
    resolving into a Master Clips bin, so FCP actually creates the timeline clips.

    Pick the sequence by `seq_index` (into _enriched_sequences order) or `seq_name`
    (first match).  Media are offline until Tier 2 wires real pathurls."""
    rich = _enriched_sequences(fcp_path)
    if seq_index is not None:
        seq_idx = seq_index
    elif seq_name is not None:
        seq_idx = next(i for i, x in enumerate(rich)
                       if (x["name"] or "").strip() == seq_name.strip())
    else:
        seq_idx = max(range(len(rich)),
                      key=lambda i: sum(len(t) for t in rich[i]["video"] + rich[i]["audio"]))
    s = rich[seq_idx]
    tb, ntsc = s["timebase"], s["ntsc"]

    # real media pathurls recovered from the binary's alias blobs, built once
    # per export and joined per source below (unresolved -> offline placeholder).
    by_bn, by_stem = _real_pathurl_index(fcp_path)

    # source key per clip: prefer the resolved media file, else the clip name, else unique
    files: dict[str, emit.File] = {}
    used_ids: set[str] = set()
    unnamed = 0

    def _src_key(it):
        nonlocal unnamed
        # key by the master UUID when known: a basename can name several distinct
        # real sources (same clip name on different camera cards), which must stay
        # separate files. Fall back to file/name for clips with no resolved master.
        k = it.get("master_uuid") or it.get("file") or it.get("name")
        if not k:
            unnamed += 1
            return f"__unnamed_{unnamed}"
        return k

    # pass 1: per source, file duration (max out) and the media types it's used as
    # (a synced .MOV appears in both a video and an audio track -> needs both blocks).
    # Only CLIP items have files/keymap entries; transitions/generators are emitted
    # from their own fields and must not consume the keymap.
    flat = ([(it, "video") for tr in s["video"] for it in tr if it.get("kind", "clip") == "clip"]
            + [(it, "audio") for tr in s["audio"] for it in tr if it.get("kind", "clip") == "clip"])
    all_items = [it for it, _ in flat]
    src_dur: dict[str, int] = {}
    src_types: dict[str, set] = {}
    src_retimed: set[str] = set()             # sources with a speed segment
    src_pathurl: dict[str, str | None] = {}   # source key -> real pathurl (or None)
    keymap = []
    # stereo/multichannel source channel (FCP's <sourcetrack><trackindex>).
    # FCP's own rule (MASTER.xml + 7 MUSEO oracles): trackindex is the clip's
    # CHANNEL POSITION within its stereo/dual-mono LINK GROUP — the pair of
    # timeline tracks one source occupies gets ti 1, 2 — independent of how
    # many same-source clips stack at other times, and NOT capped by the
    # file's channelcount (mono dual-mono gets ti=2 on the pair's second
    # track).  A trackindex with no matching indexed track in the master
    # clip's <media><audio> is unbindable and imports into Resolve as the
    # 0xFFFF uninitialised-source-range sentinel (-52:55:45:65535 class).
    #   PRIMARY:  ti = 1 + ordinal among the AUDIO members of the clip's
    #             decoded <link> sync group (byte-validated 40/40).
    #   FALLBACK: same-source numbering keyed on the RESOLVED start (the -1
    #             chained-start sentinel is chained through the track cursor
    #             first — keying on raw -1 collided every chained clip of a
    #             source and exploded ti to 1..N).
    audio_link_ti: dict[int, int] = {}
    _ti_conflict: set[int] = set()
    for chunks in (s["video"], s["audio"]):
        for chunk in chunks:
            for it in chunk:
                if it.get("kind", "clip") != "clip":
                    continue
                members = it.get("link_members") or []
                if not members:
                    continue
                targets = []
                for m, ti, ci, gi in members:
                    lst = s["video"] if m == 1 else s["audio"]
                    if not (1 <= ti <= len(lst) and 1 <= ci <= len(lst[ti - 1])):
                        targets = None
                        break
                    cand = lst[ti - 1][ci - 1]
                    if cand.get("kind", "clip") != "clip":
                        targets = None
                        break
                    targets.append((m, gi, cand))
                if not targets:
                    continue
                # channel ordinal WITHIN the group's same-source audio
                # members: a stereo/dual-mono pair shares one source -> 1, 2
                # (EPK/managed stereo, MUSEO dual-mono, the Aaron wav); a
                # sync group of DISTINCT mono masters is not a pair — each
                # member reads its own channel 1 (palastin's V+A1+A2 mono
                # groups: FCP's own export writes 1/1).  Same-source = same
                # name with COMPATIBLE master uuids: two different resolved
                # masters split the bucket (palastin), an unresolved side
                # matches anything (managed's asymmetric channel copies
                # resolve a uuid on one channel only).
                seen_aud: list = []
                for m, _gi, cand in targets:
                    if m != 2:
                        continue
                    bucket = cand.get("name") or cand.get("file")
                    uu = cand.get("master_uuid")
                    ch = 1 + sum(
                        1 for b, u in seen_aud
                        if b == bucket and (u is None or uu is None or u == uu))
                    seen_aud.append((bucket, uu))
                    prev = audio_link_ti.get(id(cand))
                    if prev is not None and prev != ch:
                        _ti_conflict.add(id(cand))
                    else:
                        audio_link_ti[id(cand)] = ch
    for cid in _ti_conflict:
        audio_link_ti.pop(cid, None)     # ambiguous: fall back (correct-or-absent)
    # resolved starts (fallback key): chain -1 through each track's cursor,
    # mirroring _mk_track's placement arithmetic
    resolved_start: dict[int, int] = {}
    for chunks in (s["video"], s["audio"]):
        for chunk in chunks:
            cursor = 0
            for it in chunk:
                st = it.get("start")
                en = it.get("end")
                if it.get("kind", "clip") != "clip":
                    st = st if (st is not None and st >= 0) else cursor
                    en = en if (en is not None and en >= 0) else st
                    cursor = max(cursor, int(en))
                    continue
                inn = int(it["in"]) if it.get("in") is not None else 0
                ou = int(it["out"]) if it.get("out") is not None else 0
                st_raw = int(st) if st is not None else 0
                en_raw = int(en) if en is not None else 0
                rst = st_raw if st_raw >= 0 else cursor
                resolved_start[id(it)] = rst
                en_r = en_raw if en_raw >= 0 else rst + max(1, ou - inn)
                cursor = max(cursor, en_r)
    audio_channel: dict[int, int] = {}
    src_max_ti: dict[str, int] = {}       # master audio track exposure (emit)
    _achan_seen: dict[tuple, int] = {}
    _chan_first: dict[tuple, dict] = {}   # (source, start) -> first channel item
    for it, mt in flat:
        k = _src_key(it)
        keymap.append(k)
        if mt == "audio":
            ch = audio_link_ti.get(id(it))
            if ch is None:
                st = resolved_start.get(
                    id(it), int(it["start"]) if it.get("start") is not None else 0)
                ch = _achan_seen.get((k, st), 0) + 1
                _achan_seen[(k, st)] = ch
            audio_channel[id(it)] = ch
            src_max_ti[k] = max(src_max_ti.get(k, 0), ch)
            # a stereo pair shares ONE set of level/pan rubber bands and markers;
            # the binary stores them on the FIRST channel element only (the
            # second is an unattached copy), while FCP emits them on BOTH
            # clipitems — replicate to the sibling channels.  Key by the
            # resolved NAME + source range: channels share name and in/out
            # exactly, while `start` can be the -1 chained sentinel on one
            # side and the master/pathurl can resolve asymmetrically (inline
            # uuid string on one channel, raw ref id on the copy).
            fkey = (it.get("name") or it.get("pathurl") or k,
                    it.get("in"), it.get("out"))
            first = _chan_first.setdefault(fkey, it)
            if first is not it:
                if not it.get("filters") and first.get("filters"):
                    it["filters"] = first["filters"]
                if not it.get("markers") and first.get("markers"):
                    it["markers"] = first["markers"]
        out = int(it["out"]) if it.get("out") is not None else 0
        if it.get("speed"):
            # a slowed clip's out-point lives in stretched time, past the real media
            # end — never let it inflate the file duration.  inputUsed (the real
            # source frames consumed) is the fallback when the binary's own media
            # duration is unknown at file creation.
            src_dur[k] = int(round(it["speed"]["input_used"]))
            src_retimed.add(k)
        else:
            src_dur[k] = max(src_dur.get(k, 1), out, 1)
        src_types.setdefault(k, set()).add(mt)
        if k not in src_pathurl:
            # structural per-master alias (exact, name-independent) is primary; the
            # basename index is the fallback for masters the structural walk misses.
            src_pathurl[k] = it.get("pathurl") or _resolve_pathurl(
                it.get("name"), it.get("file"), by_bn, by_stem)
        if not it.get("source_tc") and src_pathurl.get(k):
            # a clip whose pathurl came from the NAME fallback still deserves its
            # source timecode: re-join by the resolved url
            it["source_tc"] = s.get("tc_by_path", {}).get(src_pathurl[k])

    def _uniq(base: str) -> str:
        cand = base or "clip"
        n = 1
        while cand in used_ids:
            n += 1
            cand = f"{base}_{n}"
        used_ids.add(cand)
        return cand

    ki = 0

    fid_of: dict[str, str] = {}          # source key -> emitted file id (globally unique)
    # sync-group resolution registry: (mediatype, track_idx0) -> ONE entry per track
    # ELEMENT in order — (item, emit.Clip) for clips, None for transitions/generators —
    # so a decoded link clipindex addresses lst[clipindex-1] directly.
    link_reg: dict[tuple, list] = {}

    def _mk_track(chunk, mtype, tidx=0):
        nonlocal ki
        reg = link_reg.setdefault((mtype, tidx), [])
        out_items = []                   # emit.Clip | emit.Transition | emit.Generator
        cursor = 0                       # last resolved end, for chaining -1 sentinels
        n = len(chunk)
        for idx, it in enumerate(chunk):
            kind = it.get("kind", "clip")
            if kind == "transition":
                reg.append(None)
                st = it.get("start"); en = it.get("end")
                st = st if (st is not None and st >= 0) else cursor
                en = en if (en is not None and en >= 0) else st
                if en - st < 1:              # zero-length transition -> drop; the two
                    continue                 # clips butt-join, the cut is preserved
                cursor = max(cursor, en)
                eid = (_audio_transition_effect(it.get("effectid")) if mtype == "audio"
                       else _transition_effect(it.get("effectid")))
                out_items.append(emit.Transition(
                    start=st, end=en, alignment=it.get("alignment", "center"),
                    mediatype=mtype, effectid=eid, timebase=tb, ntsc=ntsc))
                continue
            if kind == "generator":
                reg.append(None)
                if drop_generators or mtype == "audio":
                    continue                 # a Text generator defines no cut and is
                    #                          meaningless on an audio track -> drop it
                gdur = it.get("duration") or it.get("out") or 1
                gin = it.get("in") or 0
                gout = it.get("out") or (gin + gdur)
                gs = it.get("start")
                gs = gs if (gs is not None and gs >= 0) else cursor
                ge = it.get("end")
                ge = ge if (ge is not None and ge >= 0) else gs + max(1, gdur)
                cursor = max(cursor, ge)     # chain like clips: never emit -1/0 geometry
                title = it.get("text")
                out_items.append(emit.Generator(
                    name=it.get("name") or "Text",
                    in_=gin, out=gout, start=gs, end=ge,
                    duration=max(1, gdur), text=title or "",
                    itemid=_uniq((title or it.get("name") or "Text") + " gen"),
                    mediatype=mtype, timebase=tb, ntsc=ntsc))
                continue
            # clip
            k = keymap[ki]; ki += 1
            label = it.get("name") or it.get("file") or f"clip{ki}"
            if drop_stills and _is_still(label):     # diagnostic: isolate still-abort
                reg.append(None)
                continue
            if k not in fid_of:
                types = src_types[k]
                # file id lives in a distinct id-space from clipitem ids (trailing
                # space, oracle-style) AND is globally unique — FCP aborts import on
                # any duplicate element id.
                fid = _uniq(f"{label} ")
                fid_of[k] = fid
                # native media characteristics recovered from the binary's reader
                # objects (0-wrong vs FCP's own exports): dims, rate, audio chars,
                # the byte-accurate still flag and the true media duration.
                pu = src_pathurl.get(k)
                mbp = s.get("media_by_path") or {}
                mbn = s.get("media_by_name") or {}
                mc = mbp.get(pu) if pu else None
                if mc is None:
                    for cn in ((unquote(pu.rsplit("/", 1)[-1]),) if pu else ()) + (label,):
                        mc = mbn.get(cn) or mbn.get(cn.rsplit(".", 1)[0])
                        if mc:
                            break
                mc = mc or {}
                still = _is_still(label) or bool(mc.get("still"))
                if still:
                    # stills: FCP wants the file duration decoupled from the
                    # clipitem's timeline duration — the binary's own still-file
                    # duration when known (4 or 2), else the classic sentinel.
                    file_dur = int(mc["duration"]) if mc.get("duration") else 2
                elif k in src_retimed:
                    # the true media length when the binary has it (FCP's own
                    # number), else inputUsed — the real source frames consumed,
                    # which Resolve-validated relink needs (never the stretched
                    # timeline out-point).
                    file_dur = int(mc["duration"]) if mc.get("duration") else src_dur[k]
                elif mc.get("duration"):
                    file_dur = int(mc["duration"])
                else:
                    file_dur = src_dur[k]
                files[fid] = emit.File(
                    id=fid, name=label,
                    pathurl=pu or _pathurl(label), duration=file_dur,
                    timebase=int(mc["tb"]) if mc.get("tb") else tb,
                    ntsc=mc.get("ntsc") or ntsc,
                    width=int(mc["width"]) if mc.get("width") else s["width"],
                    height=int(mc["height"]) if mc.get("height") else s["height"],
                    samplerate=int(mc["samplerate"]) if mc.get("samplerate") else 48000,
                    depth=int(mc["depth"]) if mc.get("depth") else 16,
                    channels=int(mc["channels"]) if mc.get("channels") else 2,
                    mediatype=("video" if "video" in types else "audio"),
                    has_video=("video" in types or bool(mc.get("has_video"))),
                    has_audio=("audio" in types or bool(mc.get("has_audio"))),
                    stillframe=still, source_tc=it.get("source_tc"),
                    # master <media><audio> must expose one indexed track per
                    # INSTANTIATED timeline channel (mono dual-mono: ti=2 with
                    # channelcount 1 — oracle 'grognon2' shape), or the clip
                    # can't bind and Resolve shows the 0xFFFF sentinel
                    audio_master_tracks=src_max_ti.get(k) or None,
                    meta=it.get("meta") or {})
            fid = fid_of[k]
            inn = int(it["in"]) if it.get("in") is not None else 0
            ou = int(it["out"]) if it.get("out") is not None else 0
            st_raw = int(it["start"]) if it.get("start") is not None else 0
            en_raw = int(it["end"]) if it.get("end") is not None else 0
            # -1 = a transition boundary. KEEP -1 only when a transitionitem is
            # adjacent on that side (it defines the boundary, as in the oracle);
            # otherwise resolve by chaining so FCP can still place the clip.
            prev_trans = idx > 0 and chunk[idx - 1].get("kind") == "transition"
            next_trans = idx < n - 1 and chunk[idx + 1].get("kind") == "transition"
            st = st_raw if st_raw >= 0 else (st_raw if prev_trans else cursor)
            if en_raw >= 0:
                en = en_raw
            elif next_trans:
                en = en_raw                          # keep -1; the next transition defines it
            else:
                en = max(st if st >= 0 else cursor, cursor) + max(1, ou - inn)
            # Source out MUST satisfy out-in == timeline span for a plain non-retimed clip:
            # a strict importer (Premiere) silently rejects a sequence whose clips' source
            # ranges disagree with their timeline ranges. it["out"] is the full media
            # length, so recompute from the resolved timeline span (start -1 resolves to
            # the current cursor -- the transition cut point). EXCLUDE the three cases
            # whose source range legitimately differs from the timeline (FCP-verified:
            # 166/166 plain EPK clips obey the invariant, 0 of these do): retimed clips
            # (the timeremap graph maps timeline->source non-linearly), subclips (in/out
            # are subclip-relative, mapped by subclipinfo offsets), and stills.
            # Require a concrete start too: a transition-adjacent clip keeps its decoded
            # out (its -1 boundary is defined by the neighbouring transition, and the
            # decode already matches FCP there -- recomputing from the cursor would drift).
            if (st >= 0 and en >= 0 and not it.get("speed") and not it.get("subclip")
                    and not _is_still(label)):
                ou = inn + max(1, en - st)
            if en >= 0:
                cursor = max(cursor, en)
            clip_obj = emit.Clip(
                name=label, in_=inn, out=ou, start=st, end=en,
                subclip=it.get("subclip"),
                file_id=fid, masterclipid=f"{fid}1", itemid=_uniq(label),
                trackindex=audio_channel.get(id(it), 1) if mtype == "audio" else 1,
                duration=it.get("duration") or src_dur[k], timebase=tb, ntsc=ntsc, mediatype=mtype,
                stillframe=_is_still(label), meta=it.get("meta") or {},
                compositemode=it.get("compositemode"), speed=it.get("speed"),
                alphatype=it.get("alphatype") or "none",
                alphareverse=bool(it.get("alphareverse")),
                anamorphic=bool(it.get("anamorphic")),
                filters=_emit_filters(it.get("filters")), color=it.get("color") or [],
                named_filters=it.get("named_filters") or [],
                markers=it.get("markers") or [])
            out_items.append(clip_obj)
            reg.append((it, clip_obj))
        return emit.Track(mtype, out_items)

    vtr = [_mk_track(ch, "video", ti) for ti, ch in enumerate(s["video"])]
    atr = [_mk_track(ch, "audio", ti) for ti, ch in enumerate(s["audio"])]
    _resolve_links(link_reg)
    dur = max((int(it["end"]) for it in all_items if it.get("end") is not None), default=0)
    seq = emit.Sequence(name=s["name"] or "sequence", duration=dur, timebase=tb,
                        ntsc=ntsc, width=s["width"], height=s["height"],
                        uuid=emit._uuid_from(f"{s['name'] or 'sequence'}|{seq_idx}"),
                        files=files, video_tracks=vtr, audio_tracks=atr,
                        markers=s.get("markers") or [], start_tc=s.get("start_tc"))
    return emit.build_document(seq, master_bin=master_bin)


def export_project(fcp_path, grouper=None, resolver=None) -> bytes:
    """Export a multi-sequence project as xmeml.

    `grouper(fcp_path)` -> [{"name", "items": [{"name","in","out","start",
    "end","file"}]}] (default: keyg_grouper.grouper, the containment-tree
    walk over keyg_walker2 -- names + timing byte-derived, masters excluded,
    nested sequences as items).  `resolver(fcp_path)` -> {global_clip_index:
    (name, file_id, master_id)} optionally overrides per-clip fields (None
    entries keep the grouper's value).

    Validated: mc_one/mc_two/mc_four render their clip-bearing sequence
    identically to export_single_sequence (same names/timing/document shape);
    palastin renders parseable xmeml with its 22 sequences and exact
    per-sequence clipitem counts vs FCP's own export.
    """
    from . import keyg_grouper
    seqs = (grouper or keyg_grouper.grouper)(fcp_path)
    overrides = resolver(fcp_path) if resolver is not None else {}
    tb = 25
    rendered = []
    gidx = 0
    for s in seqs:
        sname = s["name"] or f"sequence{len(rendered) + 1}"
        items = s["items"]
        dur = max((int(it["end"]) for it in items if it.get("end") is not None),
                  default=0)
        shared_fid = "file01"
        files = {shared_fid: emit.File(id=shared_fid, name=f"{sname}.mov",
                                       duration=dur, timebase=tb,
                                       width=1920, height=1080)}
        by_fname: dict[str, str] = {}
        clips = []
        for i, it in enumerate(items):
            name = it.get("name")
            fid = shared_fid
            if it.get("file"):
                fid = by_fname.get(it["file"])
                if fid is None:
                    fid = f"file{len(files) + 1:02d}"
                    by_fname[it["file"]] = fid
                    files[fid] = emit.File(id=fid, name=it["file"], timebase=tb)
            ov = overrides.get(gidx)
            if ov:
                name = ov[0] or name
                fid = ov[1] or fid
            clips.append(_clip_from_timing(i, it, fid, tb, name))
            if ov and ov[2]:
                clips[-1].masterclipid = ov[2]
            gidx += 1
        rendered.append(emit.Sequence(
            name=sname, duration=dur, timebase=tb, width=1920, height=1080,
            files=files, video_tracks=[emit.Track("video", clips)] if clips else []))
    return emit.build_project(rendered, name=Path(fcp_path).stem)


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        doc = export_single_sequence(p, name=Path(p).stem)
        out = Path(p).with_suffix(".export.xml")
        out.write_bytes(doc)
        print(f"{p} -> {out} ({len(doc)} bytes)")
