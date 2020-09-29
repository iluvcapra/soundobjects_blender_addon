import os
import bpy
from contextlib import contextmanager
from fractions import Fraction
from typing import List

from ear.fileio.adm.elements import ObjectCartesianPosition, JumpPosition, AudioBlockFormatObjects
from ear.fileio.bw64 import Bw64Reader

from .geom_utils import speaker_active_time_range, compute_relative_vector, room_norm_vector
from .speaker_utils import solo_speakers, unmute_all_speakers


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
    def sample_rate(self):
        return self.mixdown_reader.sampleRate

    @property
    def bits_per_sample(self):
        return self.mixdown_reader.bitdepth

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

        if self.intermediate_filename is not None:
            os.remove(self.intermediate_filename)
            self.intermediate_filename = None


class ObjectMixPool:

    def __init__(self, object_mixes: List[ObjectMix]):
        self.object_mixes = object_mixes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for mix in self.object_mixes:
            mix.rm_mixdown()

    @property
    def shortest_file_length(self):
        lengths = map(lambda f: len(f.mixdown_reader), self.object_mixes)
        return min(lengths)


def object_mixes_from_source_groups(groups: List[List[bpy.types.Speaker]], scene, base_dir):
    mixes = []
    for group in groups:
        mixes.append(ObjectMix(sources=group, scene=scene, base_dir=base_dir))

    return mixes
