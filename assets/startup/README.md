Place the startup animation at:

- `assets/startup/startup_loop.mp4`

Recommended export:

- `H.264 MP4`
- `1920x1080` or `1600x900`
- `24fps`
- exactly `3.0s`
- silent audio track or no audio

Visual direction:

- soft blue-gray background matching the ONCard shell
- centered logo or stacked-card motif
- simple card stack motion with one clean reveal, not busy particle effects
- no dense text baked into the video
- final frame should visually align with the main app palette so the transition feels seamless

The splash code will loop the MP4 if startup warmup takes longer than 3 seconds. If the file is missing, ONCard falls back to a static branded splash.
