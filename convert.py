from math import ceil, floor
import ffmpeg
import sys
import os
import shutil
import json
import numpy as np
import re
from PIL import Image
from itertools import repeat
from multiprocessing import Pool
import argparse

class safeExit(object):
	def __init__(self, onExit=None):
		self.onExit = onExit

	def __enter__(self):
		pass

	def __exit__(self, exitType, _, __):
		if exitType is KeyboardInterrupt:
			if self.onExit:
				self.onExit()
			return True


def main():
	parser = argparse.ArgumentParser(description='Create webm videos with dynamic resolution.')
	parser.add_argument('input', type=ascii, nargs="?", help='input file path')
	parser.add_argument('-s', '--slow', action="store_true", default=False, help='prevent usage of multiprocessing')
	parser.add_argument('-t', "--transparent", nargs="+", type=float, help='use transparent images instead of video input. Supply VIDEO_LENGTH [FPS] [WIDTH] [HEIGHT] [LOOP]')

	args = parser.parse_args()
	if not args.input and not args.transparent:
		sys.exit("No input given!")

	if args.transparent:
		makeTransparentVideo(args.slow, *args.transparent)	
		sys.exit()

	inputFilePath = args.input
	if not re.search(r'\.(mp4|webm)$', inputFilePath):
		sys.exit("No valid input file.")
	if not os.path.exists(inputFilePath):
		sys.exit("Input file does not exist.")
	
	processVideo(inputFilePath, args.slow)

def makeTransparentVideo(slow, duration, fps=30, width=500, height=500, loop=1):
	frameCount = ceil(duration * fps * loop)

	with safeExit():
		prepare()
		info = readInstructions(width, height, duration)
		actualCount = makeTransparentImages(info, frameCount, fps, duration)

		if slow:
			createWebms(fps, actualCount, False)
		else:
			createWebmsFast(fps, actualCount, False)
		concatWebms()
		moveToOutput("out.mp4")

	cleanup()
	print("Done!")

def makeTransparentImages(info, count, fps, duration):
	imageDict = {}
	index = 0
	indexList = []
	for i in range(count):
		size = getInterpolatedSize(info, (i * (1/fps)) % duration)
		if not size in imageDict:
			imageDict[size] = index
			imagePath = f"temp/frame-{index}.png"
			image = Image.new('RGBA', size, (54, 57, 63, 0))
			image.save(imagePath, 'PNG')
			indexList.append(index)
			index += 1
		else:
			indexList.append(imageDict[size])

	with open("temp/concat.txt", "a") as file:
		for i in indexList:
			file.write(f"file frame-{i}.webm\n")

	return max(indexList)


def processVideo(inputFilePath, slow):
	probe = ffmpeg.probe(inputFilePath)
	time = float(probe['streams'][0]['duration'])
	width = probe['streams'][0]['width']
	height = probe['streams'][0]['height']
	video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
	fps = int(video_info['r_frame_rate'].split('/')[0])

	with safeExit():
		prepare()
		info = readInstructions(width, height, time)
		extractFrames(inputFilePath, fps)
		count = scaleImages(info, fps, time)

		if slow:
			createWebms(fps, count)
		else:
			createWebmsFast(fps, count)
		concatWebms()
		extractAudio(inputFilePath)
		setAudio(inputFilePath)

	cleanup()
	print("Done!")

def prepare():
	cleanup(True)
	if not os.path.exists("./temp"):
		os.mkdir("./temp")

def extractFrames(video, fps):
	print("Extracting frames...")
	ffmpeg.input(video).filter('fps', fps=str(fps)).output('temp/frame-%d.png', start_number=0).overwrite_output().run(quiet=True)

def getFrames():
	for (dirpath, dirnames, filenames) in os.walk("./temp"):
		return list(map(lambda x: x.replace(".png", ""), filenames))

