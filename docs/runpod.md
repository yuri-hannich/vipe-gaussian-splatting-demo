# RunPod execution

The CUDA stages are designed for one fresh RunPod GPU Pod with two isolated
software environments. The complete smoke pipeline was validated on a Secure
Cloud NVIDIA GeForce RTX 4090 with 24 GB VRAM. The repository never requires a
RunPod account key at runtime; infrastructure creation and stopping remain
outside the public ML pipeline.

## Pod configuration

The validation host uses an official RunPod PyTorch image based on Ubuntu 24.04
and CUDA 12.8. A suitable starting image is:

```text
runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404
```

Validated smoke configuration and recommended minimums:

- one NVIDIA GPU with 24 GB VRAM;
- 20 GB container disk;
- 50 GB persistent Pod volume mounted at `/workspace`;
- public SSH enabled; and
- Secure Cloud for the validated configuration (Community Cloud is also viable
  when a healthy 24 GB GPU is available).

The `/workspace` volume holds the repository, source dataset, pinned dependency
checkouts, environments, checkpoints, and deliverables. Stop or delete it soon
after copying the final artifacts: stopped local volumes continue to incur
storage charges.

The host bootstrap verifies Linux, NVIDIA access, FFmpeg/FFprobe, Git, Make,
`g++`, `unzip`, and SHA-256 tooling. It uses an image-provided Conda when
available; otherwise it installs a checksum-pinned Miniforge under the ignored
project cache.

## Execution

Clone or copy the repository to `/workspace/vipe-gaussian-splatting-demo`, then:

```bash
cd /workspace/vipe-gaussian-splatting-demo
make pipeline PROFILE=smoke
```

Only after every smoke gate passes:

```bash
make pipeline PROFILE=quality
```

If Google throttles the public folder, upload the Drive UI ZIP to the persistent
volume and run:

```bash
DATASET_ARCHIVE=/workspace/input/zavod70.zip make pipeline PROFILE=smoke
```

This is still the same dataset input. The archive path only changes the
transport; the checked-in Drive inventory and source-sequence validator enforce
the same 126-file contract.

The default downloader does not rely on a single folder-list request. It uses
the checked-in file inventory, tries Drive's public content endpoint first,
falls back to pinned `gdown`, validates every byte size, and reuses already
validated files after interruption. The ZIP path remains a manual escape hatch
for account-wide or regional Drive outages.

## Local lifecycle automation

`scripts/runpod_pipeline.sh` offers an optional local control plane around the
same provider-independent pipeline. After copying `.env.runpod.example` to the
ignored `.env.runpod`, run:

```bash
make runpod-dry-run
make runpod
```

The account API key remains only in the local launcher environment. It is used
by `runpodctl` to query the balance and create, inspect, stop, or delete the Pod;
it is never added to Pod environment variables or SSH commands. The Pod clones
the exact pushed Git revision, so a cloud run cannot silently include local
uncommitted files.

The launcher places both a stop deadline and a later termination deadline on
the resource. An unsuccessful run stops and retains the Pod for diagnosis by
default. A successful run downloads and independently verifies the reported
artifacts before deleting the Pod and its attached Pod volume. The ignored
`.runpod/active.env` records the Pod ID when manual recovery is required.

## Cost safety

GPU prices and availability change. Query the live catalog immediately before
creating a Pod rather than copying a historical rate from a README.

Use these controls for a budgeted run:

1. dry-run and unit-test locally before provisioning;
2. choose the least expensive viable 24 GB GPU;
3. install an external or in-Pod hard-stop watchdog before setup;
4. run the 24-frame smoke profile first;
5. stop at the first failed validation and diagnose CPU-side issues while the
   Pod is stopped;
6. use the stage fingerprints instead of repeating successful setup/inference;
7. copy final artifacts off the Pod; and
8. stop compute and delete unneeded local storage.

RunPod bills Pods per second. Container and local-volume storage are billed
separately; consult the current official [Pod pricing](https://docs.runpod.io/pods/pricing)
and [storage documentation](https://docs.runpod.io/pods/storage/types) before a
new run.

## Environment boundary

ViPE and Splatfacto intentionally do not share Python, PyTorch, or CUDA native
extensions:

| Stage | Upstream | Python/PyTorch/CUDA |
| --- | --- | --- |
| ViPE | v1.2.0, exact commit pin | upstream `uv.lock`, PyTorch 2.9.0, CUDA 12.8 |
| Splatfacto | Nerfstudio v1.1.5, exact commit pin | Python 3.10, PyTorch 2.1.2, minimal CUDA 11.8 build set |

A modern NVIDIA driver supports both toolkit runtimes. Keeping their packages
separate prevents compiler and extension ABI conflicts. Splatfacto uses gsplat
and does not require the tiny-cuda-nn extension used by other Nerfstudio models.
ViPE's Python version is taken from the pinned upstream checkout and installed
as a uv-managed runtime; the Conda environment supplies CUDA and native build
tools only. Shared bootstrap tooling pins uv 0.10.4; there is no standalone pip
installation path in the pipeline.

## Smoke validation result

The complete 24-frame / 2,000-step profile produced all four assignment-facing
deliverables on an RTX 4090:

- ViPE registration for all 24 frames and 54,599 validated COLMAP points;
- an evaluated Splatfacto checkpoint with PSNR 17.03, SSIM 0.328, and LPIPS
  0.701 (smoke metrics only, not the final quality target);
- an exported 79.4 MB PLY containing 320,109 finite Gaussians; and
- a 34-frame H.264 render at 1280x960 plus a checksum-backed JSON run report.

Measured stage timings are recorded in the generated report. Setup takes longer
on a cold volume because the two intentionally isolated PyTorch stacks and the
gsplat CUDA extension must be installed once; subsequent stage execution is
resumable and reuses the persistent caches.

## Quality validation result

The complete 126-frame profile was also validated on an RTX 4090:

- ViPE registered all 126 frames and the COLMAP gate accepted 319,311 points;
- the evaluated recovery checkpoint produced PSNR 16.795, SSIM 0.3859, and
  LPIPS 0.4178 on the interval holdout split;
- the exported 1.47 GB PLY contains 5,943,740 finite Gaussians; and
- the demo contains 218 H.264 frames at 1600x1200 over 9.17 seconds.

The quality profile targets 30,000 total Splatfacto steps. The validated run
was interrupted and reached a 32,000-step save boundary during recovery before
evaluation. The current train wrapper computes `target - checkpoint_step` on
resume and exits successfully when the latest checkpoint is already at or past
the target. This avoids interpreting `--max-num-iterations` as another complete
training budget after `--load-dir`.

The exact PLY, video, metrics, and report are published in the
[quality-v1 release](https://github.com/yuri-hannich/vipe-gaussian-splatting-demo/releases/tag/quality-v1).
