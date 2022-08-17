# stupid_webm_fuckery

Wanna make discord go crazy? Try this

# Instructions

To determine how the video should be resized, define the `instructions.json` file

# Example

`pip install requirements.txt` + ffmpeg installed

```
python convert.py matrix_medium.mp4
```

for more help use `python convert.py -h`

## Creating videos without source

-   has no audio or relevant video

```
python convert.py -t DURATION FPS(default: 30) WIDTH(default:500) HEIGHT(default:500) LOOP_COUNT(default:1)
```
