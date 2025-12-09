# Dockerfile for building V8 12.8.374 with View8 patches
# OPTIMIZED: ccache + parallel builds + layer caching
FROM --platform=linux/amd64 ubuntu:22.04 AS v8-base

ENV DEBIAN_FRONTEND=noninteractive
# Use all available cores for ninja
ENV NINJA_JOBS=8

# Install dependencies with ccache for faster rebuilds
RUN apt-get update && apt-get install -y \
    git curl python3 python3-pip pkg-config \
    build-essential clang lld ninja-build \
    libglib2.0-dev libatomic1 ccache \
    && rm -rf /var/lib/apt/lists/*

# Configure ccache
ENV CCACHE_DIR=/ccache
ENV PATH="/usr/lib/ccache:${PATH}"
ENV CC="ccache clang"
ENV CXX="ccache clang++"

# Install depot_tools (cached layer)
RUN git clone --depth 1 https://chromium.googlesource.com/chromium/tools/depot_tools.git /opt/depot_tools
ENV PATH="/opt/depot_tools:${PATH}"

WORKDIR /v8-build

# Clone V8 12.8.374 (cached layer - rarely changes)
RUN git clone --depth 1 --branch 12.8.374 https://chromium.googlesource.com/v8/v8.git .

# Create .gclient and sync (cached layer)
RUN echo 'solutions = [{"name": ".", "url": "https://chromium.googlesource.com/v8/v8.git@12.8.374", "deps_file": "DEPS", "managed": False}]' > .gclient
RUN gclient sync --shallow --no-history -D

# --- Patches stage (changes more often) ---
FROM v8-base AS v8-patched

# Copy and apply patches (only patch script needed here)
COPY Disassembler/patch_v8.py /v8-build/
RUN python3 /v8-build/patch_v8.py

# --- Build stage ---
FROM v8-patched AS v8-build

# Mount ccache for faster rebuilds
RUN --mount=type=cache,target=/ccache \
    mkdir -p out.gn/x64.release && \
    printf '%s\n' \
    'dcheck_always_on = false' \
    'is_component_build = false' \
    'is_debug = false' \
    'target_cpu = "x64"' \
    'use_custom_libcxx = false' \
    'v8_monolithic = true' \
    'v8_use_external_startup_data = false' \
    'v8_static_library = true' \
    'v8_enable_disassembler = true' \
    'v8_enable_object_print = true' \
    'v8_enable_pointer_compression = true' \
    'v8_enable_sandbox = false' \
    'use_sysroot = false' \
    'treat_warnings_as_errors = false' \
    'cc_wrapper = "ccache"' \
    > out.gn/x64.release/args.gn

# Generate build files
RUN gn gen out.gn/x64.release

# Build with ccache and parallel jobs
RUN --mount=type=cache,target=/ccache \
    ninja -j${NINJA_JOBS} -C out.gn/x64.release v8_monolith

# Compile v8dasm with V8 12.x flags (requires C++20)
# COPY SOURCE HERE - so changes don't invalidate V8 build
COPY Disassembler/v8dasm.cpp /v8-build/
RUN clang++ v8dasm.cpp -g -std=c++20 -Iinclude \
    -Lout.gn/x64.release/obj \
    -lv8_libbase -lv8_libplatform -lv8_monolith \
    -lpthread -ldl -o v8dasm \
    -DV8_COMPRESS_POINTERS

# Final stage - minimal image with just v8dasm
FROM ubuntu:22.04 AS final
RUN apt-get update && apt-get install -y libatomic1 && rm -rf /var/lib/apt/lists/*
COPY --from=v8-build /v8-build/v8dasm /usr/local/bin/
CMD ["v8dasm"]
