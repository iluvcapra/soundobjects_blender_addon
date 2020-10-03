# soundobjects Blender Add-On

This add-on adds three operators for working with immersive 3D audio.

## `import_test.wav_file_batch`

**Import WAV Files:** This operator allows you to add multiple audio files to a .blend file so they'll be available to
the *Add Sounds to Meshes* operator.

## `object.add_speakers_to_obj`

**Add Sounds to Meshes:** This operator takes all the selected objects in the current scene and attaches a new speaker 
locked to that object's location throughout the animation. You provide the prefix for the name of a set of sound files
added with the _Import WAV Files_ operator, and these are added to each selected object randomly. The sounds can be 
timed to either begin playing at the beginning of the sequence, at a random time, or when the respective object is
closest to the scene's camera.

## `export.adm_wave_file`

**Export ADM Wave File:** This operator exports all of the speakers in a scene as an ADM Broadcast-WAV file compartible
with a Dolby Atmos rendering workflow. This produces a multichannel WAV file with embedded ADM metadata the passes
panning information to the client. (Has been tested and works with Avid Pro Tools 2020).