def readInstructions(width, height, duration, path="./instructions.json"):
	print("Reading instructions...")
	if not os.path.exists(path):
		sys.exit("No instruction!")
	info = {}
	with open(path) as file:
		instructions = json.load(file)
		if not "keyframes" in instructions:
			sys.exit("No keyframe data")
		for kf in instructions["keyframes"]:
			if not "time" in kf:
				sys.exit("No time for keyframe")
			time = kf["time"]
			if time == "end":
				time = duration
			if not str(time).replace('.','',1).isdigit():
				sys.exit("invalid time")
			if not "time" in kf:
				sys.exit("No size for keyframe")
			size = kf["size"]
			kfWidth = None
			kfHeight = None
			try:
				if "scale" in size:
					kfWidth = int(width * float(size["scale"]))
					kfHeight = int(height * float(size["scale"]))
				if "wScale" in size:
					kfWidth = int(width * float(size["wScale"]))
				if "hScale" in size:
					kfHeight = int(height * float(size["hScale"]))
				if "width" in size:
					kfWidth = int(size["width"])
				if "height" in size:
					kfHeight = int(size["height"])	
			except:
				sys.exit("Invalid size for keyframe")
			info[time] = [kfWidth, kfHeight]
	return info

def getInterpolatedSize(info, time):
	prev, next = None, None
	for t, kf in info.items():
		if prev is None:
			prev = [t, kf]
			continue
		if next is None:
			next = [t, kf]
		if time > next[0]:
			prev = [t, kf]
			next = None
	if not next:
		sys.exit("Could not interpolate")
	mult = (time - prev[0]) / (next[0] - prev[0])
	diff = [next[1][0] - prev[1][0], next[1][1] - prev[1][1]]
	return (max(1, int(prev[1][0] + mult * diff[0])), max(1, int(prev[1][1] + mult * diff[1])))

def scaleImages(info, fps, time):
	print("Scaling images...")
	count = 0
	for i,t in enumerate(np.arange(0, time, 1/fps)):
		print(f"{i}  /  {floor(time * fps)}", end="\r")
		imagePath = f"temp/frame-{i}.png"
		if not os.path.exists(imagePath):
			sys.exit("Try to read non-existent frame image")
		img = Image.open(imagePath)
		img = img.resize(getInterpolatedSize(info, t), Image.ANTIALIAS)
		img.save(imagePath)
		count = i
	return count

def createWebms(fps, count, write=True):
	with open("temp/concat.txt", "a") as file:
		for i in range(count + 1):
			print(f"{i}  /  {int(count)}", end="\r")
			basePath = f"temp/frame-{i}"
			cmd = f"-framerate {fps} -f image2 -i {basePath}.png -c:v libvpx-vp9 -pix_fmt yuva420p {basePath}.webm"
			executeRawFfmpegCommad(cmd)
			if write:
				file.write(f"file {basePath}.webm\n")

def processSingleWebm(i, fps):
	basePath = f"temp/frame-{i}"
	cmd = f"-framerate {fps} -f image2 -i {basePath}.png -c:v libvpx-vp9 {basePath}.webm"
	executeRawFfmpegCommad(cmd)

def createWebmsFast(fps, count, write=True):
	print("Creating webm parts... (multiprocessed, do not cancel!)")
	with Pool() as pool:
		pool.starmap(processSingleWebm, zip(range(count + 1), repeat(fps)))
	if write:
		for i in range(count + 1):
			basePath = f"frame-{i}"
			with open("temp/concat.txt", "a") as file:
				file.write(f"file {basePath}.webm\n")

def concatWebms():
	print("Concatenating webms...")
	cmd = f"-f concat -safe 0 -i temp/concat.txt -c copy -y temp/out.webm"
	executeRawFfmpegCommad(cmd)

def extractAudio(video):
	print("Extracting audio...")
	cmd = f"-y -i {video} temp/audio.wav"
	executeRawFfmpegCommad(cmd)

def setAudio(video):
	print("Combining video and audio")
	cmd = f"-i temp/out.webm -i temp/audio.wav -map 0:V:0 -map 1:a:0 -c:v copy -c:a libopus -b:a 160k -f webm {getOutput(video)}"
	executeRawFfmpegCommad(cmd)

def getOutput(video):
	return video.replace(".mp4", "_resized.webm")

def moveToOutput(video):
	shutil.move("temp/out.webm", getOutput(video))

def cleanup(surpressPrint=False):
	if not surpressPrint:
		print("Cleanup...")
	if os.path.exists("./temp"):
		shutil.rmtree("./temp")

def executeRawFfmpegCommad(cmd):
	os.system("ffmpeg -hide_banner -loglevel error " + cmd)

if __name__ == "__main__":
	main()