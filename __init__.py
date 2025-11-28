bl_info = {
    "name": "Blender Shapekey Add-Ons",
    "author": "LupisYoung",
    "version": (1, 4, 2),
    "blender": (3, 6, 0),
    "location": "Object Data Properties > Shape Keys",
    "description": "Organize, search/filter, group-tag, batch-rename, sort, and bulk-edit shapekeys.",
    "warning": "",
    "doc_url": "https://github.com/LupisYoung/Blender-Shapekey-Addons",
    "tracker_url": "https://github.com/LupisYoung/Blender-Shapekey-Addons/issues",
    "support": "COMMUNITY",
    "category": "Object",
}

__version__ = ".".join(map(str, bl_info.get("version", (0, 0, 0))))

import bpy
import json
import urllib.request
import urllib.error
from bpy.types import Operator, Panel, PropertyGroup, UIList, AddonPreferences
import os, sys, re
import time
from bpy.props import (
    BoolProperty,
    StringProperty,
    IntProperty,
    EnumProperty,
    FloatProperty,
    CollectionProperty,
)

try:
    import tomllib as _toml
except Exception:
    _toml = None

_DBL_CLICK = {"name": "", "t": 0.0}
_DBL_THRESHOLD = 0.30

# =====================================================
# Helpers & state
# =====================================================

GITHUB_REPO = "LupisYoung/Blender-Shapekey-Addons"
GITHUB_LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"

_ADDON_ID = __package__ or __name__.split(".", 1)[0]

_MANIFEST_VERSION_CACHE_STR = None
_MANIFEST_VERSION_CACHE_TUP = None

def _manifest_path():
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(pkg_dir, "blender_manifest.toml")
    return p if os.path.isfile(p) else None

def _manifest_version_str():
    """Return exact version string from blender_manifest.toml (e.g. '1.3.0-pre1'), or ''."""
    global _MANIFEST_VERSION_CACHE_STR
    if _MANIFEST_VERSION_CACHE_STR is not None:
        return _MANIFEST_VERSION_CACHE_STR

    path = _manifest_path()
    if not path:
        _MANIFEST_VERSION_CACHE_STR = ""
        return _MANIFEST_VERSION_CACHE_STR

    try:
        with open(path, "rb") as f:
            if _toml:
                data = _toml.load(f)
                v = (data.get("version")
                     or (data.get("addon") or {}).get("version")
                )
                _MANIFEST_VERSION_CACHE_STR = str(v or "").strip()
            else:
                raw = f.read().decode("utf-8", "ignore")
                m = re.search(r'^\s*version\s*=\s*"([^"]+)"\s*$', raw, flags=re.M)
                _MANIFEST_VERSION_CACHE_STR = (m.group(1).strip() if m else "")
    except Exception:
        _MANIFEST_VERSION_CACHE_STR = ""
    return _MANIFEST_VERSION_CACHE_STR

def _parse_semver_to_tuple(vstr: str):
    """
    Convert '1.3.0-pre1' -> (1,3,0, 'pre1') and comparison tuple (1,3,0,-1)
    """
    if not vstr:
        return (0, 0, 0, ""), (0, 0, 0, 0)
    t = vstr[1:] if vstr[:1].lower() == "v" else vstr
    core = re.split(r'[-+]', t, maxsplit=1)[0]
    parts = core.split(".")[:3]
    nums = [int(p) if p.isdigit() else 0 for p in parts] + [0, 0, 0]
    major, minor, patch = nums[:3]
    suffix = ""
    m = re.search(r'-(.+)$', t)
    if m: suffix = m.group(1)
    cmp = (major, minor, patch, -1 if suffix else 0)
    return (major, minor, patch, suffix), cmp

def _current_version_tuple():
    """
    Prefer version from blender_manifest.toml.
    Falls back to bl_info/ __version__ if manifest missing.
    """
    vstr = _manifest_version_str()
    if vstr:
        _full, cmp = _parse_semver_to_tuple(vstr)
        return tuple(cmp[:3])

    try:
        vi = bl_info.get("version", (0, 0, 0))
        return tuple(int(x) for x in list(vi[:3]) + [0, 0])[:3]
    except Exception:
        pass

    vstr = globals().get("__version__", "")
    if isinstance(vstr, str) and vstr:
        full, _cmp = _parse_semver_to_tuple(vstr)
        return tuple(full[:3])

    return (0, 0, 0)

def current_version_display():
    """Human-readable version for UI—shows prerelease if present."""
    vstr = _manifest_version_str()
    if vstr:
        return vstr
    v = bl_info.get("version", (0, 0, 0))
    return ".".join(map(str, v))


def _parse_version_tag(tag: str):
    """Parse GitHub tags like 'v1.3.0-pre1' into a comparison tuple."""
    if not tag:
        return (0, 0, 0, 0)
    _full, cmp = _parse_semver_to_tuple(tag)
    return cmp


