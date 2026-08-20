# Runtime Sources

## llama.cpp

Runtime llama.cpp for Jetson Nano is installed from:

- Project: `kreier/llama.cpp-jetson`
- Installer: `https://kreier.github.io/llama.cpp-jetson.nano/install.sh`

Install command:

    curl -fsSL https://kreier.github.io/llama.cpp-jetson.nano/install.sh | bash

Important binaries:

- `llama-cli`
- `llama-server`
- `llama-bench`

The exact `llama-server` version and SHA256 used by this project are recorded in:

- `deps/llama-server.manifest`

## sherpa-onnx

The exact sherpa-onnx upstream repository and commit are recorded in:

- `deps/sherpa-onnx.remote`
- `deps/sherpa-onnx.commit`

Local latency instrumentation is stored in:

- `patches/sherpa-onnx/latency-instrumentation.patch`

## Models

Model filenames and sizes:

- `deps/models.manifest`

Model SHA256 checksums:

- `deps/models.sha256`
