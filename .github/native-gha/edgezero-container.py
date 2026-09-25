"""Run the pinned app-CLI build against native remote compiler storage."""

import hashlib
import json
import os
import shutil
import shlex
import subprocess
import sys
import tarfile
from pathlib import Path

IMAGE = "rust:1.95.0-bookworm@sha256:4c2fd73ef19c5ef9d54bee03b06b2839a392604fbfcd578ed948b71b37c1d7fb"
workspace = Path(os.environ["GITHUB_WORKSPACE"])
state = Path(os.environ["RUNNER_TEMP"]) / "edgezero-benchmark"
evidence = Path(os.environ["RUNNER_TEMP"]) / "prospect-evidence"
name = "edgezero-benchmark-" + os.environ["GITHUB_RUN_ID"] + "-" + os.environ["PROVIDER"]
fixed = {
    "PATH": "/opt/tools:/opt/node/bin:/usr/local/cargo/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/state/home", "TMPDIR": "/tmp", "BASH_ENV": "", "ENV": "",
    "CARGO_HOME": "/state/cargo", "RUSTUP_HOME": "/state/rustup", "RUSTUP_TOOLCHAIN": "1.95.0",
    "CARGO_INCREMENTAL": "0", "RUSTC_WRAPPER": "/opt/tools/sccache",
    "GITHUB_WORKSPACE": "/workspace", "RUNNER_TEMP": "/state/tmp",
    "EDGEZERO__ACTION__ROOT": "/opt/edgezero",
    "EDGEZERO__ACTION__WORKSPACE": "/state/tmp/edgezero",
    "EDGEZERO__ACTION__OUTPUT_FILE": "/state/tmp/edgezero/outputs.env",
    "EDGEZERO__PROJECT__WORKING_DIRECTORY": "source",
    "EDGEZERO__PROJECT__RUST_TOOLCHAIN": "1.95.0",
    "EDGEZERO__APP__CLI__PACKAGE": "trusted-server-cli", "EDGEZERO__APP__CLI__BIN": "ts",
    "EDGEZERO__PROVIDER__ENV_CLEAR": "[]",
}


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def execute(command, extra=None, check=True, **kwargs):
    environment = {**fixed, **(extra or {})}
    process_env = os.environ.copy()
    docker_env = []
    inner_env = []
    for key, value in environment.items():
        if key == "ACTIONS_RUNTIME_TOKEN":
            process_env[key] = value
            docker_env.extend(["--env", key])
            inner_env.append(f'{key}="${{{key}}}"')
        else:
            inner_env.append(shlex.quote(key + "=" + value))
    script = "exec /usr/bin/env -i " + " ".join(inner_env) + ' "$@"'
    return subprocess.run(["docker", "exec", *docker_env, name, "/bin/sh", "-c",
                           script, "build", *command], env=process_env, check=check, **kwargs)


def mounts(items):
    result = []
    for source, target, readonly in items:
        result += ["--mount", f"type=bind,source={source},target={target}" + (",readonly" if readonly else "")]
    return result


