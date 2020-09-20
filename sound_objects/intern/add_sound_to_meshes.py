import bpy
from numpy.linalg import norm
from random import uniform, gauss
from math import floor
from enum import Enum

from dataclasses import dataclass

import sys

from .soundbank import SoundBank


class TriggerMode(str, Enum):
    START_FRAME = "START_FRAME"
    MIN_DISTANCE = "MIN_DISTANCE"
    RANDOM = "RANDOM"
    RANDOM_GAUSSIAN = "RANDOM_GAUSSIAN"


@dataclass
class SpatialEnvelope:
    considered_range: float
    enters_range: int
    closest_range: int
    min_distance: float
    exits_range: int


def sound_camera_spatial_envelope(scene: bpy.types.Scene, speaker_obj, considered_range: float) -> SpatialEnvelope:
    min_dist = sys.float_info.max
    min_dist_frame = scene.frame_start
    enters_range_frame = None
    exits_range_frame = None

    in_range = False
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        rel = speaker_obj.matrix_world.to_translation() - scene.camera.matrix_world.to_translation()
        dist = norm(rel)

        if dist < considered_range and not in_range:
            enters_range_frame = frame
            in_range = True

        if dist < min_dist:
            min_dist = dist
            min_dist_frame = frame

        if dist > considered_range and in_range:
            exits_range_frame = frame
            in_range = False
            break

    return SpatialEnvelope(considered_range=considered_range,
                           enters_range=enters_range_frame,
                           exits_range=exits_range_frame,
                           closest_range=min_dist_frame,
                           min_distance=min_dist)


def closest_approach_to_camera(scene, speaker_object):
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


def track_speaker_to_camera(speaker, camera):
    camera_lock = speaker.constraints.new('TRACK_TO')
    camera_lock.target = bpy.context.scene.camera
    camera_lock.use_target_z = True


def spot_audio(context, speaker, trigger_mode, sync_peak, sound_peak, sound_length, gaussian_stddev, envelope):
    audio_scene_in = context.scene.frame_start
    if trigger_mode == TriggerMode.START_FRAME:
        audio_scene_in = context.scene.frame_start

    elif trigger_mode == TriggerMode.MIN_DISTANCE:
        audio_scene_in = envelope.closest_range

    elif trigger_mode == TriggerMode.RANDOM:
        audio_scene_in = floor(uniform(context.scene.frame_start, context.scene.frame_end))
    elif trigger_mode == TriggerMode.RANDOM_GAUSSIAN:
        mean = (context.scene.frame_end - context.scene.frame_start) / 2
        audio_scene_in = floor(gauss(mean, gaussian_stddev))

    target_strip = speaker.animation_data.nla_tracks[0].strips[0]

    if sync_peak:
        peak = int(sound_peak)
        audio_scene_in = audio_scene_in - peak

    audio_scene_in = max(audio_scene_in, 0)

    # we have to do this weird dance because setting a start time
    # that happens after the end time has side effects
    target_strip.frame_end = context.scene.frame_end
    target_strip.frame_start = audio_scene_in
    target_strip.frame_end = audio_scene_in + sound_length


def sync_audio(speaker, sound, context, sync_peak, trigger_mode, gaussian_stddev, sound_bank, envelope):
    print("sync_audio entered")
    fps = context.scene.render.fps

    audiofile_info = sound_bank.get_audiofile_info(sound, fps)

    spot_audio(context=context, speaker=speaker, trigger_mode=trigger_mode,
               gaussian_stddev=gaussian_stddev, sync_peak=sync_peak,
               sound_peak=audiofile_info[0], sound_length=audiofile_info[1],
               envelope=envelope)


def constrain_speaker_to_mesh(speaker_obj, mesh):
    speaker_obj.constraints.clear()
    location_loc = speaker_obj.constraints.new(type='COPY_LOCATION')
    location_loc.target = mesh
    location_loc.target = mesh


def apply_gain_envelope(speaker_obj, envelope):
    pass


def add_speakers_to_meshes(meshes, context, sound=None,
                           sound_name_prefix=None,
                           sync_peak=False,
                           trigger_mode=TriggerMode.START_FRAME,
                           gaussian_stddev=1.
                           ):
    context.scene.frame_set(0)
    sound_bank = SoundBank(prefix=sound_name_prefix)

    for mesh in meshes:
        if mesh.type != 'MESH':
            print("object is not mesh")
            continue

        envelope = sound_camera_spatial_envelope(context.scene, mesh, considered_range=5.)

        speaker_obj = next((spk for spk in context.scene.objects
                            if spk.type == 'SPEAKER' and spk.constraints['Copy Location'].target == mesh), None)

        if speaker_obj is None:
            bpy.ops.object.speaker_add()
            speaker_obj = context.selected_objects[0]

        constrain_speaker_to_mesh(speaker_obj, mesh)
        track_speaker_to_camera(speaker_obj, context.scene.camera)

        if sound_name_prefix is not None:
            sound = sound_bank.random_sound()

        if sound is not None:
            speaker_obj.data.sound = sound

            sync_audio(speaker_obj, sound, context,
                       sync_peak=sync_peak,
                       trigger_mode=trigger_mode,
                       gaussian_stddev=gaussian_stddev,
                       sound_bank=sound_bank, envelope=envelope)

            apply_gain_envelope(speaker_obj, envelope)

        speaker_obj.data.update_tag()