def _fetch_latest_tag():
    """Return latest release tag_name from GitHub Releases API, or '' on failure."""
    ua = f"Blender-Shapekey-Add-Ons/{_manifest_version_str() or '0.0.0'}"
    req = urllib.request.Request(GITHUB_LATEST_API, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
        return data.get("tag_name") or ""
    except Exception:
        return ""


def _elide(text: str, max_len: int = 14) -> str:
    text = text or ""
    return text if len(text) <= max_len else (text[:max_len - 1] + "…")


def _sko_split_keyblock_half(obj, src_key, axis='X', eps=1e-4, keep_side='LEFT', use_median_plane=False):
    """
    Zero out the opposite half of src_key (relative to Basis), by copying Basis coords.
    keep_side: 'LEFT' or 'RIGHT' (negative vs positive side along the X axis).
    If use_median_plane is True, split around the median coordinate of Basis on that axis.
    """
    sk = obj.data.shape_keys
    if not sk or not src_key or src_key == sk.key_blocks[0]:
        return 0

    basis = sk.key_blocks[0]
    kd = src_key.data
    bd = basis.data
    n = len(kd)

    comp_idx = {'X': 0, 'Y': 1, 'Z': 2}.get(axis.upper(), 0)

    if use_median_plane:
        coords = [bd[i].co[comp_idx] for i in range(n)]
        coords.sort()
        mid = len(coords) // 2
        plane = (coords[mid] if (len(coords) % 2 == 1) else 0.5 * (coords[mid - 1] + coords[mid]))
    else:
        plane = 0.0

    changed = 0
    for i in range(n):
        v = bd[i].co[comp_idx] - plane
        if keep_side == 'LEFT':
            kill = (v > eps)
        else:
            kill = (v < -eps)

        if kill:
            kd[i].co = bd[i].co
            changed += 1

    return changed


def get_target_keys(context, *, require_selected=True, visible_only=True,
                    fallback_to_active=True, exclude_basis=True):
    obj = context.object
    if not obj or obj.type != 'MESH':
        return []

    pool = filtered_keys(context, obj) if visible_only else list(iter_keyblocks(obj))
    targets = [k for k in pool if get_sel(k)] if require_selected else list(pool)

    if fallback_to_active and not targets:
        ak = getattr(obj, "active_shape_key", None)
        if ak and ((not exclude_basis) or not is_basis_key(obj, ak)):
            if (not visible_only) or (ak in pool):
                targets = [ak]

    if exclude_basis:
        targets = [k for k in targets if not is_basis_key(context.object, k)]
    return targets


class SKO_OT_CheckUpdates(bpy.types.Operator):
    bl_idname = "shapekey_organizer.check_updates"
    bl_label = "Check for Updates"
    bl_description = "Check GitHub for a newer version of this add-on"
    bl_options = {'INTERNAL'}

    silent_if_latest: bpy.props.BoolProperty(
        name="Silent If Latest",
        description="If enabled, do not show a popup unless a newer version is available",
        default=False,
        options={'SKIP_SAVE'},
    )

    def execute(self, context):
        current_str = current_version_display()
        current_cmp = _parse_version_tag(current_str)
        latest_tag = _fetch_latest_tag()
        latest_cmp = _parse_version_tag(latest_tag)

        if latest_tag == "":
            msg = "Could not determine latest version (GitHub API unavailable)."
            if not self.silent_if_latest:
                self._popup(context, msg, show_open=True)
            return {'CANCELLED'}

        if latest_cmp > current_cmp:
            msg = f"New version available: {latest_tag} (current v{current_str})."
            self._popup(context, msg, show_open=True)
        else:
            msg = f"You are on the latest version (v{current_str})."
            if not self.silent_if_latest:
                self._popup(context, msg, show_open=False)
        return {'FINISHED'}

    def _popup(self, context, message, show_open=True):
        def draw(self, _ctx):
            self.layout.label(text=message)
            if show_open:
                self.layout.operator("wm.url_open", text="Open Releases").url = GITHUB_RELEASES_URL
        context.window_manager.popup_menu(draw, title="Blender Shapekey Add-Ons - Update", icon='INFO')


class SKO_AddonPreferences(AddonPreferences):
    bl_idname = _ADDON_ID

    auto_check: BoolProperty(
        name="Check on Startup",
        description="Check GitHub for updates once after loading a file",
        default=False,
    )

    def draw(self, context):
        col = self.layout.column(align=True)
        row = col.row(align=True)
        row.prop(self, "auto_check")
        row.operator("shapekey_organizer.check_updates", icon='FILE_REFRESH')


def _sko_auto_check(_dummy):
    try:
        entry = bpy.context.preferences.addons.get(_ADDON_ID)
        prefs = getattr(entry, "preferences", None)
        if getattr(prefs, "auto_check", False):
            try:
                bpy.ops.shapekey_organizer.check_updates('INVOKE_DEFAULT', silent_if_latest=True)
            except Exception:
                pass
    finally:
        try:
            bpy.app.handlers.load_post.remove(_sko_auto_check)
        except Exception:
            pass



def _on_find_change(self, context):
    """When the Find field changes, auto-select keys whose names contain it.
    Respects the case sensitivity toggle (default: case-insensitive)."""
    try:
        obj = active_obj_mesh(context)
        if not obj:
            return
        needle = self.find
        if not needle:
            return
        case_sensitive = getattr(self, 'find_case_sensitive', False)
        if not case_sensitive:
            needle_cmp = needle.lower()
        for k in iter_keyblocks(obj):
            hay = k.name if case_sensitive else k.name.lower()
            if (needle if case_sensitive else needle_cmp) in hay:
                set_sel(k, True)
    except Exception:
        pass


def active_obj_mesh(context):
    obj = context.object
    return obj if (obj and obj.type == 'MESH') else None


def iter_keyblocks(obj):
    ks = getattr(getattr(obj.data, 'shape_keys', None), 'key_blocks', None)
    return ks or []


class SKO_Item(PropertyGroup):
    key_name: StringProperty(name="Key Name")
    selected: BoolProperty(name="Selected", description="Selection state for list actions")
    group: StringProperty(name="Group", description="Optional group tag for this shapekey")


class SKO_GroupItem(PropertyGroup):
    name: StringProperty(name="Group Name", description="Custom group tag")


def _state_items():
    scn = bpy.context.scene
    return getattr(scn, 'sko_items', None)


def find_item_by_name(name: str):
    items = _state_items()
    if not items:
        return None
    for it in items:
        if it.key_name == name:
            return it
    return None


def ensure_item_by_name(name: str, create: bool = False):
    """Return state item for name. Only create when create=True (never from draw)."""
    items = _state_items()
    if items is None:
        return None
    it = find_item_by_name(name)
    if it or not create:
        return it
    it = items.add()
    it.key_name = name
    return it


def get_sel(key):
    it = find_item_by_name(key.name)
    return bool(it.selected) if it else False


def set_sel(key, val: bool):
    it = ensure_item_by_name(key.name, create=True)
    if it:
        it.selected = bool(val)


def get_group(key):
    it = find_item_by_name(key.name)
    return it.group if it else ""


def set_group(key, group_name: str):
    it = ensure_item_by_name(key.name, create=True)
    if it:
        it.group = group_name or ""


def all_groups(context):
    return getattr(context.scene, 'sko_groups', [])


def ensure_group(context, name: str):
    name = (name or "").strip()
    if not name:
        return None
    groups = all_groups(context)
    for g in groups:
        if g.name == name:
            return g
    g = groups.add()
    g.name = name
    return g


def filtered_keys(context, obj):
    ks = iter_keyblocks(obj)
    if not ks:
        return []
    props = context.scene.shapekey_organizer
    query = props.search.lower().strip()
    group = props.filter_group.strip()
    out = []
    for k in ks:
        if query and query not in k.name.lower():
            continue
        if group and get_group(k) != group:
            continue
        out.append(k)
    return out


def is_basis_key(obj, key):
    ks = getattr(getattr(obj.data, 'shape_keys', None), 'key_blocks', None)
    return bool(ks) and key == ks[0]


def _ensure_active_not_basis(obj):
    """If active key lands on Basis (index 0), push it down to index 1."""
    try:
        while obj.active_shape_key_index == 0:
            bpy.ops.object.shape_key_move(type='DOWN')
    except Exception:
        pass


def move_active_to_top_below_basis(obj):
    """Move currently active shape key to the top *below Basis* (index 1)."""
    try:
        bpy.ops.object.shape_key_move(type='TOP')
        _ensure_active_not_basis(obj)
    except Exception:
        pass

# =====================================================
# Properties
# =====================================================

class SKO_Props(PropertyGroup):
    search: StringProperty(
        name="Search",
        description="Filter shapekeys whose name contains this text (case-insensitive)",
        default="",
    )
    filter_group: StringProperty(
        name="Group",
        description="Show only keys assigned to this exact group tag",
        default="",
        options={'HIDDEN'}
    )
    anchor_index: IntProperty(
        name="Selection Anchor Index",
        description="Internal: start index for Shift-click range selection",
        default=-1,
        options={'HIDDEN'}
    )
    prefix: StringProperty(
        name="Prefix",
        description="Text to add before each selected key's name",
        default="",
    )
    suffix: StringProperty(
        name="Suffix",
        description="Text to add after each selected key's name",
        default="",
    )
    find: StringProperty(
        name="Find",
        description="Auto-selects keys whose names contain this text; used by Find & Replace",
        default="",
        update=_on_find_change,
    )
    find_case_sensitive: BoolProperty(
        name="Case Sensitive",
        description="Treat Find & Replace as case-sensitive (off = case-insensitive)",
        default=False,
    )
    replace: StringProperty(
        name="Replace",
        description="Replace the 'Find' text with this",
        default="",
    )
    sort_mode: EnumProperty(
        name="Sort",
        description="Sorting mode for selected keys",
        items=[
            ('NAME_ASC', "Name A→Z", "Sort by name ascending"),
            ('NAME_DESC', "Name Z→A", "Sort by name descending"),
            ('GROUP_LIST', "Group List → Name", "Follow custom group list order, then Name A→Z"),
        ],
        default='NAME_ASC'
    )
    auto_number_start: IntProperty(
        name="Start",
        description="Starting number for Auto-Number",
        default=1, min=0
    )
    auto_number_pad: IntProperty(
        name="Pad",
        description="Digits to pad when numbering (e.g., 2 → 01, 3 → 001)",
        default=2, min=1, max=6
    )
    slider_min: FloatProperty(
        name="Slider Min",
        description="Set slider minimum for (visible) selected keys",
        default=0.0,
        min=0.0, max=1.0,
        soft_min=0.0, soft_max=1.0,
    )
    slider_max: FloatProperty(
        name="Slider Max",
        description="Set slider maximum for (visible) selected keys",
        default=1.0,
        min=0.0, max=1.0,
        soft_min=0.0, soft_max=1.0,
    )
    affect_only_selected: BoolProperty(
        name="Only Selected",
        description="If enabled, actions only affect keys with the checkbox enabled. If off, actions affect all visible keys",
        default=True
    )
    group_search: StringProperty(
        name="Group",
        description="Group name to add/select/filter",
        default="",
    )
    group_active_index: IntProperty(
        name="Active Group Index",
        default=-1,
        options={'HIDDEN'}
    )

    # UI foldouts
    show_groups: BoolProperty(name="Show Groups", default=False)
    show_rename: BoolProperty(name="Show Rename", default=False)
    show_batch: BoolProperty(name="Show Batch Edits", default=False)

# =====================================================
# UI List
# =====================================================

class SKO_UL_ShapeKeys(UIList):
    bl_idname = "SKO_UL_shapekeys"

    def draw_filter(self, context, layout):
        pass

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        key = item
        if not key:
            return
        sel = get_sel(key)

        obj = context.object
        is_active = (getattr(obj, "active_shape_key_index", -1) == index)
        sel = get_sel(key)
        gname = get_group(key)

        split = layout.split(factor=0.5)
        left  = split.row(align=True)
        right = split.row(align=True)

        if is_active:
            left.active = True
            right.active = True

        left_split = left.split(factor=0.75)
        name_row = left_split.row(align=True)
        name_row.alignment = 'LEFT'
        btn = name_row.operator("shapekey_organizer.key_click", text=key.name, emboss=False)
        btn.key_name = key.name
        btn.key_index = index

        group_cell = left_split.row(align=True)
        group_cell.alignment = 'RIGHT'
        if gname:
            group_cell.label(text=gname, icon='OUTLINER_COLLECTION')
        else:
            group_cell.separator()

        right.prop(key, 'value', text="")
        right.prop(key, 'mute', text="", icon_only=True, icon='HIDE_OFF')
        op = right.operator(
            "shapekey_organizer.toggle_select",
            text="",
            icon='CHECKBOX_HLT' if sel else 'CHECKBOX_DEHLT',
            depress=sel
        )
        op.key_name = key.name

    def filter_items(self, context, data, propname):
        try:
            ks = getattr(data, propname)
        except Exception:
            ks = []
        props = getattr(context.scene, 'shapekey_organizer', None)
        query = (props.search.lower().strip() if props else "")
        group = (props.filter_group.strip() if props else "")

        flt_flags = []
        for k in ks:
            show = True
            if query and query not in k.name.lower():
                show = False
            if show and group and get_group(k) != group:
                show = False
            flt_flags.append(self.bitflag_filter_item if show else 0)
        return flt_flags, list(range(len(flt_flags)))



class SKO_UL_Groups(UIList):
    bl_idname = "SKO_UL_groups"

    def draw_filter(self, context, layout):
        pass

    def filter_items(self, context, data, propname):
        self.use_filter_show = False
        self.use_filter_invert = False
        self.use_filter_sort_alpha = False
        self.use_filter_sort_reverse = False

        try:
            items = getattr(data, propname)
        except Exception:
            items = []
        flags = [self.bitflag_filter_item] * len(items)
        return flags, list(range(len(items)))

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if not item:
            return
        row = layout.row(align=True)
        row.label(text=item.name)

# =====================================================
# Operators
# =====================================================

class SKO_OT_ToggleUseEditMode(bpy.types.Operator):
    bl_idname = "shapekey_organizer.toggle_use_edit_mode"
    bl_label = "Shape Key Edit Mode"
    bl_description = "Display shape keys in edit mode (for meshes only)."
    bl_options = {'INTERNAL', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj: return {'CANCELLED'}
        obj.use_shape_key_edit_mode = not obj.use_shape_key_edit_mode
        return {'FINISHED'}


class SKO_OT_ToggleShowOnly(bpy.types.Operator):
    bl_idname = "shapekey_organizer.toggle_show_only"
    bl_label = "Solo Active Shape Key"
    bl_description = "Only show the active shapekey at full value."
    bl_options = {'INTERNAL', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj: return {'CANCELLED'}
        obj.show_only_shape_key = not obj.show_only_shape_key
        return {'FINISHED'}


class SKO_OT_KeyActivateOrRename(Operator):
    bl_idname = "shapekey_organizer.key_click"
    bl_label = "Rename Shapekey"
    bl_description = "Single-click: set active. Quick second click: rename."
    bl_options = {'REGISTER', 'UNDO'}

    key_name: StringProperty(options={'SKIP_SAVE'})
    key_index: IntProperty(default=-1, options={'SKIP_SAVE'})
    new_name: StringProperty(name="New Name", default="", options={'SKIP_SAVE'})

    def invoke(self, context, event):
        obj = active_obj_mesh(context)
        if not obj:
            return {'CANCELLED'}

        now = time.perf_counter()
        if _DBL_CLICK["name"] == self.key_name and (now - _DBL_CLICK["t"]) <= _DBL_THRESHOLD:
            _DBL_CLICK["name"] = ""
            self.new_name = self.key_name
            return context.window_manager.invoke_props_dialog(self, width=260)

        idx = self.key_index
        if idx < 0:
            ks = getattr(getattr(obj.data, 'shape_keys', None), 'key_blocks', None) or []
            for i, kb in enumerate(ks):
                if kb.name == self.key_name:
                    idx = i
                    break
        if idx >= 0:
            obj.active_shape_key_index = idx

        _DBL_CLICK["name"] = self.key_name
        _DBL_CLICK["t"] = now
        try:
            for win in bpy.context.window_manager.windows:
                for area in win.screen.areas:
                    if area.type == 'PROPERTIES':
                        area.tag_redraw()
        except Exception:
            pass

        return {'FINISHED'}

    def draw(self, context):
        self.layout.prop(self, "new_name", text="")

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            return {'CANCELLED'}
        ks = getattr(getattr(obj.data, 'shape_keys', None), 'key_blocks', None)
        if not ks:
            return {'CANCELLED'}

        kb = ks.get(self.key_name)
        if not kb:
            return {'CANCELLED'}

        new = self.new_name.strip()
        if new and new != kb.name:
            it = ensure_item_by_name(kb.name, create=True)
            kb.name = new
            if it:
                it.key_name = new
        return {'FINISHED'}


class SKO_OT_ShapeKeyAdd(Operator):
    bl_idname = "shapekey_organizer.shape_key_add"
    bl_label = "Create Shapekey"
    bl_description = "Create a new shapekey (empty, from full mix, or from selected-only mix)"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Mode",
        description="How to create the new shapekey",
        items=[
            ('EMPTY',       "New (Empty)",              "Create an empty shapekey"),
            ('MIX_ALL',     "From Mix (All Visible)",   "Bake all currently visible deformation"),
            ('MIX_SELECTED',"From Mix (Selected Only)", "Bake only selected shapekeys (optionally only visible)"),
            ('DUP_SELECTED',"Duplicate",                "Make a copy of each selected shapekey (ignores Basis)"),
            ('DUP_MIRROR',  "Duplicate & Mirror",       "Duplicate each selected and mirror it"),
            ('SPLIT',       "Duplicate & Split",        "Duplicate each selected and zero each half by axis"),
        ],
        default='EMPTY'
    )

    key_name: StringProperty(
        name = "Name",
        description="Optional name; if duplicating multiple keys, this will be used as a prefix",
        default="",
        options={'SKIP_SAVE'}
    )

    # Only used when mode == MIX_SELECTED
    visible_only: BoolProperty(
        name="Only Visible (Filtered)",
        description="Limit to keys that are visible in the list (respects Search/Group filter)",
        default=False
    )
    include_zero: BoolProperty(
        name="Include Zero Values",
        description="Include selected keys even if their current value is 0.0",
        default=False
    )

    # Only used when mode == DUP_SELECTED
    duplicate_suffix: bpy.props.StringProperty(
        name="Suffix",
        description="Suffix for duplicated names (when no explicit name is given)",
        default="",
        options={'SKIP_SAVE'},
    )

    # Only used when mode == DUP_MIRROR
    use_topology: bpy.props.BoolProperty(
        name="Use Topology",
        description="Use topology mapping when mirroring (safer on asymmetric meshes)",
        default=False,
        options={'SKIP_SAVE'},
    )

    # Only used when mode == SPLIT
    split_eps: bpy.props.FloatProperty(
        name="Threshold",
        description="Vertices within this distance of the split plane are kept (prevents tiny holes)",
        default=0.0001, min=0.0, soft_max=0.01
    )

    split_left_token: bpy.props.StringProperty(
        name="Left token",
        description="Text appended for the left-half key",
        default=""
    )
    split_right_token: bpy.props.StringProperty(
        name="Right token",
        description="Text appended for the right-half key",
        default=""
    )

    keep_original: bpy.props.BoolProperty(
        name="Keep Original",
        description="Keep the original shapekey after creating left/right halves",
        default=True,
        options={'SKIP_SAVE'},
    )

    use_median_plane: bpy.props.BoolProperty(
        name="Use Median Plane",
        description="Split relative to the mesh’s median on the axis (robust if the model isn’t centered on 0)",
        default=False,
        options={'SKIP_SAVE'},
    )


    def invoke(self, context, event):
        self.key_name = ""
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "mode", text="")

        col = layout.column(align=True)
        if self.mode != 'SPLIT':
            name_label = "Prefix" if self.mode in {'DUP_SELECTED', 'DUP_MIRROR'} else "Name"
            col.prop(self, "key_name", text=name_label)

        if self.mode == 'MIX_SELECTED':
            box = layout.box()
            box.label(text="From Selected Options")
            row = box.row(align=False)
            row.prop(self, "visible_only")
            row.prop(self, "include_zero")

        elif self.mode == 'DUP_SELECTED':
            col.prop(self, "duplicate_suffix")
            box = layout.box()
            box.label(text="Tip: If Prefix and Suffix are empty,")
            box.label(text="Duplicates are suffixed with .001, .002, etc.")

        elif self.mode == 'DUP_MIRROR':
            col.prop(self, "duplicate_suffix", text="Suffix")
            col.prop(self, "use_topology", text="Use Topology")
            box = layout.box()
            box.label(text="Tip: If Prefix and Suffix are empty,")
            box.label(text="Duplicates are suffixed with \"_Mirror\"")

        elif self.mode == 'SPLIT':
            col.prop(self, "split_left_token", text="Left Suffix")
            col.prop(self, "split_right_token", text="Right Suffix")

            row = layout.row(align=True)
            row.prop(self, "split_eps")

            row =  layout.row(align=True)
            row.prop(self, "keep_original")
            row.prop(self, "use_median_plane")
            box = layout.box()
            box.label(text="Tip: If Left and/or Right token are empty,")
            box.label(text="Duplicates are suffixed with \"_L\" and \"_R\"")

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}

        props = context.scene.shapekey_organizer

        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass

        def _finalize_new_key():
            ks = getattr(getattr(obj.data, 'shape_keys', None), 'key_blocks', None)
            if not ks:
                return None
            new_key = ks[-1]
            if self.key_name.strip():
                new_key.name = self.key_name.strip()
            obj.active_shape_key_index = len(ks) - 1
            it = ensure_item_by_name(new_key.name, create=True)
            if it:
                it.selected = True
            try:
                bpy.context.view_layer.update()
                for win in bpy.context.window_manager.windows:
                    for area in win.screen.areas:
                        if area.type in {'PROPERTIES', 'VIEW_3D'}:
                            area.tag_redraw()
            except Exception:
                pass
            return new_key

        if self.mode == 'EMPTY':
            try:
                bpy.ops.object.shape_key_add(from_mix=False)
            except Exception as e:
                self.report({'ERROR'}, f"Could not create shapekey: {e}")
                return {'CANCELLED'}
            new_key = _finalize_new_key()
            self.report({'INFO'}, f"Created shapekey: {new_key.name if new_key else '(unknown)'}")
            self.key_name = ""
            return {'FINISHED'}

        if self.mode == 'MIX_ALL':
            try:
                bpy.ops.object.shape_key_add(from_mix=True)
            except Exception as e:
                self.report({'ERROR'}, f"Could not create shapekey from mix: {e}")
                return {'CANCELLED'}
            new_key = _finalize_new_key()
            self.report({'INFO'}, f"Captured full mix to: {new_key.name if new_key else '(unknown)'}")
            self.key_name = ""
            return {'FINISHED'}

        if self.mode == 'DUP_SELECTED':
            obj = active_obj_mesh(context)
            if not obj:
                self.report({'WARNING'}, "Select a mesh object with shapekeys.")
                return {'CANCELLED'}

            ks = list(iter_keyblocks(obj))
            if not ks:
                self.report({'WARNING'}, "No shapekeys to duplicate.")
                return {'CANCELLED'}

            targets = get_target_keys(context,
                                      require_selected=props.affect_only_selected,
                                      visible_only=True,
                                      fallback_to_active=True,
                                      exclude_basis=True)
            if not targets:
                self.report({'INFO'}, "No selected shapekeys to duplicate.")
                return {'CANCELLED'}

            values_cache = {k.name: float(getattr(k, "value", 0.0)) for k in ks}

            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass

            created = 0
            last_new_name = ""

            multi = (len(targets) > 1)
            name_prefix = self.key_name.strip()
            suffix = self.duplicate_suffix

            for src in targets:
                for k in ks:
                    try:
                        k.value = 0.0
                    except Exception:
                        pass
                try:
                    src.value = 1.0
                except Exception:
                    pass

                try:
                    bpy.ops.object.shape_key_add(from_mix=True)
                except Exception as e:
                    for k in ks:
                        try:
                            k.value = values_cache.get(k.name, 0.0)
                        except Exception:
                            pass
                    self.report({'ERROR'}, f"Duplicate failed on '{src.name}': {e}")
                    return {'CANCELLED'}

                new_key = obj.data.shape_keys.key_blocks[-1]

                if multi:
                    new_key.name = f"{name_prefix}{src.name}{suffix}"
                else:
                    base_name = name_prefix if name_prefix and not multi else src.name
                    if name_prefix and not multi:
                        new_key.name = f"{name_prefix}{suffix}"
                    else:
                        new_key.name = f"{name_prefix}{src.name}{suffix}"


                try:
                    new_key.slider_min = float(getattr(src, "slider_min", 0.0))
                    new_key.slider_max = float(getattr(src, "slider_max", 1.0))
                except Exception:
                    pass

                obj.active_shape_key_index = len(obj.data.shape_keys.key_blocks) - 1
                it = ensure_item_by_name(new_key.name, create=True)
                if it:
                    it.selected = True

                last_new_name = new_key.name
                created += 1

                for k in ks:
                    try:
                        k.value = values_cache.get(k.name, 0.0)
                    except Exception:
                        pass

            try:
                bpy.context.view_layer.update()
                for win in bpy.context.window_manager.windows:
                    for area in win.screen.areas:
                        if area.type in {'PROPERTIES', 'VIEW_3D'}:
                            area.tag_redraw()
            except Exception:
                pass

            self.key_name = ""

            self.report({'INFO'}, f"Duplicated {created} shapekey(s).")
            return {'FINISHED'}

        if self.mode == 'DUP_MIRROR':
            obj = active_obj_mesh(context)
            if not obj:
                self.report({'WARNING'}, "Select a mesh object with shapekeys.")
                return {'CANCELLED'}

            ks = list(iter_keyblocks(obj))
            if not ks:
                self.report({'WARNING'}, "No shapekeys to mirror.")
                return {'CANCELLED'}

            targets = get_target_keys(context,
                                      require_selected=props.affect_only_selected,
                                      visible_only=True,
                                      fallback_to_active=True,
                                      exclude_basis=True)
            if not targets:
                self.report({'INFO'}, "No selected shapekeys to mirror.")
                return {'CANCELLED'}

            values_cache = {k.name: float(getattr(k, "value", 0.0)) for k in ks}

            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass

            created = 0
            prefix = (self.key_name or "").strip()
            suffix = self.duplicate_suffix

            for src in targets:
                for k in ks:
                    try: k.value = 0.0
                    except: pass
                try:
                    src.value = 1.0
                except: pass

                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.ops.object.shape_key_add(from_mix=True)

                new_idx = len(obj.data.shape_keys.key_blocks) - 1
                obj.active_shape_key_index = new_idx
                new_k = obj.data.shape_keys.key_blocks[new_idx]

                for k in ks:
                    try: k.value = 0.0
                    except: pass

                try:
                    bpy.ops.object.shape_key_mirror(use_topology=self.use_topology)
                except Exception as e:
                    self.report({'WARNING'}, f"Mirror failed on '{new_k.name}': {e}")

                prefix = (self.key_name or "").strip()
                suffix = self.duplicate_suffix
                if not prefix and not suffix:
                    suffix = "_Mirror"
                new_k.name = f"{prefix}{src.name}{suffix}"
                it = ensure_item_by_name(new_k.name, create=True)
                if it: it.selected = True
                created += 1

                try:
                    new_k.slider_min = float(getattr(src, "slider_min", 0.0))
                    new_k.slider_max = float(getattr(src, "slider_max", 1.0))
                except:
                    pass

                for k in ks:
                    try: k.value = values_cache.get(k.name, 0.0)
                    except: pass

            try:
                bpy.context.view_layer.update()
                for win in bpy.context.window_manager.windows:
                    for area in win.screen.areas:
                        if area.type in {'PROPERTIES', 'VIEW_3D'}:
                            area.tag_redraw()
            except Exception:
                pass

            self.key_name = ""
            self.report({'INFO'}, f"Duplicated & mirrored {created} shapekey(s).")
            return {'FINISHED'}

        elif self.mode == 'SPLIT':
            obj = active_obj_mesh(context)
            if not obj:
                self.report({'WARNING'}, "Select a mesh object with shapekeys.")
                return {'CANCELLED'}

            ks = list(iter_keyblocks(obj))
            if not ks:
                self.report({'WARNING'}, "Object has no shapekeys to split.")
                return {'CANCELLED'}

            targets = get_target_keys(context,
                                      require_selected=props.affect_only_selected,
                                      visible_only=True,
                                      fallback_to_active=True,
                                      exclude_basis=True)
            if not targets:
                self.report({'WARNING'}, "Select one or more shapekeys (non-Basis) or set an active shapekey.")
                return {'CANCELLED'}

            values_cache = {k.name: float(getattr(k, "value", 0.0)) for k in ks}

            left_tok  = (self.split_left_token  or "").strip() or "_L"
            right_tok = (self.split_right_token or "").strip() or "_R"

            created = 0
            try:
                try:
                    bpy.ops.object.mode_set(mode='OBJECT')
                except Exception:
                    pass

                for src in targets:
                    for k in ks:
                        try: k.value = 0.0
                        except Exception: pass
                    try:
                        src.value = 1.0
                    except Exception:
                        pass

                    bpy.ops.object.shape_key_add(from_mix=True)
                    k_left = obj.data.shape_keys.key_blocks[-1]
                    obj.active_shape_key_index = len(obj.data.shape_keys.key_blocks) - 1

                    try:
                        k_left.value = 0.0
                    except Exception:
                        pass

                    bpy.ops.object.shape_key_add(from_mix=True)
                    k_right = obj.data.shape_keys.key_blocks[-1]
                    obj.active_shape_key_index = len(obj.data.shape_keys.key_blocks) - 1

                    k_left.name  = f"{src.name}{left_tok}"
                    k_right.name = f"{src.name}{right_tok}"

                    try:
                        for nk in (k_left, k_right):
                            nk.slider_min = float(getattr(src, "slider_min", 0.0))
                            nk.slider_max = float(getattr(src, "slider_max", 1.0))
                    except Exception:
                        pass

                    for k in iter_keyblocks(obj):
                        try: k.value = 0.0
                        except Exception: pass

                    changed_L = _sko_split_keyblock_half(
                        obj, k_left,
                        axis="X",
                        eps=max(0.0, self.split_eps),
                        keep_side='LEFT',
                        use_median_plane=self.use_median_plane
                    )
                    changed_R = _sko_split_keyblock_half(
                        obj, k_right,
                        axis="X",
                        eps=max(0.0, self.split_eps),
                        keep_side='RIGHT',
                        use_median_plane=self.use_median_plane
                    )

                    if changed_L == 0 or changed_R == 0:
                        self.report(
                            {'WARNING'},
                            f"Split '{src.name}' affected L:{changed_L} / R:{changed_R} vertices. "
                            f"Check threshold or the model’s symmetry vs X=0."
                        )

                    it = ensure_item_by_name(k_left.name,  create=True);  setattr(it, "selected", True)  if it else None
                    it = ensure_item_by_name(k_right.name, create=True);  setattr(it, "selected", True) if it else None

                    created += 2

                    if not self.keep_original:
                        try:
                            idx = list(obj.data.shape_keys.key_blocks).index(src)
                            obj.active_shape_key_index = idx
                            bpy.ops.object.shape_key_remove(all=False)
                        except Exception:
                            self.report({'WARNING'}, f"Could not remove original key '{src.name}'.")

                self.report({'INFO'}, f"Split {len(targets)} key(s) → created {created}.")
                return {'FINISHED'}

            finally:
                sk = getattr(getattr(obj.data, 'shape_keys', None), 'key_blocks', None)
                if sk:
                    for kb in sk:
                        try:
                            kb.value = float(values_cache.get(kb.name, 0.0))
                        except Exception:
                            pass
                try:
                    bpy.context.view_layer.update()
                    for win in bpy.context.window_manager.windows:
                        for area in win.screen.areas:
                            if area.type in {'PROPERTIES', 'VIEW_3D'}:
                                area.tag_redraw()
                except Exception:
                    pass

        # MIX_SELECTED
        ks = list(iter_keyblocks(obj))
        if not ks:
            self.report({'WARNING'}, "No shapekeys to combine.")
            return {'CANCELLED'}

        pool = filtered_keys(context, obj) if self.visible_only else ks

        values_cache = {k.name: float(getattr(k, "value", 0.0)) for k in ks}

        include = []
        for k in pool:
            if is_basis_key(obj, k):
                continue
            if not get_sel(k):
                continue
            if not self.include_zero and values_cache.get(k.name, 0.0) == 0.0:
                continue
            include.append(k)

        if not include:
            self.report({'INFO'}, "No selected (and eligible) shapekeys to combine.")
            return {'CANCELLED'}

        for k in ks:
            try:
                k.value = 0.0
            except Exception:
                pass

        for k in include:
            try:
                k.value = values_cache.get(k.name, 0.0)
            except Exception:
                pass

        try:
            bpy.ops.object.shape_key_add(from_mix=True)
        except Exception as e:
            for k in ks:
                try:
                    k.value = values_cache.get(k.name, 0.0)
                except Exception:
                    pass
            self.report({'ERROR'}, f"Could not create shapekey from selected mix: {e}")
            return {'CANCELLED'}

        new_key = _finalize_new_key()

        for k in ks:
            try:
                k.value = values_cache.get(k.name, 0.0)
            except Exception:
                pass

        self.report({'INFO'}, f"Created '{new_key.name if new_key else '(unknown)'}' from {len(include)} selected key(s).")
        self.key_name = ""
        return {'FINISHED'}

