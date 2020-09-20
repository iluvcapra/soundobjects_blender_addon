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
