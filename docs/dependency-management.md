# Dependency management

This repository is an independent orchestration and validation project. It does
not fork, vendor, or redistribute the ViPE or Nerfstudio source trees.

## ViPE

ViPE is treated as a pinned external dependency. The GPU setup stage will:

1. clone the official `nv-tlabs/vipe` repository into `.cache/vipe/`;
2. check out an exact tested tag and commit;
3. verify the resolved commit before installation;
4. build it in a dedicated CUDA environment; and
5. use its official inference entrypoint and COLMAP conversion script.

The local `.cache/` directory is ignored by Git. The technical clone is an
installation mechanism, not a fork: upstream history and source code do not
become part of this repository.

A source checkout is preferable to an opaque unpinned package installation
because the pipeline needs ViPE's version-matched configuration, CUDA build,
CLI, and `scripts/vipe_to_colmap.py`. Pinning and commit verification keep this
reproducible without copying upstream code.

If an upstream compatibility issue requires a change, prefer a small adapter in
this repository. Any unavoidable patch must be explicit, narrowly scoped,
documented against the pinned upstream commit, and covered by validation. A
permanent fork is not the default strategy.

## Gaussian Splatting trainer

Nerfstudio Splatfacto is also an external pinned dependency and will live in a
separate environment. ViPE and Splatfacto compile different native CUDA stacks;
isolating them avoids PyTorch, toolkit, compiler, and extension ABI conflicts.

Our repository owns only the integration surface:

- dataset download and preprocessing
- environment bootstrap and revision pins
- ViPE command configuration
- COLMAP conversion and structural validation
- Splatfacto training configuration
- evaluation, camera-path generation, rendering, and artifact checks
- reproducibility documentation

Upstream projects retain their own licenses and attribution.

## Exact tested matrix

The public pins live in `configs/versions.env`:

- ViPE `v1.2.0`, commit
  `95a8816947602ddc26fcb7a80bea4f9313059578`, installed from its exact
  `uv.lock` in the upstream CUDA 12.8 environment. The setup reads ViPE's
  `.python-version` and uses a uv-managed Python distribution so native builds
  do not depend on incomplete Python headers in the base GPU image. The CUDA
  extension target is detected from `nvidia-smi` and passed through
  `TORCH_CUDA_ARCH_LIST`, which also keeps isolated native builds deterministic;
- Nerfstudio `v1.1.5`, commit
  `6b60855003011b2ca23c2fe3f8e2ca6314c69924`;
- Splatfacto Python 3.10, PyTorch 2.1.2+cu118, torchvision 0.16.2+cu118, and a
  minimal CUDA 11.8 compiler/runtime-header set for building gsplat; and
- Miniforge `26.3.2-3`, protected by its published SHA-256 checksum when a host
  does not already provide Conda.

## Package-manager policy

Python packages are installed with `uv`, not the standalone `pip` installer:

- the downloader executes pinned `gdown` with `uvx`;
- ViPE is synchronized from its upstream frozen `uv.lock` with `uv sync
  --frozen`; and
- PyTorch, compatibility pins, and the verified Nerfstudio checkout are
  installed into the isolated Splatfacto Python with `uv pip`.

The host bootstrap records a system `uv` when available or creates an isolated
Conda tool environment containing pinned `uv` 0.10.4. `uv pip` is uv's
pip-compatible command surface; it does not invoke the pip resolver. Conda is
kept for Python runtimes, CUDA compiler/runtime headers, Ninja, and pinned GCC,
where binary package management is the appropriate layer.

The validated Splatfacto compatibility pins are NumPy 1.26.4 and setuptools
80.9.0. The latter keeps `pkg_resources` available to PyTorch 2.1.2's extension
helper, while GCC/G++ 11.4 stays within CUDA 11.8's supported host-compiler
range. The gsplat CUDA backend is imported during setup so compilation failures
surface before training and the result is retained in a persistent extension
cache.

Splatfacto uses gsplat and does not require tiny-cuda-nn. Avoiding that
unnecessary native build reduces setup time and removes one common CUDA
architecture failure mode.