class SKO_OT_ShapeKeyDelete(bpy.types.Operator):
    bl_idname = "shapekey_organizer.shape_key_delete"
    bl_label = "Delete Shapekeys"
    bl_description = "Delete selected shapekeys; if none are selected, delete the active shapekey"
    bl_options = {'REGISTER', 'UNDO'}

    _target_names: list[str] = None
    _used_fallback: bool = False

    def _gather_targets(self, context):
        """Build target list and detect if we fell back to the active key."""
        obj = context.object
        if not obj or obj.type != 'MESH':
            return [], False

        pool = filtered_keys(context, obj)
        any_selected = any(get_sel(k) and not is_basis_key(obj, k) for k in pool)

        targets = get_target_keys(context,
                                  require_selected=True,
                                  visible_only=True,
                                  fallback_to_active=True,
                                  exclude_basis=True
        )
        names = [k.name for k in targets]
        used_fallback = (not any_selected) and (len(names) == 1)

        return names, used_fallback

    def invoke(self, context, event):
        names, used_fallback = self._gather_targets(context)
        if not names:
            self.report({'INFO'}, "No shapekeys to delete.")
            return {'CANCELLED'}

        self._target_names = names
        self._used_fallback = used_fallback
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        layout = self.layout
        names = self._target_names or []

        if self._used_fallback and len(names) == 1:
            layout.label(text="Delete active shapekey?", icon='INFO')
            layout.label(text=names[0], icon='SHAPEKEY_DATA')
        else:
            layout.label(text=f"Delete {len(names)} shapekey(s)?", icon='INFO')
            for n in names[:6]:
                layout.label(text=n, icon='DOT')
            if len(names) > 6:
                layout.label(text="…")

    def execute(self, context):
        obj = context.object
        sk = getattr(getattr(obj.data, 'shape_keys', None), 'key_blocks', None)
        if not obj or not sk:
            return {'CANCELLED'}

        names = self._target_names
        if not names:
            names, _ = self._gather_targets(context)
            if not names:
                self.report({'INFO'}, "No shapekeys to delete.")
                return {'CANCELLED'}

        indices = []
        for n in names:
            kb = sk.get(n)
            if kb:
                idx = list(sk).index(kb)
                if idx > 0:
                    indices.append(idx)

        indices.sort(reverse=True)
        for idx in indices:
            obj.active_shape_key_index = idx
            try:
                bpy.ops.object.shape_key_remove(all=False)
            except Exception:
                pass

        self.report({'INFO'}, f"Deleted {len(indices)} shapekey(s).")
        return {'FINISHED'}


