import vapoursynth as vs
core = vs.core
import os, sys, io, tempfile, subprocess
from datetime import timedelta
import havsfunc as hf
import fvsfunc as fs
import muvsfunc as muf
import mvsfunc as mf
import kagefunc as kf
import nnedi3_rpow2 as nnedi3_rpow2

"""please don’t waste your time reading this"""

def cond_xpand(clip, min=4):
    mx = get_max(clip)
    matrix = [1]*4 + [0] + [1]*4
    conv = core.std.Convolution(clip, matrix, divisor=8)
    return core.std.Expr([conv, clip], f"y 0 = x {(mx // 8) * min} > {mx} 0 ? y ?")

def nnedi(clip, factor=2, w=None, h=None, kernel="spline36"):
    """5 characters > 12 characters."""
    return nnedi3_rpow2.nnedi3_rpow2(clip, factor, w, h, kernel=kernel)

def closegaps(clip):
    """this functon is most likely entirely uselss and I’m only keeping it because it took me way longer than it should have to write"""
    matrixs = [[0]*i + [1] + [0]*(8-i) for i in range(9)][1::2]
    clips = [core.std.Convolution(clip, matrix, divisor=1) for matrix in matrixs] 
    return core.std.Expr([mask] + clips + [core.std.Convolution(mask, [1]*9)], "x 30 > x y z min a min b min 10 < x c ? ?")  

def RemoveBlended(clip):
    """entirely useless except for very specific situations in which an occasional blended frame == the previous and the following frame merged together"""
    src = kgf.getY(clip)
    blended = src[-1] + core.std.Merge(src[:-2], src[2:])
    diff = core.std.PlaneStats(core.std.Expr([src, blended], "x y - abs").std.Binarize(src.format.bits_per_sample // 6))
    out = core.std.FrameEval(src, lambda n,f: src[1:] if f.props["PlaneStatsAverage"] == 0 else src, diff)
    return out

def overlayTypeset(clip, typecut_directory):
    """mainly for my personal use. the typecuts’ file names are assumed to end on “_<start frame>-<end frame>.<avi or mov>”"""
    typecuts = [entry.path for entry in os.scandir(typecut_directory) if entry.is_file() and (entry.path.endswith("avi") or entry.path.endswith("mov"))]
    for cut in typecuts:
        tc = core.ffms2.Source(cut)
        name = os.path.splitext(os.path.basename(cut))[0]
        start = int(name.split("_")[-1].split("-")[0])
        clip = fvsfunc.InsertSign(clip, tc, start, None, "709")
    return clip

def filter_squaremask(clip, filter, left=0, right=0, top=0, bottom=0):
    """entirely useless. apply filter only to area of specified square"""
    crop = core.std.Crop(clip, left, right, top, bottom)
    filtered = filter(crop)
    with_borders = filtered.std.AddBorders(left, right, top, bottom)
    mask = kgf.squaremask(clip, clip.width-left-right, clip.height-top-bottom, left, top)
    return core.std.MaskedMerge(clip, with_borders, mask)

def AverageClip(clip, image_path=None):
    """entirely useless. averages the clip to one frame"""
    src = clip.resize.Point(format=vs.YUV444PS)
    final = core.std.BlankClip(src[0])
    for i in range(src.num_frames):
        final = core.std.Expr([final, src[i]], f"y {1/src.num_frames} * x +")

    if image_path:
        out = core.resize.Point(final, format=vs.RGB24, matrix_in_s="709")
        out = core.imwri.Write(out, "PNG", image_path)
        out.get_frame(0)
    else:
        return final

def CompressToImage(srcp, image_path=None):
    """entirely useless. compresses the clip horizontally such that each column represents one frame """
    src = src[::src.num_frames // src.height]
    w1 = core.fmtc.resample(src, 1, src.height)
    frames = [w1[i] for i in range(w1.num_frames)]
    out = core.std.StackHorizontal(frames)
    if image_path:
        out = out.resize.Point(format=vs.RGB24, matrix_in_s="709")
        out = core.imwri.Write(out, "PNG",image_path)
        out.get_frame(0)
    else:
        return out

def encode(clip, output_file, **args):  
    """entirely useless except for my personal use"""
    x264_cmd = ["x264", 
                 "--demuxer",      "y4m",
                 "--preset",       "veryslow",
                 "--ref",          "16",
                 "--bframes",      "16",
                 "--crf",          "15",
                 "--aq-mode",      "3",
                 "--aq-strength",  "1",
                 "--qcomp",        "0.7",
                 "--no-fast-pskip",
                 "--psy-rd",       "0.75:0.0",
                 "--deblock",      "-1:-1",
                 "--output-csp",   "i444",
                 "--output-depth", "10",
                 "-o",             output_file,
                 "-"]  
    for i,v in args.items():
        i = "--" + i if i[:2] != "--" else i
        i = i.replace("_", "-")
        if i in x264_cmd:
            x264_cmd[x264_cmd.index(i)+1] = str(v)
        else:
            x264_cmd.extend([i,str(v)])
    
    print("x264 command: ", " ".join(x264_cmd), "\n")
    process = subprocess.Popen(x264_cmd, stdin=subprocess.PIPE)
    clip.output(process.stdin, y4m = True, progress_update = lambda value, endvalue: print(f"\rVapourSynth: {value}/{endvalue} ~ {100 * value // endvalue}% || x264: ", end=""))
    process.communicate()
    
def extract_frame(file, n, checkfps=False):
    """called by a horrible powershell script of mine because I’m too lazy actually learn the language"""
    name = os.path.splitext(os.path.basename(file))[0]
    fps = float(eval(subprocess.run(f'ffprobe -v 0 -of csv=p=0 -select_streams 0 -show_entries stream=r_frame_rate "{file}"', stdout=subprocess.PIPE).stdout.decode('utf-8').strip())) if checkfps else 24000/1001
    subprocess.check_call(f'ffmpeg -y -ss {"0" + str(timedelta(seconds=float(n)/fps))} -i "{file}" -frames:v 1 {file}_{n}.png\"', shell=True)

def preview(clip, directory=r"F:\Subbing-Raws"):
    """useless unless you insist on writing your script in some IDE/text editor and need a preview"""
    f = tempfile.NamedTemporaryFile(directory) #temp file instead of stdin so that it’s seekable
    process = subprocess.Popen(["mpv", f.name]) 
    clip.output(f, y4m = True, progress_update = lambda value, endvalue: print(f"\rVapourSynth: {value}/{endvalue} ~ {100 * value // endvalue}% || mpv: ", end=""))
    process.communicate()

def sample_extract(src):
    """returns a sample clip of 18–19 5 seconds cuts"""
    return core.std.Splice([src[x:x+5*round(src.fps)] for x in range(0, src.num_frames, src.num_frames//17)])

def assmask(clip: vs.VideoNode, vectormask: str) -> vs.VideoNode:
    """ converts an .ass clip tag to a mask"""
    bc = core.std.BlankClip(clip)
    drawing = vectormask + fr"{{\an7\bord0\shad0\pos(0,0)\p1}}m 0 0 l {clip.width} 0 {clip.width} {clip.height} 0 {clip.height}"
    return core.sub.Subtitle(bc, drawing)

def get_max(clip):
    return 1 if clip.format.sample_type == vs.FLOAT else (1 << clip.format.bits_per_sample) - 1 
