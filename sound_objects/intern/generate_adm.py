import bpy
import os

from contextlib import contextmanager

import lxml
import uuid
from fractions import Fraction
import struct

import numpy

from time import strftime

from typing import List

from ear.fileio.utils import openBw64

from ear.fileio.bw64 import Bw64Reader
from ear.fileio.bw64.chunks import (FormatInfoChunk, ChnaChunk)

from ear.fileio.adm import chna as adm_chna
from ear.fileio.adm.xml import adm_to_xml
from ear.fileio.adm.elements.block_formats import (AudioBlockFormatObjects, JumpPosition)
from ear.fileio.adm.elements.geom import ObjectCartesianPosition
from ear.fileio.adm.builder import (ADMBuilder)
from ear.fileio.adm.generate_ids import generate_ids

from sound_objects.intern.geom_utils import (compute_relative_vector,
                                             room_norm_vector,
                                             speaker_active_time_range,
                                             speakers_by_min_distance,
                                             speakers_by_start_time)

from sound_objects.intern.speaker_utils import (all_speakers, solo_speakers, unmute_all_speakers)


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


class ObjectMix:
    def __init__(self, sources: List[bpy.types.Speaker],
                 scene: bpy.types.Scene, base_dir: str):
        self.sources = sources
        self.intermediate_filename = None
        self.base_dir = base_dir
        self.scene = scene
        self._mixdown_file_handle = None
        self._mixdown_reader = None

    @property
    def frame_start(self):
        return self.scene.frame_start

    @property
    def frame_end(self):
        return self.scene.frame_end

    @property
    def mixdown_reader(self) -> Bw64Reader:
        if self._mixdown_reader is None:
            self._mixdown_reader = Bw64Reader(self.mixdown_file_handle)

        return self._mixdown_reader

    @property
    def mixdown_file_handle(self):
        if self._mixdown_file_handle is None:
            self._mixdown_file_handle = open(self.mixdown_filename, 'rb')

        return self._mixdown_file_handle

    @property
    def mixdown_filename(self):
        if self.intermediate_filename is None:
            self.mixdown()

        return self.intermediate_filename

    @property
    def object_name(self):
        return self.sources[0].name
    
    def mixdown(self):
        with adm_object_rendering_context(self.scene) as scene:
            solo_speakers(scene, self.sources)

            scene_name = bpy.path.clean_name(scene.name)
            speaker_name = bpy.path.clean_name(self.object_name)

            self.intermediate_filename = os.path.join(self.base_dir, "%s_%s.wav" % (scene_name, speaker_name))

            bpy.ops.sound.mixdown(filepath=self.intermediate_filename,
                                  container='WAV', codec='PCM', format='S24')

            print("Created mixdown named {}".format(self.intermediate_filename))

            unmute_all_speakers(scene)

    def adm_block_formats(self, room_size=1.):
        fps = self.scene.render.fps
        block_formats = []

        for speaker_obj in self.sources:
            speaker_interval = speaker_active_time_range(speaker_obj)
            for frame in range(speaker_interval.start_frame, speaker_interval.end_frame + 1):
                self.scene.frame_set(frame)
                relative_vector = compute_relative_vector(camera=self.scene.camera, target=speaker_obj)

                norm_vec = room_norm_vector(relative_vector, room_size=room_size)

                pos = ObjectCartesianPosition(X=norm_vec.x, Y=norm_vec.y, Z=norm_vec.z)

                if len(block_formats) == 0 or pos != block_formats[-1].position:
                    jp = JumpPosition(flag=True, interpolationLength=Fraction(1, fps * 2))
                    block = AudioBlockFormatObjects(position=pos,
                                                    rtime=Fraction(frame, fps),
                                                    duration=Fraction(1, fps),
                                                    cartesian=True,
                                                    jumpPosition=jp)

                    block_formats.append(block)
                else:
                    block_formats[-1].duration = block_formats[-1].duration + Fraction(1, fps)

        return block_formats

    def rm_mixdown(self):
        if self._mixdown_reader is not None:
            self._mixdown_reader = None

        if self._mixdown_file_handle is not None:
            self._mixdown_file_handle.close()
            self._mixdown_file_handle = None

        os.remove(self.intermediate_filename)
        self.intermediate_filename = None


@contextmanager
class ObjectMixPool:
    def __init__(self, object_mixes: List[ObjectMix]):
        self.object_mixes = object_mixes

    def __enter__(self):
        return self

    @property
    def shortest_file_length(self):
        lengths = map(lambda f: len(f.mixdown_reader))
        return min(lengths)

    def __exit__(self, exc_type, exc_val, exc_tb):
        for mix in self.object_mixes:
            mix.rm_mixdown()


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


def mux_adm_from_object_mixdowns(scene, sound_objects: List['ObjectMix'], output_filename, room_size=1.):
    """
    mixdowns are a tuple of wave filename, and corresponding speaker object
    """

    object_count = len(sound_objects)
    assert object_count > 0

    out_format = FormatInfoChunk(channelCount=object_count,
                                 sampleRate=scene.render.ffmpeg.audio_mixrate,
                                 bitsPerSample=24)

    with ObjectMixPool(sound_objects) as mix_pool:
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


def generate_adm(context, filepath, room_size, max_objects):
    scene = context.scene

    object_groups, _ = partition_sounds_to_objects(scene, max_objects)

    if len(object_groups) == 0:
        return {'FINISHED'}

    sound_objects = map(lambda objects: ObjectMix(sources=objects))

    mux_adm_from_object_mixdowns(scene, list(sound_objects),
                                 output_filename=filepath,
                                 room_size=room_size)

    for o in sound_objects:
        o.rm_mixdown()

    return {'FINISHED'}
