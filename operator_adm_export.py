import sys
import bpy
import os

from ear.fileio.utils import openBw64

from ear.fileio.bw64.utils import interleave
from ear.fileio.bw64.chunks import (FormatInfoChunk, ChnaChunk)

from ear.fileio.adm import chna as adm_chna
from ear.fileio.adm.xml import adm_to_xml
from ear.fileio.adm.elements.block_formats import (AudioBlockFormatObjects, JumpPosition)
from ear.fileio.adm.elements.geom import ObjectCartesianPosition
from ear.fileio.adm.builder import (ADMBuilder, TypeDefinition)
from ear.fileio.adm.generate_ids import generate_ids


import lxml
import uuid
from fractions import Fraction
import struct

import numpy
from numpy.linalg import norm
from mathutils import Quaternion, Vector

from time import strftime
from math import sqrt

bl_info = {
    "name": "Export ADM Broadcast-WAV File",
    "description": "Export a Broadcast-WAV with each speaker as an ADM object",
    "author": "Jamie Hardt",
    "version": (0, 22),
    "warning": "Requires `ear` EBU ADM Renderer package to be installed",
    "blender": (2, 90, 0),
    "category": "Import-Export",
}

def compute_relative_vector(camera: bpy.types.Camera, target: bpy.types.Object):
    """
    Return a vector from `camera` to `target` in the camera's coordinate space.

    The camera's lens is assumed to be norm to the ZX plane.
    """
    cam_loc, cam_rot, _ = camera.matrix_world.decompose()
    target_loc, _, _ = target.matrix_world.decompose()
    relative_vector = target_loc - cam_loc
    
    rotation = cam_rot.to_matrix().transposed()
    relative_vector.rotate(rotation)
    
    # The camera's worldvector is norm to the horizon, we want a vector
    # down the barrel.
    camera_correction = Quaternion( ( sqrt(2.) / 2. , sqrt(2.) / 2. , 0. , 0.) )
    relative_vector.rotate(camera_correction)
    
    return relative_vector


def room_norm_vector(vec, room_size=1.):
    """
    The Room is tearing me apart, Lisa.

    The room is a cube with the camera at its center. We use a chebyshev normalization
    to convert a vector in world or camera space into a vector the represents the projection
    of that vector onto the room's walls.

    The Pro Tools/Dolby Atmos workflow I am targeting uses "Room Centric" panner coordinates
    ("cartesian allocentric coordinates" in ADM speak) and this process seems to yield good
    results. 
    """
    chebyshev = norm(vec, ord=numpy.inf)
    if chebyshev < room_size:
        return vec / room_size
    else:
        return vec / chebyshev


def speaker_active_time_range(speaker):
    """
    The time range this speaker must control in order to sound right.

    At this time this is assuming the str
    """
    start, end = 0xffffffff, -0xffffffff
    for track in speaker.animation_data.nla_tracks:
        for strip in track.strips:
            if strip.frame_start < start:
                start = strip.frame_start

            if strip.frame_end > end:
                end = strip.frame_end

    return int(start), int(end)


def speakers_by_start_time(speaker_objs):
    return sorted(speaker_objs, key=(lambda spk: speaker_active_time_range(spk)[0]))


def group_speakers(speaker_objs):
    def group_speakers_impl1(bag):
        "Returns a useable group and the remainder"
        leftover = []
        this_group = []
        boundary = -0xffffffff
        for speaker in bag:
            start, end = speaker_active_time_range(speaker)
            if start > boundary:
                this_group.append(speaker)
                boundary = end
            else:
                leftover.append(speaker)

        return (this_group, leftover)

    groups = []
    remaining = speaker_objs
    while len(remaining) > 0:
        results = group_speakers_impl1(remaining)
        groups.append(results[0])
        remaining = results[1]

    print("Will group {} sources into {} objects".format(len(speaker_objs), len(groups)))
    return groups


