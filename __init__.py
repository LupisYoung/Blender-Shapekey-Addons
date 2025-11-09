bl_info = {
    "name": "Blender Shapekey Add-Ons",
    "author": "LupisYoung",
    "version": (1, 2, 0),
    "blender": (4, 0, 0),
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
import re
from bpy.props import (
    BoolProperty,
    StringProperty,
    IntProperty,
    EnumProperty,
    FloatProperty,
    CollectionProperty,
)

# =====================================================
# Helpers & state
# =====================================================

GITHUB_REPO = "LupisYoung/Blender-Shapekey-Addons"
GITHUB_LATEST_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"

_ADDON_ID = __package__ or __name__.split(".", 1)[0]

def _current_version_tuple():
    """
    Returns (major, minor, patch) from, in order:
    - this module's bl_info['version']
    - this module's __version__ string
    - Blender's registered add-on module bl_info['version'] or __version__
    - fallback (0, 0, 0)
    """
    import sys
    import bpy

    mod = sys.modules.get(__name__)
    if mod:
        try:
            vi = getattr(mod, "bl_info", {}).get("version", None)
            if isinstance(vi, (tuple, list)) and len(vi) >= 1:
                a = list(vi[:3]) + [0, 0]
                return tuple(int(x) for x in a[:3])
        except Exception:
            pass
        try:
            vstr = getattr(mod, "__version__", "")
            if isinstance(vstr, str) and vstr:
                parts = vstr.split(".")
                nums = []
                for p in parts[:3]:
                    try:
                        nums.append(int(p))
                    except Exception:
                        nums.append(0)
                while len(nums) < 3:
                    nums.append(0)
                return tuple(nums)
        except Exception:
            pass

    try:
        addon_id = __package__ or __name__.split(".", 1)[0]
        entry = bpy.context.preferences.addons.get(addon_id)
        reg_mod = getattr(entry, "module", None) if entry else None
        if reg_mod:
            vi = getattr(reg_mod, "bl_info", {}).get("version", None)
            if isinstance(vi, (tuple, list)) and len(vi) >= 1:
                a = list(vi[:3]) + [0, 0]
                return tuple(int(x) for x in a[:3])
            vstr = getattr(reg_mod, "__version__", "")
            if isinstance(vstr, str) and vstr:
                parts = vstr.split(".")
                nums = []
                for p in parts[:3]:
                    try:
                        nums.append(int(p))
                    except Exception:
                        nums.append(0)
                while len(nums) < 3:
                    nums.append(0)
                return tuple(nums)
    except Exception:
        pass

    return (0, 0, 0)
    if isinstance(vi, str):
        parts = vi.split(".")[:3]
        out = []
        for p in parts:
            try:
                out.append(int(p))
            except ValueError:
                out.append(0)
        while len(out) < 3:
            out.append(0)
        return tuple(out)
    return (0, 0, 0)


def _parse_version_tag(tag: str):
    """Parse 'v1.2.3' or '1.2.3' into (1,2,3). Unknown/missing -> (0,0,0)."""
    if not tag:
        return (0, 0, 0)
    t = tag[1:] if tag[:1] in ("v", "V") else tag
    parts = t.strip().split(".")[:3]
    out = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    while len(out) < 3:
        out.append(0)
    return tuple(out)


def _fetch_latest_tag():
    """Return latest release tag_name from GitHub Releases API, or '' on failure."""
    ua = "Blender-Shapekey-Add-Ons/{}".format(".".join(map(str, _current_version_tuple())) or "0.0.0")
    req = urllib.request.Request(GITHUB_LATEST_API, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
        return data.get("tag_name") or ""
    except urllib.error.HTTPError as e:
        return ""
    except Exception:
        return ""


class SKO_OT_CheckUpdates(Operator):
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
        current = _current_version_tuple()
        latest_tag = _fetch_latest_tag()
        latest = _parse_version_tag(latest_tag)

        if latest > current:
            msg = f"New version available: {latest_tag or 'unknown'} (current {'.'.join(map(str, current))})."
            self._popup(context, msg, show_open=True)
        else:
            if not self.silent_if_latest:
                if latest_tag == "":
                    self._popup(context, "Could not determine latest version (GitHub API unavailable).", show_open=True)
                else:
                    self._popup(context, "You are on the latest version.", show_open=False)
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

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        key = item
        if not key:
            return
        sel = get_sel(key)
        row = layout.row(align=True)
        row.prop(key, 'name', text="", emboss=True)

        g = get_group(key)
        if g:
            tag = row.row(align=True)
            tag.label(text=g, icon='GROUP')

        row.prop(key, 'value', text="")
        row.prop(key, 'mute', text="", icon_only=True, icon='HIDE_OFF')
        op = row.operator("shapekey_organizer.toggle_select", text="", icon='CHECKBOX_HLT' if sel else 'CHECKBOX_DEHLT', depress=sel)
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

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if not item:
            return
        row = layout.row(align=True)
        row.label(text=item.name)

# =====================================================
# Operators
# =====================================================

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
        count = 0
        for k in iter_keyblocks(obj):
            if get_sel(k):
                set_group(k, self.group)
                count += 1
        self.report({'INFO'}, f"Assigned group '{self.group}' to {count} keys.")
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
        count = 0
        for k in iter_keyblocks(obj):
            if props.affect_only_selected and not get_sel(k):
                continue
            it = ensure_item_by_name(k.name, create=True)
            new_name = f"{pre}{k.name}{suf}"
            k.name = new_name
            it.key_name = new_name
            count += 1
        self.report({'INFO'}, f"Renamed {count} keys.")
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
        ks = iter_keyblocks(obj)
        if not ks:
            return {'CANCELLED'}
        idxs = [i for i, k in enumerate(ks) if get_sel(k)]
        if not idxs:
            self.report({'INFO'}, "No keys selected.")
            return {'CANCELLED'}

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

        visible = filtered_keys(context, obj)
        targets = [k for k in visible if get_sel(k)] if props.affect_only_selected else list(visible)
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

        visible = filtered_keys(context, obj)
        targets = [k for k in visible if get_sel(k)] if props.affect_only_selected else list(visible)
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

    def execute(self, context):
        scn = context.scene
        props = scn.shapekey_organizer
        name = props.group_search.strip()
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

        obj = active_obj_mesh(context)
        assigned = 0
        if obj:
            for k in iter_keyblocks(obj):
                if is_basis_key(obj, k):
                    continue
                if get_sel(k):
                    set_group(k, name)
                    assigned += 1

        for area in context.screen.areas:
            if area.type == 'PROPERTIES':
                area.tag_redraw()

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

        # Filters
        box = layout.box()
        row = box.row(align=True)
        row.prop(props, 'search', text="Search")

        # List
        list_row = box.row(align=True)
        list_row.template_list("SKO_UL_shapekeys", "", obj.data.shape_keys, "key_blocks", obj, "active_shape_key_index", rows=10)
        controls = box.row(align=True)
        controls.operator("shapekey_organizer.select_all")
        controls.operator("shapekey_organizer.select_none")
        controls.operator("shapekey_organizer.select_invert")
        controls.operator("shapekey_organizer.sync_state")
        box.label(text="Tip: Shift-click a checkbox to select a range.")

        layout.separator()

        # Ordering
        sm = layout.box()
        sm.label(text="Ordering")
        row = sm.row(align=True)
        row.prop(props, 'sort_mode', text="")
        row.operator("shapekey_organizer.sort")
        row = sm.row(align=True)
        row.operator("shapekey_organizer.move_selected", text="Top").direction = 'TOP'
        row.operator("shapekey_organizer.move_selected", text="Up").direction = 'UP'
        row.operator("shapekey_organizer.move_selected", text="Down").direction = 'DOWN'
        row.operator("shapekey_organizer.move_selected", text="Bottom").direction = 'BOTTOM'

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
            r.operator("shapekey_organizer.group_add", text="Add")

            rr = grp.row(align=True)
            rr.template_list("SKO_UL_groups", "", context.scene, "sko_groups", context.scene, "sko_groups_index", rows=5)
            col = rr.column(align=True)
            col.operator("shapekey_organizer.group_move", text="Up").direction = 'UP'
            col.operator("shapekey_organizer.group_move", text="Down").direction = 'DOWN'
            col.separator()
            col.operator("shapekey_organizer.group_remove", text="Remove")

            r2 = grp.row(align=True)
            r2.operator("shapekey_organizer.group_select_keys", text="Select Keys")
            r2.operator("shapekey_organizer.group_filter_apply", text="Filter")
            r2.operator("shapekey_organizer.group_filter_clear", text="Clear Filter")
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
