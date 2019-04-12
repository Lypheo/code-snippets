import subprocess, os
from sys import argv
from optparse import OptionParser
from datetime import timedelta

def main(args):
    opt = OptionParser(description="Simple script to facilitate the creation of typecuts with ffmpeg. Requires ffmpeg and ffprobe to be in PATH (or the cwd)", version="", usage="")
    opt.add_option("--cutname", "-c", action="store", help="Specify prefix of the typecut filenames", dest="cutname")
    opt.add_option("--jobs", "-j", action="store", help="Specify job file to iterate through. Each line of the file should specify a frame range (includes first and last; zero-based indexing) like this: 45-232", dest="jobs")
    opt.add_option("--inputfile", "-i", action="store", help="video file or vpy script to cut the typecuts from", dest="inputfile")
    option, arg = opt.parse_args(args)
    
    if not option.jobs: opt.error("job file missing, aborting…")
    if not option.inputfile: opt.error("input file missing, aborting…")
    inputfile = option.inputfile
    cutname, ext = option.cutname or os.path.splitext(os.path.basename(inputfile))

    with open(option.jobs,'r') as jobfile:
        jobqueue = jobfile.read().split("\n")
        jobqueue.remove("")

    if not os.path.isdir(f"{os.getcwd()}\\Typecuts"):
    	os.mkdir(f"{os.getcwd()}\\Typecuts")

    if ext != ".vpy":
        fps = float(eval(subprocess.run(f'ffprobe -v 0 -of csv=p=0 -select_streams 0 -show_entries stream=r_frame_rate "{inputfile}"',
        								  stdout=subprocess.PIPE).stdout.decode('utf-8').strip()))

    for job in jobqueue:
        start, end = job.split('-')
        print(f"\nStart frame: {start}\nEnd frame: {end}")

        output = os.path.join('Typecuts', f'{cutname}_{start}-{end}.mov')
        subprocess.check_call(f'ffmpeg -ss {"0" + str(timedelta(seconds=float(start)/fps))} -i "{inputfile}" -frames:v {int(end)-int(start)+1} -c:v prores_ks -profile:v 4444 -q:v 4 -pix_fmt yuv444p10le -an "{output}"' if ext != ".vpy" else
                              f'vspipe --y4m -s {start} -e {end} "{inputfile}" - | ffmpeg -i - -c:v prores_ks -profile:v 4444 -pix_fmt yuv444p10le -an -q:v 4 "{output}"', shell=True)

    print("\nDone.")

if __name__ == '__main__':
    main(argv[1:])