class SKO_OT_ToggleSelect(Operator):
    bl_idname = "shapekey_organizer.toggle_select"
    bl_label = "Toggle Select"
    bl_description = "Click to toggle; Shift-click to select a range between the anchor and this item"
    bl_options = {'INTERNAL', 'UNDO'}

    key_name: StringProperty(name="Key Name")
    range_mode: BoolProperty(options={'HIDDEN'}, default=False)

    def invoke(self, context, event):
        self.range_mode = bool(getattr(event, "shift", False))
        return self.execute(context)

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}

        ks = getattr(getattr(obj.data, 'shape_keys', None), 'key_blocks', None)
        if not ks:
            return {'CANCELLED'}

        props = context.scene.shapekey_organizer

        idx_of = {k.name: i for i, k in enumerate(ks)}
        if self.key_name not in idx_of:
            return {'CANCELLED'}
        current_idx = idx_of[self.key_name]

        visible_names = [k.name for k in filtered_keys(context, obj)]
        visible_set = {idx_of[n] for n in visible_names if n in idx_of}

        if self.range_mode and props.anchor_index >= 0 and props.anchor_index in visible_set and current_idx in visible_set:
            a, b = sorted((props.anchor_index, current_idx))
            for i in range(a, b + 1):
                if i in visible_set:
                    set_sel(ks[i], True)
        else:
            set_sel(ks[current_idx], not get_sel(ks[current_idx]))

        props.anchor_index = current_idx
        return {'FINISHED'}


