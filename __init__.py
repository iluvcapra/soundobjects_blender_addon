import bpy

from .operator_add_speakers_to_objects import AddSoundToMeshOperator
from .operator_adm_export import ADMWaveExport
from .operator_wav_import import ImportWav

bl_info = {
    "name": "Sound Objects",
    "description": "Tools for adding sounds to objects and export to immersive format",
    "author": "Jamie Hardt",
    "version": (0, 1),
    "warning": "Requires `ear` EBU ADM Renderer package to be installed",
    "blender": (2, 91, 2),
    "category": "Import-Export",
    "support": "TESTING",
    "tracker_url": "https://github.com/iluvcapra/soundobjects_blender_addon/issues",
    "wiki_url": ""
}

#class SoundObjectAttachmentPanel(bpy.types.Panel):
#    bl_idname = "OBJECT_PT_sound_object_attachment_panel"
#    bl_space_type = "VIEW_3D"
#    bl_label = "Attach Sounds"
#    bl_region_type = "UI"
#    bl_category = "Tools"
#    bl_context = "object"
#    bl_options = {"DEFAULT_CLOSED"}

#    def draw(self, context):
#        self.layout.label(text="Attach Sounds")


def import_wav_menu_callback(self, context):
    self.layout.operator(ImportWav.bl_idname, text="WAV Audio Files (.wav)")


def export_adm_menu_callback(self, context):
    self.layout.operator(ADMWaveExport.bl_idname, text="ADM Broadcast-WAVE (.wav)")


def add_sound_to_mesh_menu_callback(self, context):
    self.layout.operator(AddSoundToMeshOperator.bl_idname, icon='SPEAKER')
    

def register():
    bpy.utils.register_class(AddSoundToMeshOperator)
    bpy.utils.register_class(ADMWaveExport)
    bpy.utils.register_class(ImportWav)

    bpy.types.TOPBAR_MT_file_import.append(import_wav_menu_callback)
    bpy.types.TOPBAR_MT_file_export.append(export_adm_menu_callback)
    bpy.types.VIEW3D_MT_object.append(add_sound_to_mesh_menu_callback)

#    bpy.utils.register_class(SoundObjectAttachmentPanel)
    

def unregister():
    bpy.utils.unregister_class(AddSoundToMeshOperator)
    bpy.utils.unregister_class(ADMWaveExport)
    bpy.utils.unregister_class(ImportWav)

    bpy.types.TOPBAR_MT_file_import.remove(import_wav_menu_callback)
    bpy.types.TOPBAR_MT_file_export.remove(export_adm_menu_callback)
    bpy.types.VIEW3D_MT_object.remove(add_sound_to_mesh_menu_callback)

#    bpy.utils.unregister_class(SoundObjectAttachmentPanel)
