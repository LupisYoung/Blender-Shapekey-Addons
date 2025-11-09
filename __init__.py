bl_info = {
    "name": "Blender Shapekey Add-Ons",
    "author": "LupisYoung",
    "version": (1, 0),
    "blender": (4, 0, 0),
    "location": "Object Data Properties > Shape Keys",
    "description": "Organize, search/filter, group-tag, batch-rename, sort, and bulk-edit shapekeys.",
    "warning": "",
    "doc_url": "https://github.com/LupisYoung/Blender-Shapekey-Addons",
    "tracker_url": "https://github.com/LupisYoung/Blender-Shapekey-Addons/issues",
    "support": "COMMUNITY",
    "category": "Object",
}

import bpy
from bpy.types import Operator, Panel, PropertyGroup, UIList
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

def _on_find_change(self, context):
    """When the Find field changes, auto-select all keys whose names contain it (case-insensitive).
    (Does not deselect others; empty Find does nothing.)"""
    try:
        obj = active_obj_mesh(context)
        if not obj:
            return
        txt = self.find.lower()
        if not txt:
            return
        for k in iter_keyblocks(obj):
            if txt in k.name.lower():
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
        description="Auto-selects keys whose names contain this text; used by Find & Replace (case-sensitive)",
        default="",
        update=_on_find_change,
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
            ('GROUP_NAME', "Group→Name", "Group (A→Z), then Name (A→Z)"),
            ('PINNED_FIRST', "Pinned First", "Pinned keys first, then A→Z"),
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
        default=0.0
    )
    slider_max: FloatProperty(
        name="Slider Max",
        description="Set slider maximum for (visible) selected keys",
        default=1.0
    )
    list_rows: IntProperty(
        name="Rows",
        description="Number of rows to display in the scrollable list",
        default=10, min=3, max=24
    )
    affect_only_selected: BoolProperty(
        name="Only Selected",
        description="If enabled, actions only affect keys with the checkbox enabled. If off, actions affect all visible keys",
        default=True
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
        row.prop(key, 'value', text="")
        row.prop(key, 'mute', text="", icon_only=True, icon='HIDE_OFF')
        row.prop(key, 'pin', text="", icon_only=True, icon='PINNED')
        op = row.operator("shapekey_organizer.toggle_select", text="", icon='CHECKBOX_HLT' if sel else 'CHECKBOX_DEHLT', depress=sel)
        op.key_name = key.name
        g = get_group(key)
        if g:
            row.label(text=f"[{g}]")

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

# =====================================================
# Operators
# =====================================================

class SKO_OT_ToggleSelect(Operator):
    bl_idname = "shapekey_organizer.toggle_select"
    bl_label = "Toggle Select"
    bl_description = "Toggle selection state for this shapekey"
    bl_options = {'INTERNAL', 'UNDO'}

    key_name: StringProperty(name="Key Name")

    def execute(self, context):
        it = ensure_item_by_name(self.key_name, create=True)
        if not it:
            self.report({'WARNING'}, "Could not access selection state.")
            return {'CANCELLED'}
        it.selected = not it.selected
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
    bl_description = "Select all currently visible (filtered) shapekeys"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}
        for k in filtered_keys(context, obj):
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
    bl_description = "Invert selection for all currently visible (filtered) shapekeys"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}
        for k in filtered_keys(context, obj):
            set_sel(k, not get_sel(k))
        return {'FINISHED'}