def adm_block_formats_for_speakers(scene, speaker_objs, room_size=1.):
    
    block_formats = []
    
    # frame_start = start_frame or scene.frame_start
    # frame_end = end_frame or scene.frame_end
    fps = scene.render.fps

    for speaker_obj in speakers_by_start_time(speaker_objs):
        speaker_start, speaker_end = speaker_active_time_range(speaker_obj)
        for frame in range(speaker_start, speaker_end + 1):
            scene.frame_set(frame)
            relative_vector = compute_relative_vector(camera=scene.camera, 
                                                      object=speaker_obj)
            
            norm_vec = room_norm_vector(relative_vector, room_size=room_size)
            
            pos = ObjectCartesianPosition(X=norm_vec.x , Y=norm_vec.y , Z=norm_vec.z)
            
            if len(block_formats) == 0 or pos != block_formats[-1].position:
                jp = JumpPosition(flag=True, interpolationLength=Fraction(1,fps * 2) ) 
                block = AudioBlockFormatObjects(position= pos, 
                                                rtime=Fraction(frame,fps),
                                                duration=Fraction(1,fps) , 
                                                cartesian=True,
                                                jumpPosition=jp)
            
                block_formats.append(block)
            else:
                block_formats[-1].duration = block_formats[-1].duration + Fraction(1,fps)
                
    return block_formats


def adm_data_for_scene(scene, speaker_objs_lists, wav_format, room_size):
    
    b = ADMBuilder()
    
    frame_start = scene.frame_start
    frame_end = scene.frame_end
    fps = scene.render.fps
    
    b.create_programme(audioProgrammeName=scene.name, 
                   start=Fraction(frame_start ,fps), 
                   end=Fraction(frame_end, fps) )
                   
    b.create_content(audioContentName="Objects")
    
    for i, speakers_this_mixdown in enumerate(speaker_objs_lists):
        block_formats = adm_block_formats_for_speakers(scene, speakers_this_mixdown, 
                                                      room_size=room_size)
        created = b.create_item_objects(track_index=i, 
                                        name=speakers_this_mixdown[0].name,
                                        block_formats=block_formats)
        
        created.audio_object.start = Fraction(frame_start, fps)
        created.audio_object.duration = Fraction(frame_end - frame_start, fps)
        created.track_uid.sampleRate = wav_format.sampleRate
        created.track_uid.bitDepth = wav_format.bitsPerSample
    
    adm = b.adm
    
    generate_ids(adm)
    chna = ChnaChunk()
    adm_chna.populate_chna_chunk(chna, adm)
    
    return adm_to_xml(adm), chna
  

def bext_data(scene, speaker_obj, sample_rate, room_size):
    description = "SCENE={};ROOM_SIZE={}\n".format(scene.name, room_size).encode("ascii")
    originator_name = "Blender {}".format(bpy.app.version_string).encode("ascii")
    originator_ref = uuid.uuid1().hex.encode("ascii")
    date10 = strftime("%Y-%m-%d").encode("ascii")
    time8 = strftime("%H:%M:%S").encode("ascii")
    timeref = int(float(scene.frame_start) * sample_rate / float(scene.render.fps))
    version = 0
    umid = b"\0" * 64
    pad = b"\0" * 190
    
    data = struct.pack("<256s32s32s10s8sQH64s190s", description, originator_name, 
                       originator_ref, date10, time8, timeref, version, umid, pad)
                       
    return data
    

