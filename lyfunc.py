import vapoursynth as vs
core = vs.core
import os, sys, io, tempfile, subprocess, math
from datetime import timedelta
import havsfunc as hf
import fvsfunc as fs
import muvsfunc as muf
import mvsfunc as mf
import kagefunc as kf
import nnedi3_rpow2 as nnedi3_rpow2

def sigmoid_scale(clip, w, h, filter, center=0.5, slope=6.5):
    """See: http://www.imagemagick.org/Usage/resize/#resize_sigmoidal"""
    def apply_sigmoid(x, center=center, slope=slope, inverse=False):
        MIN = 1/(1+math.exp(center*slope))
        MAX = 1/(1+math.exp(slope*(center-1)))
        if not inverse:
            sigm = 1/(1+math.exp(slope*(center-x)))
            return (sigm - MIN) / (MAX-MIN)
        else:
            xi = MIN + x*(MAX-MIN)
            return center - math.log((1-xi)/xi)/slope
    
    v = [i*(1/(65536-1)) for i in range(65536)]
    lut = [apply_sigmoid(i, center=.5, inverse=True) for i in v]
    lut_inverse = [apply_sigmoid(i, center=.5, inverse=False) for i in v]
    
    linear = core.resize.Bicubic(clip, format=vs.RGB48, transfer_in_s="709", transfer_s="linear")
    sigmoid = core.std.Lut(linear, lutf=lut, floatout=True)
    resized = filter(sigmoid, w, h, format=vs.RGB48)
    inverted_sigmoid = core.std.Lut(resized, lutf=lut_inverse, floatout=True)
    gamma = core.resize.Bicubic(inverted_sigmoid, format=clip.format, transfer_in_s="linear", transfer_s="709")
    return gamma

def text_mask(src, w=1280, h=720, thr=7, kernel='bilinear', b=1/3, c=1/3, taps=3):
    """mask particularly pesky higher-res text overlays that the usual diff + expand can’t catch"""

    thr = thr * maxvalue // 255 if src.format.sample_type == vs.INTEGER else thr / (235 - 16) 

    src_y = core.std.ShufflePlanes(src, planes=0, colorfamily=vs.GRAY)
    descaled = ff.Resize(src_y, w, h, kernel=kernel, a1=b, a2=c, taps=taps, invks=True)
    rescaled = ff.Resize(descaled, src.width, src.height, kernel=kernel, a1=b, a2=c, taps=taps)
    diff = core.std.Expr([src_y, rescaled], 'x y - abs')
    
    mask = diff.std.Binarize(thr)
    mask = closing(mask, 3)
    inpand = cond_inpand(mask, n=5, cond=17)
    black = core.std.BlankClip(inpand)
    mask = core.std.FrameEval(mask, lambda n,f: inpand if f.props.PlaneStatsAverage > 0.001 else black, core.std.PlaneStats(inpand))
    mask = dilation(mask, 25)

    return mask

def vfr(src, thresh=0.001):
    diff = core.std.PlaneStats(src[:-1], src[1:])
    duplicates = [i+1 for i,f in enumerate(diff.frames()) if f.props.PlaneStatsDiff < thresh]
            
    def collide_successive(l):
        outl = []
        c = 1
        for i in range(len(l)):
            if c != 1: 
                c -= 1
                continue

            if i+1 != len(l): 
                nxt = l[i+1]

                while nxt == l[i]+c:
                    c += 1
                    if i+c == len(l):
                        break
                    nxt = l[i+c]

                outl.append((l[i], c))
            else:
                outl.append((l[i], 1))

        return outl

    dedupe_list = collide_successive(duplicates)

    def extend_duration(n, f):
        frame = f.copy()
        frames, repetitions = zip(*dedupe_list)
        if n+1 in frames:
            frame.props._DurationNum *= repetitions[frames.index(n+1)] + 1
        return frame
        
    out = core.std.ModifyFrame(src, src, extend_duration)
    out = core.std.DeleteFrames(out, duplicates)
    
    return out

