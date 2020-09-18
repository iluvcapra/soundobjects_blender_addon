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

from dataclasses import dataclass
from typing import List, Tuple

bl_info = {
    "name": "Export ADM Broadcast-WAV File",
    "description": "Export a Broadcast-WAV with each speaker as an ADM object",
    "author": "Jamie Hardt",
    "version": (0, 23),
    "warning": "Requires `ear` EBU ADM Renderer package to be installed",
    "blender": (2, 90, 0),
    "category": "Import-Export",
}

class FrameInterval:
    def __init__(self, start_frame, end_frame):
        self.start_frame = int(start_frame)
        self.end_frame = int(end_frame)

    def overlaps(self, other : 'FrameInterval') -> bool:
        return self.start_frame <= other.start_frame <= self.end_frame or \
            other.start_frame <= self.start_frame <= other.end_frame


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


def room_norm_vector(vec, room_size=1.) -> Vector:
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


def closest_approach_to_camera(scene, speaker_object) -> (float, int):
    max_dist = sys.float_info.max
    at_time = scene.frame_start
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        rel = speaker_object.matrix_world.to_translation() - scene.camera.matrix_world.to_translation()
        dist = norm(rel)
        
        if dist < max_dist:
            max_dist = dist
            at_time = frame

    return (max_dist, at_time)


def speaker_active_time_range(speaker) -> FrameInterval:
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

    return FrameInterval(start_frame=start, end_frame=end)


def speakers_by_min_distance(scene, speakers):
    def min_distance(speaker):
        return closest_approach_to_camera(scene, speaker)[0]

    return sorted(speakers, key=(lambda spk: min_distance(spk)))


def speakers_by_start_time(speaker_objs):
    return sorted(speaker_objs, key=(lambda spk: speaker_active_time_range(spk).start_frame))


def group_speakers(speakers, scene) -> List[List[bpy.types.Object]]:
    def list_can_accept_speaker(speaker_list, speaker_to_test):
        """
        returns True if speaker_list contains no speakers active in
        the range speaker_to_test is active in
        """
        test_range = speaker_active_time_range(speaker_to_test)
        for spk in speaker_list:
            spk_range = speaker_active_time_range(spk)
            if spk_range.overlaps(test_range):
                return False

        return True

    by_priority = speakers_by_min_distance(scene, speakers)

    ret_val = [[]]
    for spk in by_priority:
        success = False # flaggy-flag because I can't do a break->continue from the inner
        for elem in ret_val:
            if list_can_accept_speaker(elem, spk):
                elem.append(spk)
                success = True
                break
        if not success:
            ret_val.append([spk])

    for i in range(len(ret_val)):
        ret_val[i] = speakers_by_start_time(ret_val[i])

    return ret_val


def adm_block_formats_for_speakers(scene, speaker_objs, room_size=1.):
    
    fps = scene.render.fps
    block_formats = []

    for speaker_obj in speakers_by_start_time(speaker_objs):
        speaker_interval = speaker_active_time_range(speaker_obj)
        for frame in range(speaker_interval.start_frame, speaker_interval.end_frame + 1):
            scene.frame_set(frame)
            relative_vector = compute_relative_vector(camera=scene.camera, target=speaker_obj)
            
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


def adm_for_object(scene, speakers_this_mixdown, room_size, b, i, frame_start, fps, frame_end, wav_format):
    block_formats = adm_block_formats_for_speakers(scene=scene, 
                                                   speaker_objs=speakers_this_mixdown, 
                                                   room_size=room_size)
    created = b.create_item_objects(track_index=i, 
                                    name=speakers_this_mixdown[0].name,
                                    block_formats=block_formats)

    created.audio_object.start = Fraction(frame_start, fps)
    created.audio_object.duration = Fraction(frame_end - frame_start, fps)
    created.track_uid.sampleRate = wav_format.sampleRate
    created.track_uid.bitDepth = wav_format.bitsPerSample
  

def adm_for_scene(scene, speaker_groups, wav_format, room_size):
    
    b = ADMBuilder()
    
    frame_start = scene.frame_start
    frame_end = scene.frame_end
    fps = scene.render.fps
    
    b.create_programme(audioProgrammeName=scene.name, 
                   start=Fraction(frame_start ,fps), 
                   end=Fraction(frame_end, fps) )
                   
    b.create_content(audioContentName="Objects")
    
    for i, speakers_this_mixdown in enumerate(speaker_groups):
        adm_for_object(scene, speakers_this_mixdown, room_size, b, i, frame_start, fps, frame_end, wav_format)
    
    adm = b.adm
    
    generate_ids(adm)
    chna = ChnaChunk()
    adm_chna.populate_chna_chunk(chna, adm)
    
    return adm_to_xml(adm), chna


