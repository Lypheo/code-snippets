from subprocess import check_output, run
import os
from optparse import OptionParser
from vapoursynth import core
import shutil

def merge_intervals(l):
    out = sorted(l)
    overlaps_flat = sum(out, [])
    overlaps = zip(overlaps_flat[1:-1:2], overlaps_flat[2:-1:2])
    for j,i in enumerate(overlaps):
        if i[0] >= i[1]-1:
            lower = out[j][0]
            upper = max(out[j+1][1], out[j][1])
            out[j:j+2] = [ [lower, upper] ]
            return merge_intervals(out)
    return l

def snap(keyframes, n, bw=True):
    kf = max(filter(lambda x: x <= n, keyframes))
    return kf if bw else keyframes[keyframes.index(kf) + 1] - 1

def parse():
    parser = OptionParser(usage="py stitcher.py --base foo.mkv --vpy foo.vpy --x264-conf \"x264 <x264 parameters> \" --replace <frame ranges to replace>" ,description="""Fixes encoding mistakes by splicing in new clips encoded from the provided VapourSynth script.
                                         Since cutting is only possible on keyframes, frame ranges will be extended to the nearest previous or subsequent keyframes respectively.
                                         Requires vspipe, ffprobe and mkvmerge.
                                         Will most likely break in various ways on everything other than the video and setup I tested this with, because I can’t code for shit.""")
    parser.add_option("--base", dest="src",
                      help="base clip")
    parser.add_option("--vpy", dest="vpy",
                      help="vapoursynth script to cut the replacement clips from")
    parser.add_option("--x264-conf", dest="enc_conf",
                      help="the x264 command line to use WITHOUT the input and output options, \ne. g. \"x264.exe --preset veryfast --crf 15 --output-depth 10\"")
    parser.add_option("--replace", dest="repl",
                      help="frame ranges (inclusive, zero-indexed) to replace. \nformat: a-b[:c-d[:e-f…]], e. g. ``--replace -382:523-854`` will replace everything up to including frame 382 as well as frames 523 – 854. Omitting a frame number is evaluated as frame 0 or the last frame respectively.")

    options, args = parser.parse_args()
    for i, v in vars(options).items():
        if v == None:
            parser.error("Missing arguments. Aborting …")
        globals()[i] = v


def cut_replacement_clips(kf_cuts):
    if not os.path.exists(f"{os.getcwd()}/cuts"):
        os.mkdir(f"{os.getcwd()}/cuts")

    for start, end in kf_cuts:
        run(rf"vspipe -y -s {start} -e {end} {vpy} - | {enc_conf} --demuxer y4m - -o cuts/{start}-{end}_new.mkv", shell=True, check=True)

def cut_source_clips(kf_cuts, framecount):
    flat = sum(kf_cuts, [])
    mkvmerge_ranges =  [[1, kf_cuts[0][0] + 1]] if kf_cuts[0][0] != 0 else []
    mkvmerge_ranges += [[end+2,start+1] for end,start in zip(flat[1:-1:2], flat[2:-1:2])]
    mkvmerge_ranges += [[kf_cuts[-1][-1]+2, framecount+1]] if kf_cuts[-1][-1] != framecount-1 else []

    print(kf_cuts)
    print(mkvmerge_ranges)
    split_parameter = ",".join(["-".join(map(str,framerange)) for framerange in mkvmerge_ranges])
    run(rf"mkvmerge -A -S --output cuts/old.mkv {src} --split parts-frames:{split_parameter}", shell=True, check=True)
    for i,v in enumerate(mkvmerge_ranges):
        os.rename(f"cuts/old-{i+1:03d}.mkv", f"cuts/{v[0]-1}-{v[1]-2}_old.mkv")

def join_clips():
    files = ["cuts/" + file for file in os.listdir("cuts/")]
    files.sort(key = lambda file: int(os.path.basename(file).split("-")[0]))
    run(f"mkvmerge --output {os.path.splitext(src)[0]}_video.mkv " + " + ".join(files))

def cleanup():
    if os.path.exists(rf"{os.path.splitext(src)[0]}_video.mkv"):
        os.remove(rf"{os.path.splitext(src)[0]}_video.mkv")
    shutil.rmtree("cuts/")

def main():
    parse()

    keyframes_raw = check_output(r"ffprobe -select_streams v -show_entries frame=pkt_pts_time -of compact=p=0:nk=1 -skip_frame nokey -loglevel fatal " + src, shell=True).decode()
    keyframes = [round(float(i)*(24000/1001)) for i in keyframes_raw.split()]
    framecount = core.ffms2.Source(src).num_frames    

    cuts = [[int(j.split("-")[0] or 0), int(j.split("-")[1] or framecount-1)] for j in repl.split(":")]
    kf_cuts = [[snap(keyframes, j[0]), snap(keyframes, j[1], False)] for j in cuts]
    kf_cuts = merge_intervals(kf_cuts)

    cut_replacement_clips(kf_cuts)
    cut_source_clips(kf_cuts, framecount)
    join_clips()
    run(rf"ffmpeg -i {os.path.splitext(src)[0]}_video.mkv -i {src} -map 0:v -map 1 -map -1:v -c copy {os.path.splitext(src)[0]}_fixed.mkv -y") # mux audio
    cleanup()

if __name__ == '__main__':
    try:
        main()
    except:
        cleanup()