class SKO_OT_AssignGroup(Operator):
    bl_idname = "shapekey_organizer.assign_group"
    bl_label = "Assign Group"
    bl_description = "Assign the current Group filter value to selected shapekeys"
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
    bl_description = "Find text in names and replace it for each affected shapekey"
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
        count = 0
        for k in iter_keyblocks(obj):
            if props.affect_only_selected and not get_sel(k):
                continue
            if find in k.name:
                it = ensure_item_by_name(k.name, create=True)
                new_name = k.name.replace(find, repl)
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
    bl_description = "Sort the selected (or all visible) keys based on the chosen mode. Basis is kept at the top"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}
        ks = iter_keyblocks(obj)
        if not ks:
            return {'CANCELLED'}
        props = context.scene.shapekey_organizer

        data = [(i, k) for i, k in enumerate(ks) if (not props.affect_only_selected or get_sel(k))]
        if not data:
            self.report({'INFO'}, "Nothing to sort.")
            return {'CANCELLED'}

        def sort_key(item):
            _, k = item
            if props.sort_mode == 'NAME_DESC':
                return (k.name.lower(),)
            if props.sort_mode == 'GROUP_NAME':
                return (get_group(k).lower(), k.name.lower())
            if props.sort_mode == 'PINNED_FIRST':
                return (0 if k.pin else 1, k.name.lower())
            return (k.name.lower(),)

        reverse = True if props.sort_mode == 'NAME_DESC' else False
        ordered = sorted(data, key=sort_key, reverse=reverse)

        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass
        indices = [idx for idx, _ in ordered]
        for idx in sorted(indices):
            obj.active_shape_key_index = idx
            move_active_to_top_below_basis(obj)
        self.report({'INFO'}, f"Sorted {len(indices)} keys (moved below Basis).")
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
        count = 0
        for k in iter_keyblocks(obj):
            if props.affect_only_selected and not get_sel(k):
                continue
            k.slider_min = props.slider_min
            k.slider_max = props.slider_max
            count += 1
        self.report({'INFO'}, f"Updated slider ranges on {count} keys.")
        return {'FINISHED'}


class SKO_OT_ResetValues(Operator):
    bl_idname = "shapekey_organizer.reset_values"
    bl_label = "Reset Values to 0"
    bl_description = "Set value to 0.0 for affected shapekeys"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = active_obj_mesh(context)
        if not obj:
            self.report({'WARNING'}, "Select a mesh object with shapekeys.")
            return {'CANCELLED'}
        props = context.scene.shapekey_organizer
        count = 0
        for k in iter_keyblocks(obj):
            if props.affect_only_selected and not get_sel(k):
                continue
            k.value = 0.0
            count += 1
        self.report({'INFO'}, f"Reset {count} keys to 0.0")
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
        row.prop(props, 'filter_group', text="Group")
        row.prop(props, 'list_rows', text="Rows")

        # List
        list_row = box.row(align=True)
        list_row.template_list("SKO_UL_shapekeys", "", obj.data.shape_keys, "key_blocks", obj, "active_shape_key_index", rows=props.list_rows)
        controls = box.row(align=True)
        controls.operator("shapekey_organizer.select_all")
        controls.operator("shapekey_organizer.select_none")
        controls.operator("shapekey_organizer.select_invert")
        controls.operator("shapekey_organizer.sync_state")

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
            r.operator("shapekey_organizer.assign_group", text="Assign").group = props.filter_group
            r.operator("shapekey_organizer.clear_group", text="Clear")
            grp.label(text="Tip: Set 'Group' filter above, then click Assign to tag selected with that group name.")

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
            row.prop(props, 'suffix')
            rn.operator("shapekey_organizer.add_prefix_suffix")
            row = rn.row(align=True)
            row.prop(props, 'find')
            row.prop(props, 'replace')
            rn.operator("shapekey_organizer.find_replace")
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
    SKO_Props,
    SKO_UL_ShapeKeys,
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
    SKO_PT_Main,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.shapekey_organizer = bpy.props.PointerProperty(type=SKO_Props)
    bpy.types.Scene.sko_items = CollectionProperty(type=SKO_Item)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
    del bpy.types.Scene.shapekey_organizer
    if hasattr(bpy.types.Scene, 'sko_items'):
        del bpy.types.Scene.sko_items


if __name__ == "__main__":
    register()