def write_muxed_adm(scene, mixdowns, output_filename=None, room_size=1.):
    """
    mixdowns are a tuple of wave filename, and corresponding speaker object
    """
    object_count = len(mixdowns)
    assert object_count > 0
    
    READ_BLOCK=1024
    out_file = output_filename or os.path.join(os.path.dirname(mixdowns[0][0]), 
                            bpy.path.clean_name(scene.name) + ".wav")
    
    infiles = []
    shortest_file = 0xFFFFFFFFFFFF
    for elem in mixdowns:
        infile = openBw64(elem[0], 'r')
        infiles.append(infile)
        if len(infile) < shortest_file:
            shortest_file = len(infile)
        
    
    out_format = FormatInfoChunk(channelCount=object_count, 
                                   sampleRate=infiles[0].sampleRate,
                                   bitsPerSample=infiles[0].bitdepth)
    
    
    with openBw64(out_file, 'w', formatInfo=out_format) as outfile:
        speakers = list(map(lambda x: x[1], mixdowns))
        adm, chna = adm_data_for_scene(scene, speakers, out_format, room_size=room_size)
        outfile.axml = lxml.etree.tostring(adm, pretty_print=True)
        outfile.chna = chna
        outfile.bext = bext_data(scene, None, out_format.sampleRate, room_size=room_size)
        
        cursor = 0
        while True:
            remainder = shortest_file - cursor
            to_read = min(READ_BLOCK, remainder)
            if to_read == 0:
                break
            
            buffer = numpy.zeros((to_read, object_count))
            for i, infile in enumerate(infiles):
                buffer[: , i] = infile.read(to_read)[: , 0]
            
            outfile.write(buffer)
            cursor = cursor + to_read
    
    for infile in infiles:
        infile._buffer.close()
        
    for elem in mixdowns:
        os.unlink(elem[0])


def all_speakers(scene):
    return [obj for obj in scene.objects if obj.type == 'SPEAKER']


def solo_speakers(scene, solo_group):
    for speaker in all_speakers(scene):
        if speaker in solo_group:
            speaker.data.muted = False
        else:
            speaker.data.muted = True
        
        speaker.data.update_tag()


def unmute_all_speakers(scene):
    for speaker in all_speakers(scene):
        speaker.data.muted = False
        speaker.data.update_tag()
        

def speaker_mixdowns(scene, filepath):
    basedir = os.path.dirname(filepath)
    for speaker_group in group_speakers(all_speakers(scene)):
        solo_speakers(scene, speaker_group)
    
        scene_name = bpy.path.clean_name(scene.name)
        speaker_name = bpy.path.clean_name(speaker_group[0].name)

        fn = os.path.join(basedir, "%s_%s.wav" % (scene_name, speaker_name) )
        bpy.ops.sound.mixdown(filepath=fn, container='WAV', codec='PCM', format='S24')
        yield (fn, speaker_group)


def save_output_state(context):
    """
    save render settings that we change to produce object WAV files
    """
    ff = context.scene.render.image_settings.file_format
    codec = context.scene.render.ffmpeg.audio_codec
    chans = context.scene.render.ffmpeg.audio_channels
    return (ff, codec, chans)


def restore_output_state(ctx, context):
    context.scene.render.image_settings.file_format = ctx[0]
    context.scene.render.ffmpeg.audio_codec = ctx[1]
    context.scene.render.ffmpeg.audio_channels = ctx[2]


def write_some_data(context, filepath, room_size):
    ctx = save_output_state(context)
    
    scene = bpy.context.scene
    
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.audio_codec = 'PCM'
    scene.render.ffmpeg.audio_channels = 'MONO'

    mixdowns = list(speaker_mixdowns(scene, filepath))
    mixdown_count = len(mixdowns)
    if mixdown_count == 0:
        return {'FINISHED'}
    else:
        write_muxed_adm(scene, mixdowns, output_filename= filepath, room_size=room_size)
    
    #cleanup
    unmute_all_speakers(scene)
    restore_output_state(ctx, context)
    return {'FINISHED'}



#########################################################################
### BOILERPLATE EXPORTER CODE BELOW


# ExportHelper is a helper class, defines filename and
# invoke() function which calls the file selector.
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty, BoolProperty, EnumProperty, FloatProperty
from bpy.types import Operator


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

    def execute(self, context):
        return write_some_data(context, self.filepath, self.room_size)


# Only needed if you want to add into a dynamic menu
def menu_func_export(self, context):
    self.layout.operator(ADMWaveExport.bl_idname, text="ADM Broadcast-WAVE (.wav)")


def register():
    bpy.utils.register_class(ADMWaveExport)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)


def unregister():
    bpy.utils.unregister_class(ADMWaveExport)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)


if __name__ == "__main__":
    register()

