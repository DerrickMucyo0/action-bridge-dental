#!/usr/bin/env python3
"""Package an already-built static frontend locally; never upload or publish.

The caller builds with the five reviewed public variables. This packaging gate
rejects wrapped build directories, symlinks, dotfiles, maps and credential files.
The deployment ZIP is suitable for Amplify's presigned manual upload, preserving
the private artifact bucket's ACL-disabled configuration.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

PUBLIC = {"VITE_API_BASE_URL": "https://l52iwors8c.execute-api.us-east-2.amazonaws.com/staging",
          "VITE_COGNITO_CLIENT_ID": "7uotveip0c7k931lv2te275fjg", "VITE_COGNITO_REGION": "us-east-2",
          "VITE_BACKGROUND_JOBS_ENABLED": "false", "VITE_PUBLIC_ACCOUNT_ACTIONS_ENABLED": "false"}
EXTENSIONS = {".html", ".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico",
              ".woff", ".woff2", ".ttf", ".txt", ".webmanifest"}


def package(dist, output):
    if output.exists():
        raise ValueError("Output exists; refusing to overwrite a reviewed frontend package")
    if dist.is_symlink() or not (dist / "index.html").is_file():
        raise ValueError("Expected a plain build directory with root index.html")
    files = []
    bundle = b""
    for path in sorted(dist.rglob("*")):
        relative = path.relative_to(dist)
        if path.is_symlink() or any(part.startswith(".") for part in relative.parts):
            raise ValueError("Symlink or dotfile in build output")
        if path.is_dir():
            continue
        if path.suffix.lower() not in EXTENSIONS:
            raise ValueError("Unexpected build file type: " + str(relative))
        data = path.read_bytes()
        if re.search(rb"(?:AKIA|ASIA)[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", data):
            raise ValueError("Possible credential material in build output")
        if path.suffix == ".js":
            bundle += data
        files.append((relative.as_posix(), data))
    for key in ("VITE_API_BASE_URL", "VITE_COGNITO_CLIENT_ID"):
        if PUBLIC[key].encode() not in bundle:
            raise ValueError("Bundle is not built for the reviewed staging API/client")
    # Check the actual application configuration object emitted by Vite, including
    # every public binding, rather than an unrelated "false" elsewhere in JS.
    bindings = [("apiBaseUrl", PUBLIC["VITE_API_BASE_URL"]), ("cognitoClientId", PUBLIC["VITE_COGNITO_CLIENT_ID"]),
                ("cognitoRegion", PUBLIC["VITE_COGNITO_REGION"]), ("backgroundJobsEnabled", "false"),
                ("publicAccountActionsEnabled", "false")]
    pattern = rb"\{\s*" + rb"\s*,\s*".join(
        rb'["\']?' + key.encode() + rb'["\']?\s*:\s*["\']' + re.escape(value.encode()) + rb'["\']'
        for key, value in bindings) + rb"\s*\}"
    if not re.search(pattern, bundle):
        raise ValueError("Cannot prove background jobs and public account actions are disabled in the actual bundle")
    output.mkdir(parents=True)
    destination = output / "frontend.zip"
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in files:
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 27, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    manifest = {"status": "LOCAL_PACKAGE_ONLY_NOT_PUBLISHED", "public_build_configuration": PUBLIC,
                "file_count": len(files), "zip_bytes": destination.stat().st_size,
                "zip_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                "files": [{"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in files]}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("web/dist"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package(args.dist.resolve(), args.output.resolve()), indent=2))