class SKO_OT_SyncState(Operator):
    bl_idname = "shapekey_organizer.sync_state"
    bl_label = "Refresh"
    bl_description = "Scan current object and create state entries for all shapekeys (safe)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}
        created = 0
        for k in iter_keyblocks(obj):
            if not find_item_by_name(k.name):
                it = ensure_item_by_name(k.name, create=True)
                if it:
                    created += 1
        self.report({'INFO'}, f"State synced for {created} keys.")
        return {'FINISHED'}


class SKO_OT_SelectAll(Operator):
    bl_idname = "shapekey_organizer.select_all"
    bl_label = "All"
    bl_description = "Select all currently visible (filtered) shapekeys (ignores Basis)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}
        for k in filtered_keys(context, obj):
            if is_basis_key(obj, k):
                continue
            set_sel(k, True)
        return {'FINISHED'}


class SKO_OT_SelectNone(Operator):
    bl_idname = "shapekey_organizer.select_none"
    bl_label = "None"
    bl_description = "Clear selection for all currently visible (filtered) shapekeys"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}
        for k in filtered_keys(context, obj):
            set_sel(k, False)
        return {'FINISHED'}


class SKO_OT_SelectInvert(Operator):
    bl_idname = "shapekey_organizer.select_invert"
    bl_label = "Invert"
    bl_description = "Invert selection for all currently visible (filtered) shapekeys (ignores Basis)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}
        for k in filtered_keys(context, obj):
            if is_basis_key(obj, k):
                continue
            set_sel(k, not get_sel(k))
        return {'FINISHED'}


