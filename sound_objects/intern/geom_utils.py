import sys
from math import sqrt

import numpy
from numpy.linalg import norm


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