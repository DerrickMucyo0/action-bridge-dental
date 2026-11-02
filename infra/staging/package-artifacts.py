#!/usr/bin/env python3
"""Create local content-addressed Lambda ZIPs and public artifact-key parameters.

Run after npm run build:lambda. This never uploads, runs AWS, or reads identity
parameters. Existing different files and symlinks are refused.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SLUGS = {"HealthFunction": "health", "CasesFunction": "cases", "CalculationsFunction": "calculations", "JobsFunction": "jobs", "JobWorkerFunction": "job-worker"}


def slug_parameter(logical):
    return logical.removesuffix("Function") + "ArtifactKey"


def no_symlinks(path):
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Refusing a symlink in an artifact path")


def zip_bundle(directory):
    no_symlinks(directory)
    if not (directory / "index.mjs").is_file():
        raise ValueError("Build each Lambda bundle before packaging")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(directory.rglob("*")):
            no_symlinks(path)
            if path.is_dir():
                continue
            if not path.is_file() or path.name.startswith(".env"):
                raise ValueError("Refusing an unexpected bundle file")
            info = zipfile.ZipInfo(path.relative_to(directory).as_posix(), (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    return buffer.getvalue()


def package(bundles, output, manifest):
    no_symlinks(output)
    # Build and validate everything before writing any output.
    prepared, parameters = {}, []
    for logical, slug in SLUGS.items():
        content = zip_bundle(bundles / slug)
        digest = hashlib.sha256(content).hexdigest()
        key = manifest["artifact_prefix"] + slug + "/" + digest + ".zip"
        prepared[output / slug / (digest + ".zip")] = content
        parameters.append({"ParameterKey": slug_parameter(logical), "ParameterValue": key})
    prepared[output / "artifact-parameters.json"] = (json.dumps(parameters, indent=2) + "\n").encode()
    for path, content in prepared.items():
        no_symlinks(path)
        if path.exists() and path.read_bytes() != content:
            raise ValueError("Existing artifact output differs; use a new output directory")
    for path, content in prepared.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open("xb") as handle:
                handle.write(content)
    return parameters


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".staging" / "artifacts")
    args = parser.parse_args()
    manifest = json.loads((HERE / "resources.json").read_text())
    try:
        package(ROOT / "backend" / ".build", args.output_dir, manifest)
    except (ValueError, OSError) as error:
        raise SystemExit("Local packaging refused: " + str(error)) from None
    print("Prepared five local ZIPs and artifact-parameters.json; no upload or identity-parameter access.")


if __name__ == "__main__":
    main()
