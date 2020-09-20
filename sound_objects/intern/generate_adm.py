import bpy

from contextlib import contextmanager

import lxml
import uuid
from fractions import Fraction
import struct

import numpy

from time import strftime

from typing import List

from ear.fileio.utils import openBw64

from ear.fileio.bw64.chunks import (FormatInfoChunk, ChnaChunk)

from ear.fileio.adm import chna as adm_chna
from ear.fileio.adm.xml import adm_to_xml
from ear.fileio.adm.builder import (ADMBuilder)
from ear.fileio.adm.generate_ids import generate_ids

from sound_objects.intern.geom_utils import (speaker_active_time_range,
                                             speakers_by_min_distance,
                                             speakers_by_start_time)

from sound_objects.intern.object_mix import (ObjectMix, ObjectMixPool)

from sound_objects.intern.speaker_utils import (all_speakers)


@contextmanager
def adm_object_rendering_context(scene: bpy.types.Scene):
    old_ff = scene.render.image_settings.file_format
    old_codec = scene.render.ffmpeg.audio_codec
    old_chans = scene.render.ffmpeg.audio_channels

    scene = bpy.context.scene

    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.audio_codec = 'PCM'
    scene.render.ffmpeg.audio_channels = 'MONO'

    yield scene

    scene.render.image_settings.file_format = old_ff
    scene.render.ffmpeg.audio_codec = old_codec
    scene.render.ffmpeg.audio_channels = old_chans


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
        success = False  # flaggy-flag because I can't do a break->continue from the inner
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


def adm_for_object(scene, sound_object: ObjectMix, room_size, adm_builder, object_index, wav_format):
    fps = scene.render.fps
    frame_start = scene.frame_start
    frame_end = scene.frame_end

    block_formats = sound_object.adm_block_formats(room_size=room_size)
    created = adm_builder.create_item_objects(track_index=object_index,
                                              name=sound_object.object_name,
                                              block_formats=block_formats)

    created.audio_object.start = Fraction(frame_start, fps)
    created.audio_object.duration = Fraction(frame_end - frame_start, fps)
    created.track_uid.sampleRate = wav_format.sampleRate
    created.track_uid.bitDepth = wav_format.bitsPerSample


def adm_for_scene(scene, sound_objects: List['ObjectMix'], wav_format, room_size):
    adm_builder = ADMBuilder()

    frame_start = scene.frame_start
    frame_end = scene.frame_end
    fps = scene.render.fps

    adm_builder.create_programme(audioProgrammeName=scene.name,
                                 start=Fraction(frame_start, fps),
                                 end=Fraction(frame_end, fps))

    adm_builder.create_content(audioContentName="Objects")

    for object_index, sound_object in enumerate(sound_objects):
        adm_for_object(scene, sound_object, room_size, adm_builder, object_index, wav_format)

    adm = adm_builder.adm

    generate_ids(adm)
    chna = ChnaChunk()
    adm_chna.populate_chna_chunk(chna, adm)

    return adm_to_xml(adm), chna


########################################################################
# File writing functions below


def bext_data(scene, sample_rate, room_size):
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


def write_muxed_wav(mix_pool: ObjectMixPool, scene, out_format, room_size, outfile, shortest_file):
    READ_BLOCK = 1024

    sound_objects = mix_pool.object_mixes
    adm, chna = adm_for_scene(scene, sound_objects, out_format, room_size=room_size)

    outfile.axml = lxml.etree.tostring(adm, pretty_print=True)
    outfile.chna = chna
    outfile.bext = bext_data(scene, out_format.sampleRate, room_size=room_size)

    cursor = 0
    while True:
        remainder = shortest_file - cursor
        to_read = min(READ_BLOCK, remainder)
        if to_read == 0:
            break

        buffer = numpy.zeros((to_read, len(sound_objects)))
        for i, sound_object in enumerate(sound_objects):
            buffer[:, i] = sound_object.mixdown_reader.read(to_read)[:, 0]

        outfile.write(buffer)
        cursor = cursor + to_read


def mux_adm_from_object_mix_pool(scene, mix_pool: ObjectMixPool, output_filename, room_size=1.):

    object_count = len(mix_pool.object_mixes)
    assert object_count > 0

    out_format = FormatInfoChunk(channelCount=object_count,
                                 sampleRate=scene.render.ffmpeg.audio_mixrate,
                                 bitsPerSample=24)

    with openBw64(output_filename, 'w', formatInfo=out_format) as outfile:
        write_muxed_wav(mix_pool, scene, out_format, room_size,
                        outfile, mix_pool.shortest_file_length)



def partition_sounds_to_objects(scene, max_objects):
    sound_sources = all_speakers(scene)

    if len(sound_sources) == 0:
        return []

    object_groups = group_speakers(sound_sources, scene)
    too_far_speakers = []

    if len(object_groups) > max_objects:
        too_far_speakers = object_groups[max_objects:]
        object_groups = object_groups[0:max_objects]

    print("Will create {} objects for {} sources, ignoring {} sources".format(
        len(object_groups), len(sound_sources), len(too_far_speakers)))

    for i, group in enumerate(object_groups):
        print("Object Group %i" % i)
        for source in group:
            print(" - %s" % source.name)
    return object_groups, too_far_speakers


def generate_adm(context: bpy.types.Context, filepath: str, room_size: float, max_objects: int):
    scene = context.scene

    object_groups, _ = partition_sounds_to_objects(scene, max_objects)

    if len(object_groups) == 0:
        return {'FINISHED'}

    with ObjectMixPool.pool_from_source_groups(object_groups) as pool:
        mux_adm_from_object_mix_pool(scene, mix_pool=pool,
                                     output_filename=filepath,
                                     room_size=room_size)


    print("generate_adm exiting")
    return {'FINISHED'}
