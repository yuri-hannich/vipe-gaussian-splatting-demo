# Pipeline architecture

The project deliberately separates portable CPU-side stages from NVIDIA
CUDA-only reconstruction stages.

```text
Google Drive JPEGs
        |
        v
inspect + hash + sequence validation       macOS / Linux
        |
        v
contiguous 1 FPS H.264 preparation         macOS / Linux
        |
        v
ViPE pose/depth/SLAM inference             Linux + NVIDIA CUDA
        |
        v
COLMAP text export + validation            Linux, portable validation
        |
        v
Nerfstudio Splatfacto training             Linux + NVIDIA CUDA
        |
        v
held-out evaluation + camera-path render   Linux + NVIDIA CUDA
```

## Why the Mac does not emulate the GPU stages

ViPE and the selected Gaussian Splatting implementation compile and execute
NVIDIA CUDA extensions. Apple MPS is not an ABI-compatible replacement. The
local workflow therefore tests data contracts and deterministic preprocessing,
while RunPod executes the same prepared MP4 and the GPU-specific stages.

## Local contract

`make local-smoke` must fail early if the sequence, timestamps, image sizes,
FFmpeg encode, decoded frame count, frame rate, pixel format, or output size is
wrong. A successful local smoke run is the handoff condition for GPU work.

## Source and dependency boundaries

The project contains its own orchestration, validation, and configuration code.
ViPE and Nerfstudio remain pinned external dependencies installed into ignored
local caches and separate environments; neither upstream source tree is
committed here.

See the detailed [dataset preprocessing strategy](data-preprocessing.md) and
[dependency management policy](dependency-management.md).

## Target execution contract

The repository exposes one top-level command:

```bash
make pipeline
```

Its defaults point to the two assignment inputs: the official pinned ViPE
source and the provided Google Drive dataset. Both values remain overridable for
testing or future datasets without editing source code.

The umbrella command executes and validates these stages:

```text
preflight -> download -> inspect -> prepare -> setup ViPE -> infer
          -> export COLMAP -> validate geometry -> setup Splatfacto
          -> train -> evaluate -> export PLY -> render -> report
```

Individual stages remain available in the CLI for debugging, but a reviewer
does not need to assemble them manually. Completed stages are resumable and tied
to input/configuration fingerprints so an interrupted RunPod session does not
silently reuse stale artifacts.

### Assignment deliverables

The repository itself is one deliverable and contains the command, source,
configuration, and documentation. A successful full run produces evidence for
the other three:

1. a verified working ViPE setup and inference artifact set;
2. a trained Gaussian Splatting checkpoint and exported `.ply` scene; and
3. a rendered demo video following a validated camera trajectory.

The final run report records revisions, environment versions, GPU details,
stage timings, validation results, metrics, and artifact checksums.
