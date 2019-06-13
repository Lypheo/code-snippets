## stitcher.py

A simple script to facilitate re-encoding parts of videos (to fix minor filtering mistakes for instance).
Works by splicing in new clips encoded from a provided VapourSynth script.
Since cutting is only possible on keyframes, frame ranges will be extended to the nearest keyframes.
Requires vspipe, ffmpeg+ffprobe and mkvmerge.

In more detail, it works as follows:
1. Extend the given frame ranges to the nearest previous or subsequent keyframes respectively.
2. Encode the replacement clips with vspipe.
3. Use mkvmerge to cut all the parts from the source video that are to be kept.
4. Join the source clips and the replacement clips and mux the original audio.

Probably will break in various ways since 1. I can’t code for shit 2. I’ve hardly tested it at all 3. No input validation/sanitization or error handling 4. Multimedia is hell.

## typecuts.py

A simple script to automate the creation of prores typecuts for AFX.
Can use either a video file or a VapourSynth script.
