import bpy
import os

# bl_info = {
#     "name": "Import WAV Files",
#     "description": "Import WAV files, with options to automatically pack and Fake user",
#     "author": "Jamie Hardt",
#     "version": (0, 20),
#     "blender": (2, 90, 0),
#     "location": "File > Import > WAV Audio Files",
#     "warning": "", # used for warning icon and text in addons panel
#     "support": "COMMUNITY",
#     "category": "Import-Export",
# }

def read_some_data(context, filepath, pack, dir, fake):
    
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


# ImportHelper is a helper class, defines filename and
# invoke() function which calls the file selector.
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.types import Operator


class ImportWav(Operator, ImportHelper):
    """Import WAV audio files"""
    bl_idname = "import_test.wav_file_batch"  # important since its how bpy.ops.import_test.some_data is constructed
    bl_label = "Import WAV Files"

    # ImportHelper mixin class uses this
    filename_ext = ".wav"

    filter_glob: StringProperty(
        default="*.wav",
        options={'HIDDEN'},
        maxlen=255,  # Max internal buffer length, longer would be clamped.
    )

    # List of operator properties, the attributes will be assigned
    # to the class instance from the operator settings before calling.
    # pack_it_in: BoolProperty(
    #     name="Pack Into .blend File",
    #     description="Embed the audio data into the .blend file",
    #     default=True,
    # )
    
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

    def execute(self, context):
        return read_some_data(context=context, filepath=self.filepath, 
                              dir=self.all_in_directory, fake=self.fake,  
                              pack=False)