def mosaic(clip, num):
    """returns a mosaic preview frame of the clip composed of num x num frames"""
    clip = clip.resize.Spline36(format=vs.RGB48, matrix_in_s="709")
    frames = [clip[int(((clip.num_frames-1)/(num**2 - 1)) * i)].dpid.Dpid(clip.width // num, clip.height // num) for i in range(num**2)]
    horizontal = [core.std.StackHorizontal(frames[i:i+num]) for i in range(0, num**2, num)]
    return core.std.StackVertical(horizontal)

def bddiff(bd, tv, thresh):
    """returns a clip of all pairs of differing frames"""
    diff = core.std.PlaneStats(bd, tv)
    tv = core.text.FrameNum(tv).text.Text("TV", 9)
    bd = core.text.FrameNum(bd).text.Text("BD", 9)
    unchanged = [i for i,f in enumerate(diff.frames()) if f.props["PlaneStatsDiff"] < thresh]
    return core.std.Interleave([core.std.DeleteFrames(bd, unchanged), core.std.DeleteFrames(tv, unchanged)])

def diff_sort(bd, tv):
    """returns a clip of all frame pairs sorted by the magnitude of their difference. untested though ヽ( ﾟヮ・)ノ """
    diff = core.std.PlaneStats(bd, tv)
    diffs = [(f.props.PlaneStatsDiff, i) for i,f in enumerate(diff.frames())]        
    diffs.sort(key = lambda x: x[0], reverse=True)

    bd_text = core.text.FrameNum(bd).text.Text("bd", 9)
    tv_text = core.text.FrameNum(tv).text.Text("tv", 9)

    out = core.std.Splice([bd_text[d[1]].text.Text(f"Difference: {d[0]}", 2) + tv_text[d[1]].text.Text(f"Difference: {d[0]}", 2) for d in diffs])
        
    return out

def sample_extract(src, shots=18, shot_duration=5):
    """returns a sample clip of <shots> scenes of <shot_duration> seconds respectively"""
    return core.std.SelectEvery(src, src.num_frames//shots, range(0,round(src.fps*shot_duration))).std.AssumeFPS(src)

def stats(clip, clipb=None):
    return core.std.PlaneStats(clip, clipb).text.FrameProps()

def YAEM(clip, denoise=False, threshold=140):
    """                 256 > threshold > 0
    the whole function is just moronic and ridicilously slow for a halo mask. use findehalo or whatever instead"""
    y = kf.getY(clip)
    max_ = core.std.Maximum(y)
    mask = core.std.MakeDiff(max_, y)
    denoise = mf.BM3D(mask, sigma=10) if denoise else False
    conv = core.std.Convolution(denoise or mask, [1]*9)
    min_ = core.std.Minimum(mask)
    mask = core.std.Expr([mask, conv, min_], "x y < z x ?").std.Binarize(get_max(clip)*threshold/255)
    infl = mask.std.Maximum()
    return core.std.Expr([mask, infl], "y x -")

def cond_inpand(clip, n=3, cond=4):
    """1 if <cond> pixels in the nxn neighbourhood are 1, else 0"""
    max_value = get_max(clip)
    x = int((n-1)/2 * (1+n))
    y = -1 + n**2
    matrix = [1]*x + [0] + [1]*x
    conv = core.std.Convolution(clip, matrix, divisor=y)
    return core.std.Expr([conv, clip], f"x {math.floor((max_value / y) * (y-cond))} <= 0 {max_value} ? y min")

def cond_xpand(clip, n=3, cond=4):
    """expects binary clips"""
    max_value = get_max(clip)
    x = (n-1)/2 * (1+n)
    y = -1 + n**2
    matrix = [1]*x + [0] + [1]*x
    conv = core.std.Convolution(clip, matrix, divisor=y)
    return core.std.Expr([conv, clip], f"x {math.floor((max_value / y) * cond)} >= {max_value} 0 ? y max")

def nnedi(clip, factor=2, w=None, h=None, kernel="spline36"):
    """5 characters > 12 characters."""
    return nnedi3_rpow2.nnedi3_rpow2(clip, factor, w, h, kernel=kernel)

def closegaps(clip):
    """most likely entirely uselss and I’m only keeping it because it took me way longer than it should have to write"""
    matrices = [[0]*i + [1] + [0]*(8-i) for i in range(9)][1::2]
    clips = [core.std.Convolution(clip, matrix, divisor=1) for matrix in matrices] 
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
    mask = kf.squaremask(clip, clip.width-left-right, clip.height-top-bottom, left, top)
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

def CompressToImage(src, image_path=None):
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

def save_frame(clip, n):
    out = core.imwri.Write(clip[n].resize.Point(format=vs.RGBS, matrix_in_s="709"), "PNG", f"VS%d-screenshot_{n}.png")
    out.get_frame(0)

def preview(clip, directory=r"F:\Subbing-Raws", point=False):
    """useless unless you insist on writing your script in some IDE/text editor and need a preview"""
    f = tempfile.NamedTemporaryFile(dir=directory) #temp file instead of stdin so that it’s seekable
    process = subprocess.Popen(["mpv", "--scale", "oversample" if point else "ewa_lanczossharp", f.name])
    if clip.format.color_family not in [vs.YUV, vs.GRAY]:
        prev = clip.resize.Bicubic(format=vs.YUV444P16, matrix_s="709")
    else:
        prev = clip
    prev.output(f, y4m = True, progress_update = lambda value, endvalue: print(f"\rVapourSynth: {value}/{endvalue} ~ {100 * value // endvalue}% || mpv: ", end=""))
    process.communicate()

def assmask(clip: vs.VideoNode, vectormask: str) -> vs.VideoNode:
    """ converts an .ass clip tag to a mask"""
    drawing = vectormask + fr"{{\an7\bord0\shad0\pos(0,0)\p1}}m 0 0 l {clip.width} 0 {clip.width} {clip.height} 0 {clip.height}"
    c = core.sub.Subtitle(clip, drawing, blend=False)
    return c[1]

def get_max(clip):
    return 1 if clip.format.sample_type == vs.FLOAT else (1 << clip.format.bits_per_sample) - 1 


######################## morphological functions (with a square structuring element) as an alternative to the unbearably slow built-ins ################

def dilation(src, radius):
    for i in range(radius):
        src = core.std.Maximum(src)
    return src

def erosion(src, radius):
    for i in range(radius):
        src = core.std.Minimum(src)
    return src

def closing(src, radius):
    clip  = dilation(src, radius)
    clip  = erosion(clip, radius)
    return clip
    
def opening(src, radius):
    clip = erosion(src, radius)
    clip = dilation(clip, radius)
    return clip
