# Dataset preprocessing strategy

This document explains the preprocessing decisions that turn the supplied
ordered JPEG sequence into a deterministic ViPE input. The choices are part of
the reconstruction contract rather than incidental media conversion settings.

## Interpreting the input

The dataset contains 126 DJI JPEG images named from
`dji_20250111171148_0001_v.jpg` to
`dji_20250111171353_0126_v.jpg`. Both the sequence indices and filename
timestamps are continuous. Consecutive timestamps differ by exactly one
second, so the capture is treated as a 1 FPS image sequence.

It is not an original 30 FPS video: no intermediate frames exist between the
supplied photographs. The generated MP4 is a deterministic transport format
for ViPE, not an attempt to synthesize missing motion.

## Why use an MP4

ViPE accepts both video files and image directories. Its image-directory stream
currently assigns a fixed 30 FPS time base. That would describe adjacent images
as approximately 33 milliseconds apart even though this capture is one second
apart. ViPE uses time in processing decisions such as keyframe and instance
segmentation spacing, so an incorrect time base is not merely a playback issue.

The baseline therefore encodes exactly one source image as one video frame at
1 FPS. We retain the original JPEGs as immutable source material and validate
the decoded MP4 before it can enter the GPU pipeline.

## Why downscale from 4000x3000

The 12-megapixel originals are unnecessarily expensive for an initial
reconstruction: they increase decode time, intermediate tensor sizes, depth-map
storage, Gaussian training time, and peak VRAM. Several ViPE components also
operate at lower internal resolutions, so full-resolution input does not imply
full-resolution geometric inference.

The current profiles preserve the source 4:3 aspect ratio:

| Profile | Frames | Resolution | Purpose |
| --- | ---: | ---: | --- |
| Smoke | first 24 contiguous frames | 1280x960 | fast contract and environment validation |
| Full | all 126 frames | 1600x1200 | baseline reconstruction input |

The full profile reduces the pixel count by 6.25x while retaining useful roof,
wall, and vegetation detail. Higher-resolution quality profiles can be tested
after the baseline completes within the selected GPU budget.

## Camera-intrinsics consistency

Resizing changes focal length and principal-point coordinates in pixel units.
The baseline avoids manual intrinsics scaling: ViPE processes the 1600x1200
MP4, and its COLMAP converter exports the corresponding decoded frames together
with intrinsics for that same resolution. Those converter-exported images will
be used for baseline Gaussian Splatting training.

Training with the original 4000x3000 JPEGs would require scaling every camera
intrinsic by the exact image scale. Mixing resolutions without this adjustment
would silently damage the reconstruction.

## Encoding contract

The generated input uses:

- H.264 via `libx264`
- constant 1 FPS
- CRF 18 and the slow preset
- Lanczos resizing
- 1600x1200 for the full profile
- limited-range `yuv420p`
- stripped source metadata

Full-range JPEG input can otherwise be tagged as deprecated `yuvj420p` by
FFmpeg. The pipeline explicitly maps full-range JPEG values to limited-range
`yuv420p` for consistent Linux decoder behavior.

MP4 encoding is lossy, so the JPEGs remain the source of truth. CRF 18 is the
baseline quality/runtime tradeoff; a lossless or image-directory comparison is
an optional experiment if ViPE pose quality indicates compression sensitivity.

## Validation gates

The preprocessing stage fails before GPU work if any contract is violated. It
checks:

- expected JPEG naming convention
- continuous and unique frame indices
- one-second timestamp cadence
- identical image dimensions
- expected full-dataset count of 126
- per-file sizes and SHA-256 hashes matched against the tracked golden inventory
- decoded MP4 frame count
- exact average frame rate
- even output dimensions
- `yuv420p` pixel format
- output video SHA-256 and FFprobe metadata

The verified local baseline contains 126 decoded frames, lasts 126 seconds, and
is approximately 130 MiB. The manifests and generated media are intentionally
excluded from Git.