class SKO_OT_AssignGroup(Operator):
    bl_idname = "shapekey_organizer.assign_group"
    bl_label = "Assign Group"
    bl_description = "Assign the current Group field value to selected shapekeys"
    bl_options = {'REGISTER', 'UNDO'}

    group: StringProperty(name="Group", description="Group name to assign to selected keys")

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}

        props = context.scene.shapekey_organizer

        gname = (self.group or "").strip() or (props.group_search or "").strip()
        if not gname:
            self.report({'WARNING'}, "Enter a group name first.")
            return {'CANCELLED'}

        all_keys = list(iter_keyblocks(obj))
        selected_targets = [k for k in all_keys if get_sel(k) and not is_basis_key(obj, k)]

        if not selected_targets:
            ak = getattr(obj, "active_shape_key", None)
            if ak and not is_basis_key(obj, ak):
                targets = [ak]
            else:
                targets = []
        else:
            targets = selected_targets

        if not targets:
            self.report({'INFO'}, "No shapekeys to assign (Basis is ignored).")
            return {'CANCELLED'}

        for k in targets:
            set_group(k, gname)

        ensure_group(context, gname)

        try:
            bpy.context.view_layer.update()
            for win in bpy.context.window_manager.windows:
                for area in win.screen.areas:
                    if area.type in {'PROPERTIES', 'VIEW_3D'}:
                        area.tag_redraw()
        except Exception:
            pass

        self.report({'INFO'}, f"Assigned group '{gname}' to {len(targets)} key(s).")
        return {'FINISHED'}


class SKO_OT_ClearGroup(Operator):
    bl_idname = "shapekey_organizer.clear_group"
    bl_label = "Clear Group"
    bl_description = "Clear the group tag from selected shapekeys"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}
        count = 0
        for k in iter_keyblocks(obj):
            if get_sel(k):
                set_group(k, "")
                count += 1
        self.report({'INFO'}, f"Cleared group on {count} keys.")
        return {'FINISHED'}


class SKO_OT_PrefixSuffix(Operator):
    bl_idname = "shapekey_organizer.add_prefix_suffix"
    bl_label = "Apply Prefix/Suffix"
    bl_description = "Add prefix and/or suffix to each affected shapekey name"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}

        props = context.scene.shapekey_organizer
        pre, suf = props.prefix, props.suffix
        if not pre and not suf:
            self.report({'WARNING'}, "Nothing to add (enter a prefix and/or suffix).")
            return {'CANCELLED'}

        targets = get_target_keys(context,
                                  require_selected=props.affect_only_selected,
                                  visible_only=True,
                                  fallback_to_active=True,
                                  exclude_basis=True
        )
        if not targets:
            self.report({'INFO'}, "No shapekeys to rename.")
            return {'CANCELLED'}

        count = 0
        for k in targets:
            it = ensure_item_by_name(k.name, create=True)
            new_name = f"{pre}{k.name}{suf}"
            k.name = new_name
            if it:
                it.key_name = new_name
            count += 1

        self.report({'INFO'}, f"Renamed {count} key(s).")
        return {'FINISHED'}


class SKO_OT_FindReplace(Operator):
    bl_idname = "shapekey_organizer.find_replace"
    bl_label = "Find & Replace"
    bl_description = "Find text in names and replace it for each affected shapekey (case-insensitive by default)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}
        props = context.scene.shapekey_organizer
        find = props.find
        repl = props.replace
        if not find:
            self.report({'WARNING'}, "Enter text to find.")
            return {'CANCELLED'}

        case_sensitive = props.find_case_sensitive
        count = 0
        if case_sensitive:
            for k in iter_keyblocks(obj):
                if props.affect_only_selected and not get_sel(k):
                    continue
                if find in k.name:
                    it = ensure_item_by_name(k.name, create=True)
                    new_name = k.name.replace(find, repl)
                    k.name = new_name
                    it.key_name = new_name
                    count += 1
        else:
            pattern = re.compile(re.escape(find), re.IGNORECASE)
            for k in iter_keyblocks(obj):
                if props.affect_only_selected and not get_sel(k):
                    continue
                if pattern.search(k.name):
                    it = ensure_item_by_name(k.name, create=True)
                    new_name = pattern.sub(repl, k.name)
                    k.name = new_name
                    it.key_name = new_name
                    count += 1

        self.report({'INFO'}, f"Renamed {count} keys.")
        return {'FINISHED'}


class SKO_OT_AutoNumber(Operator):
    bl_idname = "shapekey_organizer.auto_number"
    bl_label = "Auto-Number"
    bl_description = "Append an increasing number to each affected shapekey name"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}
        props = context.scene.shapekey_organizer
        i = props.auto_number_start
        pad = props.auto_number_pad
        count = 0
        for k in iter_keyblocks(obj):
            if props.affect_only_selected and not get_sel(k):
                continue
            it = ensure_item_by_name(k.name, create=True)
            new_name = f"{k.name} {str(i).zfill(pad)}"
            k.name = new_name
            it.key_name = new_name
            i += 1
            count += 1
        self.report({'INFO'}, f"Auto-numbered {count} keys.")
        return {'FINISHED'}


class SKO_OT_Sort(Operator):
    bl_idname = "shapekey_organizer.sort"
    bl_label = "Sort Selected"
    bl_description = ("Sort visible keys (or only selected if enabled). "
                      "Modes: A→Z (All), Z→A (All), or Group List → Name (ungrouped last). "
                      "Basis stays at the top.")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}

        ks = getattr(getattr(obj.data, 'shape_keys', None), 'key_blocks', None)
        if not ks:
            self.report({'INFO'}, "No shapekeys found.")
            return {'CANCELLED'}

        props = context.scene.shapekey_organizer

        visible = filtered_keys(context, obj)

        targets = [k for k in visible if get_sel(k)] if props.affect_only_selected else list(visible)
        if not targets:
            self.report({'INFO'}, "Nothing to sort (check filters/selection).")
            return {'CANCELLED'}

        mode = props.sort_mode

        if mode in {'NAME_ASC', 'NAME_DESC'}:
            reverse = (mode == 'NAME_DESC')
            ordered = sorted(targets, key=lambda k: k.name.lower(), reverse=reverse)
            order_name = "Name A→Z" if not reverse else "Name Z→A"
        else:
            glist = [g.name for g in all_groups(context)]
            gprio = {name: i for i, name in enumerate(glist)}

            def sort_key(k):
                gname = get_group(k)
                gindex = gprio.get(gname, 999999)  # ungrouped last
                return (gindex, k.name.lower())

            ordered = sorted(targets, key=sort_key)
            order_name = "Group List → Name"

        def index_of(name: str) -> int:
            for i, kb in enumerate(obj.data.shape_keys.key_blocks):
                if kb.name == name:
                    return i
            return -1

        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass

        for k in reversed(ordered):
            i = index_of(k.name)
            if i < 0:
                continue
            obj.active_shape_key_index = i
            bpy.ops.object.shape_key_move(type='TOP')
            while obj.active_shape_key_index == 0:
                bpy.ops.object.shape_key_move(type='DOWN')

        self.report({'INFO'}, f"Sorted {len(ordered)} keys: {order_name}.")
        return {'FINISHED'}



class SKO_OT_MoveSelected(Operator):
    bl_idname = "shapekey_organizer.move_selected"
    bl_label = "Move Selected"
    bl_description = "Move selected keys within the stack. 'Top' always means just under Basis"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(
        name="Direction",
        description="Where to move the selected keys",
        items=[('TOP', 'Top', ''), ('UP', 'Up', ''), ('DOWN', 'Down', ''), ('BOTTOM', 'Bottom', '')],
        default='TOP'
    )

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}
        targets = get_target_keys(context,
                                  require_selected=True,
                                  visible_only=True,
                                  fallback_to_active=True,
                                  exclude_basis=True)
        if not targets:
            self.report({'INFO'}, "No keys to move.")
            return {'CANCELLED'}

        ks = list(iter_keyblocks(obj))
        name_to_idx = {k.name: i for i, k in enumerate(ks)}
        idxs = [name_to_idx[k.name] for k in targets if k.name in name_to_idx]

        if self.direction in {'TOP', 'UP'}:
            order = sorted(idxs)
        else:
            order = sorted(idxs, reverse=True)

        for i in order:
            obj.active_shape_key_index = i
            if self.direction == 'TOP':
                move_active_to_top_below_basis(obj)
            else:
                bpy.ops.object.shape_key_move(type=self.direction)
                if self.direction == 'UP':
                    _ensure_active_not_basis(obj)
        self.report({'INFO'}, f"Moved {len(order)} keys {self.direction.lower()}.")
        return {'FINISHED'}


