# ViPE Gaussian Splatting Demo

An end-to-end reconstruction pipeline that turns the supplied ordered drone
images into a validated Gaussian Splatting scene and a rendered camera-path
video.

The repository owns the data validation, deterministic preprocessing, ViPE
orchestration, COLMAP conversion checks, Splatfacto training, evaluation,
export, rendering, and provenance report. NVIDIA
[ViPE](https://github.com/nv-tlabs/vipe) and Nerfstudio
[Splatfacto](https://docs.nerf.studio/nerfology/methods/splat.html) remain
pin-verified external dependencies.

## Assignment deliverables

| Requirement | Produced evidence |
| --- | --- |
| Working ViPE setup | pinned CUDA environment, inference artifacts, and stage log |
| Gaussian Splatting result | trained checkpoint and `artifacts/quality/splat/splat.ply` |
| Public repository | this repository, including scripts, tests, and design rationale |
| End-to-end demo | `artifacts/quality/demo.mp4` and checksum-backed run report |

The source images and generated artifacts are intentionally excluded from Git.
Final large artifacts are published separately in the
[quality-v2 GitHub Release](https://github.com/yuri-hannich/vipe-gaussian-splatting-demo/releases/tag/quality-v2).

## One-command reproduction

Use a Linux machine with an NVIDIA GPU. The clean-room validation target is a
RunPod Pod with:

- NVIDIA RTX 4090 or another CUDA GPU with at least 24 GB VRAM;
- `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`;
- 20 GB container disk;
- at least 50 GB mounted at `/workspace`; and
- public SSH enabled.

Clone the repository under the mounted volume and run:

```bash
git clone https://github.com/yuri-hannich/vipe-gaussian-splatting-demo.git
cd vipe-gaussian-splatting-demo
make pipeline
```

`quality` is the default profile, so this is equivalent to:

```bash
make pipeline PROFILE=quality
```

The command downloads both assignment inputs from their public sources,
installs isolated pinned environments, validates every intermediate contract,
trains the Gaussian model, evaluates it, exports the PLY, renders the demo, and
writes the final report. No RunPod API key or other secret is required by the
repository.

Expect a cold run to download approximately 1.1 GB of source images and two
intentional PyTorch/CUDA stacks. Keep the clone under `/workspace` so
environments, dependency caches, checkpoints, and outputs use the mounted
volume rather than the smaller container disk.

## Optional: launch RunPod from your local machine

The manual GPU-host path above is provider-independent. As a convenience, this
repository can also manage the complete RunPod lifecycle from macOS or Linux
and return the deliverables to the local clone.

Install the official [RunPod CLI](https://docs.runpod.io/runpodctl/overview) and
run `runpodctl doctor` once so the account has a usable SSH key. Then:

```bash
cp .env.runpod.example .env.runpod
# Add RUNPOD_API_KEY to the private .env.runpod file.

make runpod-dry-run
make runpod
```

`make runpod` performs a clean-room run:

1. requires a clean commit already pushed to the public origin;
2. shows the profile, GPU, storage, balance, and safety deadlines;
3. creates a fresh Pod without sending the account API key into it;
4. clones and checks out the exact local commit from GitHub;
5. starts the same `make pipeline` command as a reconnectable remote job;
6. downloads artifacts, logs, and stage records into the local clone;
7. validates PLY/video hashes and metadata against `run-report.json`; and
8. deletes the successful Pod and its Pod volume unless configured otherwise.

The launcher installs no Python packages locally. It requires Bash, Git,
Python 3, SSH, rsync, and `runpodctl`. `.env.runpod`, local launcher state, and
all downloaded artifacts are ignored by Git. On failure, the Pod is stopped and
retained for diagnosis by default; the independent termination deadline still
prevents indefinite storage retention. All behavior is configurable in the
commented `.env.runpod.example` template.

## Smoke before quality

For a new GPU type or modified dependency pin, first verify the same complete
pipeline with the bounded profile:

```bash
make pipeline PROFILE=smoke
```

| Profile | Frames | ViPE input | Splatfacto steps | Purpose |
| --- | ---: | ---: | ---: | --- |
| `smoke` | 24 | 1280x960 at 1 FPS | 2,000 | integration and CUDA gate |
| `quality` | 126 | 1600x1200 at 1 FPS | 30,000 | assignment deliverables |

The smoke profile has been validated end to end on an RTX 4090: all 24 cameras
registered, the COLMAP export contained 54,599 points, and the exported PLY
contained 320,109 finite Gaussians. Smoke metrics are an integration signal,
not the final quality claim.

## Validated quality result

The full 126-frame profile is validated from a clean RTX 4090 Pod at the exact
tagged revision. The downloadable
[quality-v2 release](https://github.com/yuri-hannich/vipe-gaussian-splatting-demo/releases/tag/quality-v2)
contains the PLY, video, metrics, and schema-v2 run report from that one-command
run. The report is the source of truth for exact metrics, revisions, stage
timings, media metadata, and SHA-256 digests.

The quality contract is all 126 registered cameras, a 1600x1200 ViPE/COLMAP
scene, 30,000 total Splatfacto iterations, interval-held-out evaluation, a
schema-validated binary Gaussian PLY, and a 218-frame H.264 trajectory render.
Nerfstudio checkpoint filenames contain the zero-based last completed step, so
resume subtracts `checkpoint_step + 1` from the iteration target.

Visual inspection shows stable camera motion, coherent building/terrain
geometry, and strong view agreement. Thin leafless branches and vegetation
remain the main source of blur and floaters, as expected from the scene content
and incomplete view coverage. Metrics use Nerfstudio's interval holdout split
and should not be compared directly with results using different splits,
resolutions, or preprocessing.

## Pipeline

```text
public JPEG sequence
        |
        v
download -> inspect -> deterministic 1 FPS MP4
        |
        v
ViPE pose / depth / masks / SLAM map
        |
        v
COLMAP export -> structural and geometry validation
        |
        v
Splatfacto train -> evaluate -> export PLY -> render MP4
        |
        v
checksum-backed run-report.json
```

Every stage writes a log and a fingerprinted completion record. Re-running the
same command resumes outputs only when its command, relevant configuration,
inputs, dependencies, and recorded output signatures still match. Splatfacto
resume steps are counted toward the configured total training target.

Inspect the resolved stage plan without executing it:

```bash
make pipeline-dry-run PROFILE=quality
```

## Outputs

A successful quality run creates:

```text
runs/quality/
  vipe/                         ViPE RGB, pose, depth, mask, and SLAM artifacts
  colmap/zavod70/               validated cameras, images, and points3D
  nerfstudio/                   config and checkpoints
  logs/                         one log per pipeline stage

artifacts/quality/
  evaluation/                   held-out comparison renders
  metrics.json                  PSNR, SSIM, LPIPS, and throughput
  splat/splat.ply               exported Gaussian representation
  demo.mp4                      rendered observed-trajectory interpolation
  run-report.json               revisions, host, timings, checksums, validation
```

The report is the machine-readable acceptance record. It requires every
preceding stage record, finite typed evaluation metrics, the exact Splatfacto
PLY schema and payload length, the configured video profile, and SHA-256/size
metadata for the PLY, metrics, and video. The report stage writes its own stage
record immediately after taking this pre-report provenance snapshot.

## Dataset download fallback

The checked-in `configs/dataset-files.tsv` contains the 126 public Drive file
IDs, filenames, expected sizes, and golden SHA-256 digests. Downloading files individually avoids
Google Drive's folder-list limit. Each file first uses Drive's public content
endpoint, falls back to pinned `gdown` through `uvx`, verifies both size and
digest, and retries without discarding already validated files.

If Drive still rate-limits a clean run, download the provided folder as a ZIP
through the Drive UI and run the same pipeline with a transport override:

```bash
DATASET_ARCHIVE=/workspace/input/zavod70.zip make pipeline
```

The ZIP must contain the assignment JPEGs. The same filename, count, cadence,
dimension, and hash validation runs regardless of transport.

## Local development

CPU-side preprocessing and tests also run on macOS:

```bash
make check
make download
make local-smoke
make verify
```

`make local-smoke` validates the available contiguous sequence and creates the
bounded 24-frame ViPE input without attempting CUDA inference. Run `make
inspect` for the strict 126-frame assignment gate. Apple MPS cannot replace the native
CUDA extensions used by ViPE and gsplat, so reconstruction remains Linux +
NVIDIA only.

## Reproducibility

- Exact upstream tags and commits live in `configs/versions.env`.
- ViPE installs from its upstream frozen `uv.lock`.
- Splatfacto uses an isolated Python 3.10 / PyTorch 2.1.2+cu118 environment.
- Python packages are installed with `uv`; Conda is reserved for runtimes,
  CUDA compiler/runtime headers, Ninja, and pinned GCC/G++.
- Source checkouts and environments live under ignored `.cache/`; they are
  installation dependencies, not vendored forks.
- Source media, generated data, checkpoints, and artifacts are ignored.

See:

- [dataset preprocessing rationale](docs/data-preprocessing.md)
- [pipeline architecture and contracts](docs/architecture.md)
- [dependency and CUDA environment policy](docs/dependency-management.md)
- [RunPod configuration and cost controls](docs/runpod.md)

## License and upstream projects

The original orchestration code in this repository is MIT licensed. ViPE,
Nerfstudio, gsplat, PyTorch, and their transitive dependencies retain their own
licenses. Review the pinned upstream repositories before redistributing their
code or model artifacts.
