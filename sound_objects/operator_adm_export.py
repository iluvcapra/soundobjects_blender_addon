from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty, BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy.types import Operator

from .intern.generate_adm import generate_adm

class ADMWaveExport(Operator, ExportHelper):
    """Export a Broadcast-WAV audio file with each speaker encoded as an ADM object"""
    bl_idname = "export.adm_wave_file"  # important since its how bpy.ops.import_test.some_data is constructed
    bl_label = "Export ADM Wave File"

    # ExportHelper mixin class uses this
    filename_ext = ".wav"

    filter_glob: StringProperty(
        default="*.wav",
        options={'HIDDEN'},
        maxlen=255,  # Max internal buffer length, longer would be clamped.
    )
    
    room_size: FloatProperty(
        default=1.0,
        name="Room Size",
        description="Distance from the lens to the front room boundary",
        min=0.001,
        step=1.,
        unit='LENGTH'
    )

    max_objects: IntProperty(
        name="Max Objects",
        description="Maximum number of object tracks to create",
        default=24,
        min=0,
        max=118
    )

    create_bed:BoolProperty(
        name="Create 7.1 Bed",
        description="Create a bed for all sounds not included on object tracks",
        default=False
    )

    def execute(self, context):
        return generate_adm(context, self.filepath, self.room_size, self.max_objects)