class SKO_OT_ToggleMute(Operator):
    bl_idname = "shapekey_organizer.toggle_mute"
    bl_label = "Mute/Unmute"
    bl_description = "Mute, unmute, or toggle mute state on selected (or visible) keys"
    bl_options = {'REGISTER', 'UNDO'}

    state: EnumProperty(
        name="State",
        description="How to change the mute flag",
        items=[('ON','On','Mute selected keys'),('OFF','Off','Unmute selected keys'),('TOGGLE','Toggle','Toggle the mute flag')],
        default='TOGGLE')

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}
        count = 0
        for k in iter_keyblocks(obj):
            if not get_sel(k):
                continue
            if self.state == 'TOGGLE':
                k.mute = not k.mute
            elif self.state == 'ON':
                k.mute = True
            else:
                k.mute = False
            count += 1
        self.report({'INFO'}, f"Updated mute on {count} keys.")
        return {'FINISHED'}


class SKO_OT_SetSliderRange(Operator):
    bl_idname = "shapekey_organizer.set_slider_range"
    bl_label = "Set Slider Range"
    bl_description = "Apply slider min/max to affected shapekeys"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}
        props = context.scene.shapekey_organizer

        min_v = max(0.0, min(1.0, float(props.slider_min)))
        max_v = max(0.0, min(1.0, float(props.slider_max)))

        if min_v > max_v:
            min_v, max_v = max_v, min_v

        if abs(max_v - min_v) < 1e-9:
            eps = 1e-4
            if min_v <= 0.0:
                max_v = min(min_v + eps, 1.0)
            elif max_v >= 1.0:
                min_v = max(max_v - eps, 0.0)
            else:
                half = eps * 0.5
                min_v = max(0.0, min_v - half)
                max_v = min(1.0, max_v + half)

        targets = get_target_keys(context,
                                  require_selected=props.affect_only_selected,
                                  visible_only=True,
                                  fallback_to_active=True,
                                  exclude_basis=True)
        if not targets:
            self.report({'INFO'}, "No visible shapekeys to update.")
            return {'CANCELLED'}

        count = 0
        for k in targets:
            try:
                k.slider_min = min_v
                k.slider_max = max_v
            except Exception:
                continue
            try:
                if k.value < min_v:
                    k.value = min_v
                elif k.value > max_v:
                    k.value = max_v
            except Exception:
                pass
            count += 1
        self.report({'INFO'}, f"Updated slider ranges on {count} keys.")
        return {'FINISHED'}


class SKO_OT_ResetValues(Operator):
    bl_idname = "shapekey_organizer.reset_values"
    bl_label = "Reset Values to 0"
    bl_description = "Reset slider range and set value = 0.0 for affected shapekeys"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}
        props = context.scene.shapekey_organizer

        targets = get_target_keys(context,
                                  require_selected=props.affect_only_selected,
                                  visible_only=True,
                                  fallback_to_active=True,
                                  exclude_basis=True)
        if not targets:
            self.report({'INFO'}, "No visible shapekeys to reset.")
            return {'CANCELLED'}

        default_min, default_max = 0.0, 1.0
        ranges_reset = 0
        values_reset = 0

        for k in targets:
            try:
                k.slider_min = default_min
                k.slider_max = default_max
                ranges_reset += 1
            except Exception:
                pass

            if is_basis_key(obj, k):
                continue
            try:
                k.value = 0.0
                values_reset += 1
            except Exception:
                pass

        props.slider_min = 0.0
        props.slider_max = 1.0

        try:
            for win in bpy.context.window_manager.windows:
                for area in win.screen.areas:
                    if area.type == 'PROPERTIES':
                        area.tag_redraw()
        except Exception:
            pass

        self.report({'INFO'}, f"Reset ranges on {ranges_reset} keys and values on {values_reset} keys.")
        return {'FINISHED'}


class SKO_OT_GroupAdd(Operator):
    bl_idname = "shapekey_organizer.group_add"
    bl_label = "Add"
    bl_description = (
        "Add the typed group name to the Groups list (no duplicates) and assign it to currently selected shapekeys. "
        "If the group already exists, it becomes the active selection."
    )
    bl_options = {'REGISTER', 'UNDO'}

    group: StringProperty(
        name="Group",
        description="Group name to create/assign",
        default=""
    )

    def execute(self, context):
        scn = context.scene
        props = scn.shapekey_organizer

        name = (self.group or props.group_search or "").strip()
        if not name:
            self.report({'WARNING'}, "Enter a group name to add.")
            return {'CANCELLED'}

        groups = scn.sko_groups
        existed = any(g.name == name for g in groups)

        ensure_group(context, name)
        for i, g in enumerate(groups):
            if g.name == name:
                scn.sko_groups_index = i
                break
        props.group_search = name

        assigned = 0
        obj = active_obj_mesh(context)
        if obj:
            sk = getattr(getattr(obj.data, 'shape_keys', None), 'key_blocks', None)
            all_keys = list(sk) if sk else []
    
            selected = [k for k in all_keys if get_sel(k) and not is_basis_key(obj, k)]
            if selected:
                targets = selected
            else:
                idx = getattr(obj, "active_shape_key_index", -1)
                ak = sk[idx] if (sk and 0 <= idx < len(sk)) else None
                targets = [ak] if (ak and not is_basis_key(obj, ak)) else []
    
            for k in targets:
                set_group(k, name)
                assigned += 1

        try:
            for area in context.screen.areas:
                if area.type == 'PROPERTIES':
                    area.tag_redraw()
        except Exception:
            pass

        if existed:
            self.report({'INFO'}, f"Selected existing group '{name}'. Assigned to {assigned} keys.")
        else:
            self.report({'INFO'}, f"Added group '{name}'. Assigned to {assigned} keys.")
        return {'FINISHED'}


class SKO_OT_GroupRemove(Operator):
    bl_idname = "shapekey_organizer.group_remove"
    bl_label = "Remove"
    bl_description = "Remove the selected group from the list and clear it from all assigned shapekeys"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scn = context.scene
        idx = scn.sko_groups_index
        groups = scn.sko_groups
        if idx < 0 or idx >= len(groups):
            return {'CANCELLED'}

        group_name = groups[idx].name

        obj = active_obj_mesh(context)
        removed_count = 0
        if obj:
            for k in iter_keyblocks(obj):
                if get_group(k) == group_name:
                    set_group(k, "")
                    removed_count += 1

        groups.remove(idx)
        scn.sko_groups_index = min(idx, len(groups) - 1)

        self.report({'INFO'}, f"Removed group '{group_name}' from list and cleared from {removed_count} keys.")
        for area in context.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()
        return {'FINISHED'}


class SKO_OT_GroupMove(Operator):
    bl_idname = "shapekey_organizer.group_move"
    bl_label = "Move"
    bl_description = "Reorder groups in the list"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(items=[('UP','Up',''),('DOWN','Down','')], default='UP')

    def execute(self, context):
        scn = context.scene
        idx = scn.sko_groups_index
        groups = scn.sko_groups
        if idx < 0 or idx >= len(groups):
            return {'CANCELLED'}
        new_idx = idx - 1 if self.direction == 'UP' else idx + 1
        if new_idx < 0 or new_idx >= len(groups):
            return {'CANCELLED'}
        groups.move(idx, new_idx)
        scn.sko_groups_index = new_idx
        return {'FINISHED'}


class SKO_OT_GroupSelectKeys(Operator):
    bl_idname = "shapekey_organizer.group_select_keys"
    bl_label = "Select Keys"
    bl_description = "Select all keys tagged with the selected group (ignores Basis)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'MESH':
            return {'CANCELLED'}
        scn = context.scene
        idx = scn.sko_groups_index
        groups = scn.sko_groups
        if idx < 0 or idx >= len(groups):
            return {'CANCELLED'}
        gname = groups[idx].name
        for k in iter_keyblocks(obj):
            if is_basis_key(obj, k):
                continue
            if get_group(k) == gname:
                set_sel(k, True)
        return {'FINISHED'}


class SKO_OT_GroupFilterApply(Operator):
    bl_idname = "shapekey_organizer.group_filter_apply"
    bl_label = "Filter"
    bl_description = "Filter the shapekey list to the selected group"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scn = context.scene
        props = scn.shapekey_organizer
        idx = scn.sko_groups_index
        if idx < 0 or idx >= len(scn.sko_groups):
            return {'CANCELLED'}
        props.filter_group = scn.sko_groups[idx].name
        return {'FINISHED'}


class SKO_OT_GroupFilterClear(Operator):
    bl_idname = "shapekey_organizer.group_filter_clear"
    bl_label = "Clear Filter"
    bl_description = "Clear the group filter in the list"
    bl_options = {'REGISTER'}

    def execute(self, context):
        props = context.scene.shapekey_organizer
        props.filter_group = ""
        return {'FINISHED'}

# =====================================================
# Panel
# =====================================================

