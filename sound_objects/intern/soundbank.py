import bpy

import numpy

from typing import List
from random import choice
from aud import Sound


class SoundBank:
    def __init__(self, prefix):
        self.prefix = prefix
        self.cached_info = {}

    def sounds(self) -> List[Sound]:
        return [sound for sound in bpy.data.sounds if sound.name.startswith(self.prefix)] 

    def random_sound(self) -> Sound:
        if len(self.sounds()) == 0:
            return None
        else:
            return choice(self.sounds())

    def get_audiofile_info(self, sound, fps) -> (int, int):
        """
        Returns frame of max_peak and duration in frames
        """
        
        if sound.filepath in self.cached_info.keys():
            return self.cached_info[sound.filepath]

        if sound.filepath.startswith("//"):
            path = bpy.path.abspath(sound.filepath)
        else:
            path = sound.filepath

        aud_sound = Sound(path)
        samples = aud_sound.data()
        sample_rate = aud_sound.specs[0]
        index = numpy.where(samples == numpy.amax(samples))[0][0]
        max_peak_frame = (index * fps / sample_rate)

        sample_count = aud_sound.length
        frame_length = sample_count * fps / sample_rate

        retvalue = (max_peak_frame , frame_length)
        self.cached_info[sound.filepath] = retvalue

        return retvalue