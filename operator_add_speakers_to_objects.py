import bpy

from bpy.types import Operator
from bpy.props import BoolProperty, StringProperty, EnumProperty, FloatProperty

from .intern.add_sound_to_meshes import add_speakers_to_meshes, TriggerMode

class AddSoundToMeshOperator(Operator):
    """Add a speaker to each selected object"""
    bl_idname = "object.add_speakers_to_obj"
    bl_label = "Add Sounds to Meshes"
    
    TRIGGER_OPTIONS = (
        (TriggerMode.START_FRAME, 
            "Start Frame", 
            "Sound will play on the first frame of the animation"),
        (TriggerMode.MIN_DISTANCE, 
            "Minimum Distance", 
            "Sound will play when the object is closest to the camera"),
        (TriggerMode.RANDOM, 
            "Random", 
            "Sound will play exactly once, at a random time"),
        (TriggerMode.RANDOM_GAUSSIAN,
            "Random (Gaussian)",
            "Sound will play exactly once, at a guassian random time with " + 
            "stdev of 1 and mean in the middle of the animation")
    )
    
    @classmethod
    def poll(cls, context):
        sounds_avail = bpy.data.sounds
        return len(context.selected_objects) > 0 and len(sounds_avail) > 0

    use_sounds: StringProperty(
        name="Sound Prefix",
        description="Sounds having names starting with thie field will be assigned randomly to each speaker"
    )
    
    sync_audio_peak: BoolProperty(
        name="Sync Audio Peak",
        default=True,
        description="Synchronize speaker audio to loudest peak instead of beginning of file"
    )
    
    trigger_mode: EnumProperty(
        items=TRIGGER_OPTIONS,
        name="Trigger",
        description="Select when each sound will play",
        default=TriggerMode.MIN_DISTANCE,
        
    )
    
    gaussian_stddev: FloatProperty(
        name="Gaussian StDev",
        description="Standard Deviation of Gaussian random time",
        default=1.,
        min=0.001,
        max=6.,
    )
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)
    
    def execute(self, context):
        
        add_speakers_to_meshes(bpy.context.selected_objects, bpy.context, 
                       sound=None, 
                       sound_name_prefix=self.use_sounds, 
                       trigger_mode=self.trigger_mode,
                       sync_peak=self.sync_audio_peak,
                       gaussian_stddev=self.gaussian_stddev)
        return {'FINISHED'}
