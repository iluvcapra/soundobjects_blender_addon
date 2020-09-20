import bpy
import os

def read_some_data(filepath, pack, dir, fake):
    
    def import_one(fp):
        sound = bpy.data.sounds.load(fp, check_existing=False)
        if pack:
            sound.pack()
            
        if fake:
            sound.use_fake_user = True
            
    if dir:
        the_dir = os.path.dirname(filepath)
        for child in os.listdir(the_dir):
            if child.endswith(".wav"):
                import_one(os.path.join(the_dir, child))
                
    else:
        import_one(filepath)
        
    return {'FINISHED'}


from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.types import Operator


class ImportWav(Operator, ImportHelper):
    """Import WAV audio files"""
    bl_idname = "import_test.wav_file_batch" 
    bl_label = "Import WAV Files"

    filename_ext = ".wav"

    filter_glob: StringProperty(
        default="*.wav",
        options={'HIDDEN'},
        maxlen=255,  # Max internal buffer length, longer would be clamped.
    )
    
    fake: BoolProperty(
        name="Add Fake User",
        description="Add the Fake User to each of the sound files",
        default=True,
    )
    
    all_in_directory: BoolProperty(
        name="All Files in Folder",
        description="Import every WAV file found in the folder as the selected file",
        default=False,
    )

    def execute(self, _):
        return read_some_data(filepath=self.filepath, pack=False, dir=self.all_in_directory, fake=self.fake)