class SKO_PT_Main(Panel):
    bl_label = "Blender Shapekey Add-Ons"
    bl_idname = "SKO_PT_main"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "data"

    @classmethod
    def poll(cls, context):
        obj = active_obj_mesh(context)
        return obj and getattr(getattr(obj.data, 'shape_keys', None), 'key_blocks', None)

    def draw(self, context):
        layout = self.layout
        obj = context.object
        props = context.scene.shapekey_organizer

        # Updates
        entry = bpy.context.preferences.addons.get(_ADDON_ID)
        prefs = entry.preferences if entry else None
        row = layout.row(align=True)
        if prefs:
            row.prop(prefs, "auto_check", text="Check on Startup")
        row.operator("shapekey_organizer.check_updates", text="Check for Updates", icon='FILE_REFRESH')
        row = layout.row(align=True)
        row.alignment = 'RIGHT'
        row.label(text=f"Installed: v{current_version_display()}")

        # Filters
        state_edit = bool(getattr(obj, "use_shape_key_edit_mode", False))
        state_solo = bool(getattr(obj, "show_only_shape_key", False))

        box = layout.box()
        row = box.row(align=True)
        row.prop(props, 'search', text="Search")
        layout.separator()
        row.operator("shapekey_organizer.toggle_show_only",
            text="", icon=('SOLO_ON' if obj.show_only_shape_key else 'SOLO_OFF'), depress=state_solo)
        row.operator("shapekey_organizer.toggle_use_edit_mode",
            text="", icon=('EDITMODE_HLT'), depress=state_edit)

        # List
        list_row = box.row(align=True)
        list_row.template_list("SKO_UL_shapekeys", "", obj.data.shape_keys, "key_blocks", obj, "active_shape_key_index", rows=10)
        row = box.row(align=True)
        row.operator("shapekey_organizer.shape_key_add", text="Create…", icon='ADD')
        row.operator("shapekey_organizer.shape_key_delete", text="Delete", icon='TRASH')
        controls = box.row(align=True)
        controls.operator("shapekey_organizer.select_all", icon='CHECKBOX_HLT')
        controls.operator("shapekey_organizer.select_none", icon='CHECKBOX_DEHLT')
        controls.operator("shapekey_organizer.select_invert", icon='ARROW_LEFTRIGHT')
        controls.operator("shapekey_organizer.sync_state", icon='FILE_REFRESH')
        box.label(text="Tip: Shift-click a checkbox to select a range.")

        layout.separator()

        # Ordering
        sm = layout.box()
        sm.label(text="Ordering")
        row = sm.row(align=True)
        row.prop(props, 'sort_mode', text="")
        row.operator("shapekey_organizer.sort", icon='SORTALPHA')
        row = sm.row(align=True)
        row.operator("shapekey_organizer.move_selected", text="Top", icon="TRIA_UP_BAR").direction = 'TOP'
        row.operator("shapekey_organizer.move_selected", text="Up", icon="TRIA_UP").direction = 'UP'
        row.operator("shapekey_organizer.move_selected", text="Down", icon="TRIA_DOWN").direction = 'DOWN'
        row.operator("shapekey_organizer.move_selected", text="Bottom", icon="TRIA_DOWN_BAR").direction = 'BOTTOM'

        layout.separator()

        # Groups
        grp = layout.box()
        hdr = grp.row(align=True)
        icon = 'TRIA_DOWN' if props.show_groups else 'TRIA_RIGHT'
        hdr.prop(props, 'show_groups', text="", icon=icon, emboss=False)
        hdr.label(text="Groups")
        if props.show_groups:
            r = grp.row(align=True)
            r.prop(props, 'group_search', text="Group")
            r.operator("shapekey_organizer.group_add", text="Add", icon='ADD')

            rr = grp.row(align=True)
            rr.template_list("SKO_UL_groups", "", context.scene, "sko_groups", context.scene, "sko_groups_index", rows=5)
            col = rr.column(align=True)
            col.operator("shapekey_organizer.group_move", text="Up", icon="TRIA_UP").direction = 'UP'
            col.operator("shapekey_organizer.group_move", text="Down", icon="TRIA_DOWN").direction = 'DOWN'
            col.separator()
            col.operator("shapekey_organizer.group_remove", text="Remove", icon='REMOVE')

            r2 = grp.row(align=True)
            r2.operator("shapekey_organizer.group_select_keys", text="Select Keys", icon='RESTRICT_SELECT_OFF')
            r2.operator("shapekey_organizer.group_filter_apply", text="Filter", icon='FILTER')
            r2.operator("shapekey_organizer.group_filter_clear", text="Clear Filter", icon='X')
            grp.label(text=f"Active filter: '{props.filter_group or 'None'}'")

        layout.separator()

        # Rename
        rn = layout.box()
        hdr = rn.row(align=True)
        icon = 'TRIA_DOWN' if props.show_rename else 'TRIA_RIGHT'
        hdr.prop(props, 'show_rename', text="", icon=icon, emboss=False)
        hdr.label(text="Rename")
        if props.show_rename:
            row = rn.row(align=True)
            row.prop(props, 'prefix')
            row.separator()
            row.prop(props, 'suffix')
            rn.operator("shapekey_organizer.add_prefix_suffix")

            rn.separator()

            row = rn.row(align=True)
            row.prop(props, 'find')
            row.separator()
            row.prop(props, 'replace')
            rn.operator("shapekey_organizer.find_replace")
            row = rn.row(align=True)
            row.prop(props, 'find_case_sensitive', text='Case-Sensitive')

            rn.separator()

            row = rn.row(align=True)
            row.prop(props, 'auto_number_start')
            row.prop(props, 'auto_number_pad')
            rn.operator("shapekey_organizer.auto_number")

        layout.separator()

        # Batch edits
        bt = layout.box()
        hdr = bt.row(align=True)
        icon = 'TRIA_DOWN' if props.show_batch else 'TRIA_RIGHT'
        hdr.prop(props, 'show_batch', text="", icon=icon, emboss=False)
        hdr.label(text="Batch Edits")
        if props.show_batch:
            row = bt.row(align=True)
            row.prop(props, 'slider_min')
            row.prop(props, 'slider_max')
            bt.operator("shapekey_organizer.set_slider_range")
            row = bt.row(align=True)
            row.operator("shapekey_organizer.toggle_mute", text="Mute").state = 'ON'
            row.operator("shapekey_organizer.toggle_mute", text="Unmute").state = 'OFF'
            row.operator("shapekey_organizer.toggle_mute", text="Toggle").state = 'TOGGLE'
            bt.operator("shapekey_organizer.reset_values")

        layout.prop(props, 'affect_only_selected')

# =====================================================
# Registration
# =====================================================

classes = (
    SKO_Item,
    SKO_GroupItem,
    SKO_Props,
    SKO_AddonPreferences,
    SKO_UL_ShapeKeys,
    SKO_UL_Groups,
    SKO_OT_ToggleUseEditMode,
    SKO_OT_ToggleShowOnly,
    SKO_OT_KeyActivateOrRename,
    SKO_OT_ShapeKeyAdd,
    SKO_OT_ShapeKeyDelete,
    SKO_OT_CheckUpdates,
    SKO_OT_ToggleSelect,
    SKO_OT_SelectAll,
    SKO_OT_SelectNone,
    SKO_OT_SelectInvert,
    SKO_OT_AssignGroup,
    SKO_OT_ClearGroup,
    SKO_OT_PrefixSuffix,
    SKO_OT_FindReplace,
    SKO_OT_AutoNumber,
    SKO_OT_Sort,
    SKO_OT_MoveSelected,
    SKO_OT_ToggleMute,
    SKO_OT_SetSliderRange,
    SKO_OT_ResetValues,
    SKO_OT_SyncState,
    SKO_OT_GroupAdd,
    SKO_OT_GroupRemove,
    SKO_OT_GroupMove,
    SKO_OT_GroupSelectKeys,
    SKO_OT_GroupFilterApply,
    SKO_OT_GroupFilterClear,
    SKO_PT_Main,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.shapekey_organizer = bpy.props.PointerProperty(type=SKO_Props)
    bpy.types.Scene.sko_items = CollectionProperty(type=SKO_Item)
    bpy.types.Scene.sko_groups = CollectionProperty(type=SKO_GroupItem)
    bpy.types.Scene.sko_groups_index = IntProperty(default=-1)

    if _sko_auto_check not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_sko_auto_check)


def unregister():
    try:
        if _sko_auto_check in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(_sko_auto_check)
    except Exception:
        pass

    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    del bpy.types.Scene.shapekey_organizer
    if hasattr(bpy.types.Scene, 'sko_items'):
        del bpy.types.Scene.sko_items
    if hasattr(bpy.types.Scene, 'sko_groups'):
        del bpy.types.Scene.sko_groups
    if hasattr(bpy.types.Scene, 'sko_groups_index'):
        del bpy.types.Scene.sko_groups_index


if __name__ == "__main__":
    register()