def isolation():
    uid, gid = os.getuid(), os.getgid()
    if uid == 0:
        raise SystemExit("The application must run as the hosted runner's non-root user")
    return ["--platform", "linux/amd64", "--read-only", "--user", f"{uid}:{gid}",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--tmpfs", f"/tmp:rw,nosuid,nodev,uid={uid},gid={gid}"]


def check_sources():
    for source, expected in ((workspace / "application", os.environ["UPSTREAM_SHA"]),
                             (state / "source", os.environ["UPSTREAM_SHA"]),
                             (workspace / "edgezero", os.environ["ACTION_SHA"])):
        actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
        if actual != expected:
            raise SystemExit(f"Source identity changed at {source}")
        run("git", "-C", str(source), "diff", "HEAD", "--exit-code")
        untracked = subprocess.check_output(["git", "-C", str(source), "ls-files", "--others", "--exclude-standard"], text=True)
        if untracked:
            raise SystemExit(f"Unexpected source files at {source}: {untracked}")


def prepare():
    if state.exists():
        raise SystemExit("Refusing to reuse an existing build state directory")
    evidence.mkdir(parents=True, exist_ok=True)
    state.mkdir()
    for folder in ("runtime/home", "runtime/cargo", "runtime/rustup", "runtime/tmp/edgezero", "tools", "verify"):
        (state / folder).mkdir(parents=True)
    shutil.copytree(workspace / "application", state / "source", symlinks=True)
    check_sources()
    shutil.copy2(shutil.which("sccache"), state / "tools/sccache")
    shutil.copy2(workspace / "benchmark-tools/jq", state / "tools/jq")
    node = Path(shutil.which("node")).resolve().parent.parent
    (state / "node-path").write_text(str(node))
    run("docker", "pull", "--platform", "linux/amd64", IMAGE)
    run("docker", "run", "--detach", "--name", name, *isolation(), "--network", "host",
        *mounts([(workspace / "edgezero", "/opt/edgezero", True),
                 (state / "source", "/workspace/source", False), (state / "runtime", "/state", False),
                 (state / "tools", "/opt/tools", True), (node, "/opt/node", True)]),
        IMAGE, "sleep", "infinity")
    execute(["bash", "-euc", """
test ! -e /var/run/docker.sock
test -z "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-}${BORINGCACHE_API_TOKEN:-}${BORINGCACHE_CI_BROKER_FILE:-}${BENCHMARK_SECRET_SENTINEL:-}"
! tr '\\0' '\\n' < /proc/1/environ | grep -q benchmark-only-sentinel
! touch /usr/benchmark-write-check 2>/dev/null
touch /state/tmp/write-check
cp -a /usr/local/rustup/. /state/rustup/
rustup set auto-self-update disable
rustc +1.95.0 --version
cargo +1.95.0 --version
node --version
npm --version
jq --version
sccache --version
git -C /workspace/source diff --exit-code
"""])
    metadata = execute(["cargo", "+1.95.0", "metadata", "--manifest-path", "/workspace/source/Cargo.toml",
                        "--locked", "--no-deps", "--format-version", "1"], capture_output=True, text=True)
    package = next(p for p in json.loads(metadata.stdout)["packages"] if p["name"] == "trusted-server-cli")
    record = {"image": IMAGE, "action_sha": os.environ["ACTION_SHA"],
              "package": package["name"], "version": package["version"],
              "application_sha": subprocess.check_output(["git", "-C", str(workspace / "application"), "rev-parse", "HEAD"], text=True).strip()}
    if record["application_sha"] != os.environ["UPSTREAM_SHA"]:
        raise SystemExit("Application checkout differs from the pinned source")
    (evidence / "container.json").write_text(json.dumps(record, indent=2) + "\n")


def build(smoke=False):
    if os.environ["PROVIDER"] == "boringcache":
        keys = ("SCCACHE_WEBDAV_ENDPOINT", "SCCACHE_WEBDAV_KEY_PREFIX", "SCCACHE_WEBDAV_RW_MODE",
                "SCCACHE_MULTILEVEL_CHAIN", "SCCACHE_SERVER_PORT", "SCCACHE_IDLE_TIMEOUT")
        cache = {key: os.environ[key] for key in keys}
    else:
        keys = ("SCCACHE_GHA_ENABLED", "SCCACHE_GHA_VERSION", "SCCACHE_GHA_RW_MODE",
                "ACTIONS_RESULTS_URL", "ACTIONS_RUNTIME_TOKEN", "ACTIONS_CACHE_SERVICE_V2")
        cache = {key: os.environ[key] for key in keys}
        cache.update(SCCACHE_SERVER_PORT="4227", SCCACHE_IDLE_TIMEOUT="0")
    if smoke:
        command = ["bash", "-euc", """
printf 'pub fn answer() -> u32 { 42 }\\n' > /state/tmp/check.rs
sccache rustc --crate-name cache_check --crate-type rlib --emit dep-info,link --out-dir /state/tmp /state/tmp/check.rs
rm /state/tmp/libcache_check.rlib
sccache rustc --crate-name cache_check --crate-type rlib --emit dep-info,link --out-dir /state/tmp /state/tmp/check.rs
test -s /state/tmp/libcache_check.rlib
"""]
    else:
        command = ["/opt/edgezero/.github/actions/build-app-cli/scripts/build-app-cli.sh"]
    result = execute(command, cache, check=False)
    with (evidence / "container-sccache.json").open("w") as output:
        stats = execute(["sccache", "--show-stats", "--stats-format=json"], cache, check=False, stdout=output)
    stop_code = execute(["sccache", "--stop-server"], cache, check=False).returncode
    raise SystemExit(result.returncode or stats.returncode or stop_code)


def verify():
    record = json.loads((evidence / "container.json").read_text())
    artifact = state / "runtime/tmp/edgezero/edgezero-cli.tar"
    with tarfile.open(artifact) as archive:
        members = archive.getmembers()
        if sorted(m.name for m in members) != ["app-cli-meta.json", "ts"] or not all(m.isfile() for m in members):
            raise SystemExit("Unexpected artifact members")
        metadata = json.load(archive.extractfile("app-cli-meta.json"))
        if metadata != {"app-cli-package": record["package"], "app-cli-bin": "ts", "app-cli-version": record["version"]}:
            raise SystemExit("Artifact metadata differs from Cargo metadata")
    run("docker", "run", "--rm", *isolation(), "--network", "none",
        *mounts([(workspace / "edgezero", "/opt/edgezero", True),
                 (state / "tools", "/opt/tools", True), (artifact.parent, "/artifact", True),
                 (state / "verify", "/verify", False)]), IMAGE, "/usr/bin/env", "-i",
        "PATH=/opt/tools:/usr/bin:/bin", "HOME=/verify", "RUNNER_TEMP=/verify",
        "EDGEZERO__APP__CLI__ARTIFACT_DIR=/artifact", "EDGEZERO__ACTION__TOOL_ROOT=/verify/tools",
        "bash", "/opt/edgezero/.github/actions/deploy-core/scripts/download-app-cli.sh")
    binary = state / "verify/tools/bin/ts"
    record.update(binary_sha256=hashlib.file_digest(binary.open("rb"), "sha256").hexdigest(),
                  binary_bytes=binary.stat().st_size)
    (evidence / "artifact-validation.json").write_text(json.dumps(record, indent=2) + "\n")
    check_sources()


def cleanup():
    subprocess.run(["docker", "rm", "--force", name], check=False)
    if state.exists():
        shutil.rmtree(state)


if __name__ == "__main__":
    {"prepare": prepare, "build": build, "smoke": lambda: build(True), "verify": verify, "cleanup": cleanup}[sys.argv[1]]()