########################################################################
# File writing functions below


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


def load_infiles_for_muxing(mixdowns):
    infiles = []
    shortest_file = 0xFFFFFFFFFFFF
    for elem in mixdowns:
        infile = openBw64(elem[0], 'r')
        infiles.append(infile)
        if len(infile) < shortest_file:
            shortest_file = len(infile)
    return infiles, shortest_file


def write_muxed_wav(mixdowns, scene, out_format, room_size, outfile, shortest_file, object_count, infiles):
    #print("write_muxed_wav entered")
    READ_BLOCK=1024
    speaker_groups = list(map(lambda x: x[1], mixdowns))
    
    adm, chna = adm_for_scene(scene, speaker_groups, out_format, room_size=room_size)

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


def mux_adm_from_object_mixdowns(scene, mixdowns_spk_list_tuple, output_filename=None, room_size=1.):
    """
    mixdowns are a tuple of wave filename, and corresponding speaker object
    """
    #print("mux_adm_from_object_mixdowns entered")

    object_count = len(mixdowns_spk_list_tuple)
    assert object_count > 0

    infiles, shortest_file = load_infiles_for_muxing(mixdowns_spk_list_tuple)
    
    out_file = output_filename or os.path.join(os.path.dirname(mixdowns_spk_list_tuple[0][0]), 
                            bpy.path.clean_name(scene.name) + ".wav")
    
    out_format = FormatInfoChunk(channelCount=object_count, 
                                   sampleRate=infiles[0].sampleRate,
                                   bitsPerSample=infiles[0].bitdepth)
    
    with openBw64(out_file, 'w', formatInfo=out_format) as outfile:
        write_muxed_wav(mixdowns_spk_list_tuple, scene, out_format, room_size, outfile, shortest_file, object_count, infiles)
    
    for infile in infiles:
        infile._buffer.close()


def rm_object_mixes(mixdowns):
   #print("rm_object_mixes entered")
    for elem in mixdowns:
        os.remove(elem[0])


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


def create_mixdown_for_object(scene, speaker_group, basedir):
    solo_speakers(scene, speaker_group)

    scene_name = bpy.path.clean_name(scene.name)
    speaker_name = bpy.path.clean_name(speaker_group[0].name)

    fn = os.path.join(basedir, "%s_%s.wav" % (scene_name, speaker_name) )
    bpy.ops.sound.mixdown(filepath=fn, container='WAV', codec='PCM', format='S24')
    print("Created mixdown named {}".format(fn))
    return fn


def generate_speaker_mixdowns(scene, speaker_groups, filepath):
    basedir = os.path.dirname(filepath)

    for speaker_group in speaker_groups:
        fn = create_mixdown_for_object(scene, speaker_group, basedir)
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


def write_some_data(context, filepath, room_size, max_objects):
    ctx = save_output_state(context)
    
    scene = bpy.context.scene
    
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.audio_codec = 'PCM'
    scene.render.ffmpeg.audio_channels = 'MONO'

    sound_sources = all_speakers(scene)

    object_groups = group_speakers(sound_sources, scene)
    too_far_speakers = []
    if len(object_groups) > max_objects:
        too_far_speakers = object_groups[max_objects:]
        object_groups = object_groups[0:max_objects]

    print("Will create {} objects for {} sources, ignoring {} sources".format(
                 len(object_groups), len(sound_sources), len(too_far_speakers)))

    for i, group in enumerate(object_groups):
        print("Object Group %i"%i)
        for source in group:
            print(" - %s" % source.name)

    mixdowns_spk_list_tuple = list(generate_speaker_mixdowns(scene, object_groups, filepath))

    mixdown_count = len(mixdowns_spk_list_tuple)

    if mixdown_count == 0:
        return {'FINISHED'}
    else:
        mux_adm_from_object_mixdowns(scene, mixdowns_spk_list_tuple, 
                                     output_filename= filepath, 
                                     room_size=room_size)
    
    #cleanup
    #print("Will delete {} input object files".format(len(mixdowns_spk_list_tuple)))
    rm_object_mixes(mixdowns_spk_list_tuple)
    unmute_all_speakers(scene)
    restore_output_state(ctx, context)
    return {'FINISHED'}



#########################################################################
### BOILERPLATE EXPORTER CODE BELOW


# ExportHelper is a helper class, defines filename and
# invoke() function which calls the file selector.
from bpy_extras.io_utils import ExportHelper
from bpy.props import StringProperty, BoolProperty, EnumProperty, FloatProperty, IntProperty
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

    max_objects: IntProperty(
        name="Max Objects",
        description="Maximum number of objects to create",
        default=24,
        min=0,
        max=118
    )

    def execute(self, context):
        return write_some_data(context, self.filepath, self.room_size, self.max_objects)


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

