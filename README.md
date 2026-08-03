# ViPE Gaussian Splatting Demo

An end-to-end, reproducible pipeline for reconstructing a scene from an image
sequence with NVIDIA ViPE and rendering a novel camera trajectory from a
Gaussian Splatting model.

## Status

The deterministic CPU-side pipeline is tested on Apple Silicon, and the full
24-frame / 2,000-step smoke profile is validated end to end on a RunPod RTX
4090. It produced ViPE/COLMAP geometry, evaluation metrics, an exported Gaussian
PLY, a rendered H.264 demo, and a checksum-backed run report. The 126-frame
quality run remains to be produced before final publication.

## Local quick start

Prerequisites: Python 3.9+, FFmpeg, Make, and `uv` for the optional dataset
download command.

```bash
make check
make download
make local-smoke
make test
```

`make local-smoke` validates and hashes the available source sequence, checks
filename indices and one-second timestamp cadence, requires at least 24 frames,
prepares the first 24 contiguous frames as a 1280-wide 1 FPS H.264 video, and
validates the decoded artifact with FFprobe. `make inspect` is the stricter
full-dataset gate and requires all 126 frames.

Generated data and manifests live under `data/` and are excluded from Git.

If Google temporarily rate-limits `gdown`, download the folder as a ZIP in the
Drive UI and extract the JPEG files into `data/raw/zavod70/`; `make inspect`
will verify that the local copy is complete before it can be used.

To prepare the complete 126-frame input at 1600 pixels wide:

```bash
make prepare-full
```

The commands can be customized without editing source files:

```bash
make local-smoke DATASET_DIR=/path/to/images SMOKE_FRAMES=32 SMOKE_WIDTH=1600
```

## Planned pipeline

1. Download and validate the provided image sequence.
2. Estimate camera intrinsics, poses, masks, and depth with ViPE.
3. Convert the ViPE artifacts to a Gaussian-Splatting-compatible dataset.
4. Train the Gaussian representation.
5. Render and encode a short novel-view trajectory.

The final RunPod workflow will expose these stages through one reviewer-facing
command:

```bash
make pipeline
```

The command will be resumable; lower-level targets will remain available for
development and diagnosis.

The source images are not redistributed by this repository. The checked-in
`configs/dataset-files.tsv` contains only the public Drive IDs, filenames, and
expected byte sizes needed to work around Google Drive's 50-file folder-list
limit and to validate resumable downloads.

## One-command CUDA pipeline

On a Linux host with an NVIDIA GPU, FFmpeg, Git, a C++ compiler, Make, and
`unzip`:

```bash
make pipeline PROFILE=smoke
make pipeline PROFILE=quality
```

`quality` is the default profile, so the final reviewer-facing command is:

```bash
make pipeline
```

Always run `smoke` first on a new host. It downloads/requires only the first 24
contiguous frames and uses 2,000 Splatfacto steps to verify the complete
integration. `quality` uses all 126 frames at
1600x1200, the full ViPE depth-alignment pipeline, and 30,000 Splatfacto steps.

Google Drive can temporarily throttle many public downloads. If that happens,
download the assignment folder as one ZIP through the Drive UI, then keep the
same pipeline command and supply the alternative form of the dataset input:

```bash
DATASET_ARCHIVE=/absolute/path/to/zavod70.zip make pipeline PROFILE=smoke
```

The ZIP must contain the 126 JPEG files at its root. Whether data comes from the
public folder or a ZIP, the strict inspection stage enforces filenames, frame
count, one-second cadence, dimensions, and hashes before CUDA work starts.

To inspect every resolved command without executing it:

```bash
make pipeline-dry-run PROFILE=quality
```

Every completed stage has a fingerprint tied to its command, configuration,
upstream revisions, inputs, and dependency-stage fingerprints. Re-running the
same command resumes verified outputs; changed or missing artifacts invalidate
the affected stage and everything downstream.

### Generated deliverables

A successful run creates ignored runtime artifacts under `runs/` and
`artifacts/<profile>/`:

- ViPE RGB, pose, intrinsics, depth, masks, and SLAM-map artifacts;
- validated COLMAP text geometry and initialization points;
- a Nerfstudio Splatfacto config and checkpoint;
- held-out evaluation metrics and renders;
- `splat/splat.ply`, the exported Gaussian representation;
- `demo.mp4`, rendered along a conservative path near observed cameras; and
- `run-report.json`, containing revisions, GPU/environment details, timings,
  metrics, validation results, checksums, and Gaussian/video metadata.

Design rationale:

- [Dataset preprocessing strategy](docs/data-preprocessing.md) explains the
  1 FPS time base, resolution choice, color conversion, intrinsics consistency,
  and validation gates.
- [Pipeline architecture](docs/architecture.md) defines the macOS/CUDA boundary
  and artifact contracts.
- [Dependency management](docs/dependency-management.md) explains why ViPE and
  Nerfstudio are pinned external dependencies rather than vendored forks.
- [RunPod execution](docs/runpod.md) defines the tested host contract, storage
  layout, smoke-first workflow, and cost-safety rules.

## Verified local result

Tested on an Apple M4 Pro running macOS 26.3.1 with Python 3.9.6 and FFmpeg
8.1.1:

- 126 source JPEGs validated at 4000x3000 pixels
- continuous indices 0001-0126 and one-second filename cadence
- complete H.264 input: 1600x1200, 1 FPS, 126 decoded frames, 126 seconds
- `yuv420p` limited-range pixel format for broad Linux/CUDA compatibility
- 130 MiB encoded video and SHA-256-backed manifests
