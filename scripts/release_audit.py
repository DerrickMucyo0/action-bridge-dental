#!/usr/bin/env python3
"""Offline, value-free publication audit. Never contacts a service or edits Git.

Findings are candidates, not proof that a credential is valid or revoked. Output
contains locations/categories only; matching content is never serialized.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile


PATTERNS = {
    "aws-access-key-id": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "provider-token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|npm_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{20,})\b"),
    "jwt-shaped-token": re.compile(rb"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    "url-embedded-credential": re.compile(rb"https?://[^\s/:@]+:[^\s/@]+@"),
    "aws-secret-assignment": re.compile(rb"(?i)\b(?:aws_secret_access_key|aws_session_token)\b\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{32,}"),
}
INLINE_PASSWORD = re.compile(rb"(?i)\bpassword(?:\s|[*:]){0,8}`[^`]+`")
TRY_IT = re.compile(rb"(?i)\*\*try it:?\*\*")
NOTICE_FILES = {
    "third-party-notices.txt",
    "licenses/geist-OFL.txt",
    "licenses/plus-jakarta-sans-OFL.txt",
    "licenses/react-MIT.txt",
    "licenses/react-dom-MIT.txt",
    "licenses/react-router-MIT.txt",
    "licenses/react-router-dom-MIT.txt",
    "licenses/lucide-react-ISC.txt",
    "licenses/zod-MIT.txt",
    "licenses/scheduler-MIT.txt",
    "licenses/cookie-MIT.txt",
    "licenses/set-cookie-parser-MIT.txt",
}


def scan_bytes(data: bytes, prose: bool = False) -> list[dict]:
    """Return line/category only, even for malformed text or a real secret."""
    if b"\0" in data:
        return []
    findings = []
    for number, line in enumerate(data.splitlines(), 1):
        kinds = [name for name, pattern in PATTERNS.items() if pattern.search(line)]
        # Historical demo credentials were published as adjacent inline fields,
        # rather than as a PASSWORD assignment. Keep the heuristic explicit.
        if prose and (INLINE_PASSWORD.search(line) or TRY_IT.search(line)) and len(re.findall(rb"`[^`]+`", line)) >= 2:
            kinds.append("shared-account-inline-candidate")
        if "private-key" in kinds and not re.search(rb"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", data):
            kinds[kinds.index("private-key")] = "private-key-header-without-body-candidate"
        findings.extend({"line": number, "category": kind} for kind in kinds)
    return findings


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], input=input_bytes,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout


def audit_current(repo: Path) -> dict:
    paths = git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
    findings, text_files, binary_files = [], 0, 0
    for name in filter(None, paths):
        path = repo / name
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        if b"\0" in data:
            binary_files += 1
            continue
        text_files += 1
        findings.extend({"path": name, **item} for item in scan_bytes(data, Path(name).suffix.lower() in {".md", ".txt", ".rst"}))
    return {"scope": "tracked and nonignored untracked working-tree candidate files", "text_files": text_files,
            "binary_files_not_OCR_reviewed": binary_files, "findings": findings}


def audit_history(repo: Path) -> dict:
    rows = git(repo, "rev-list", "--objects", "--all").decode().splitlines()
    paths = {}
    for row in rows:
        oid, _, name = row.partition(" ")
        paths.setdefault(oid, name)
    request = "".join(oid + "\n" for oid in paths).encode()
    metadata = git(repo, "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)", input_bytes=request)
    blob_ids = [row.split()[0].decode() for row in metadata.splitlines() if row.split()[1] == b"blob"]
    blobs = git(repo, "cat-file", "--batch", input_bytes="".join(oid + "\n" for oid in blob_ids).encode())
    offset, text_count, binary_count, findings = 0, 0, 0, []
    for oid in blob_ids:
        end = blobs.index(b"\n", offset)
        header = blobs[offset:end].split()
        size = int(header[2])
        data = blobs[end + 1:end + 1 + size]
        offset = end + 2 + size
        if b"\0" in data:
            binary_count += 1
            continue
        text_count += 1
        items = scan_bytes(data, Path(paths[oid]).suffix.lower() in {".md", ".txt", ".rst"})
        if items:
            commits = git(repo, "log", "--all", "--format=%H", "--find-object=" + oid).decode().splitlines()
            findings.extend({"path": paths[oid], "blob": oid, "change_commits": commits, **item} for item in items)
    message_findings = []
    commits = git(repo, "rev-list", "--all").decode().splitlines()
    for oid in commits:
        message = git(repo, "log", "-1", "--format=%B", oid)
        message_findings.extend({"commit": oid, **item} for item in scan_bytes(message, True))
    return {"scope": "all locally reachable refs; no reflog, remote, unreachable objects or credential probing",
            "commits": len(commits), "unique_blobs": len(blob_ids), "text_blobs": text_count,
            "binary_blobs_not_OCR_reviewed": binary_count, "findings": findings,
            "commit_message_findings": message_findings}


def audit_archive(path: Path) -> dict:
    findings, unsafe, binaries = [], [], 0
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = {item.filename for item in members}
        duplicates = sorted(name for name, count in Counter(item.filename for item in members).items() if count > 1)
        for item in members:
            name = PurePosixPath(item.filename)
            if (name.is_absolute() or ".." in name.parts or "\\" in item.filename
                    or re.match(r"^[A-Za-z]:", item.filename) or any(ord(c) < 32 for c in item.filename)
                    or any(p.startswith(".") for p in name.parts)
                    or (item.external_attr >> 16) & 0o170000 == 0o120000):
                unsafe.append(item.filename)
            data = archive.read(item)
            if b"\0" in data:
                binaries += 1
            findings.extend({"path": item.filename, **entry} for entry in scan_bytes(data))
        missing = sorted(NOTICE_FILES - names)
        notice_manifest = Path(__file__).resolve().parents[1] / "docs/RELEASE_DEPENDENCY_NOTICES.json"
        notice_mismatches = []
        if not notice_manifest.is_file():
            notice_mismatches.append("LOCAL_TRUSTED_NOTICE_MANIFEST_MISSING")
        else:
            for entry in json.loads(notice_manifest.read_text())["entries"]:
                if entry["public_path"] in names and hashlib.sha256(archive.read(entry["public_path"])).hexdigest() != entry["sha256"]:
                    notice_mismatches.append(entry["public_path"])
        font_files = sum(name.lower().endswith((".woff", ".woff2", ".ttf", ".otf")) for name in names)
        photographic_files = sorted(name for name in names if name.lower().endswith((".jpg", ".jpeg", ".webp")))
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size,
            "files": len(members), "font_files": font_files, "photographic_files": photographic_files,
            "binary_files_not_OCR_reviewed": binaries, "unsafe_paths": unsafe, "duplicate_paths": duplicates,
            "missing_notices": missing, "notice_hash_mismatches": notice_mismatches, "findings": findings,
            "artifact_gate": "FAIL" if missing or notice_mismatches or unsafe or duplicates or findings else "PASS"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {"audit_kind": "OFFLINE_HEURISTIC_VALUE_FREE_NOT_RELEASE_AUTHORIZATION", "current": audit_current(args.repo)}
    if args.history:
        result["history"] = audit_history(args.repo)
    if args.archive:
        result["archive"] = audit_archive(args.archive)
    result["limitations"] = ["No credential validity/revocation checks", "No OCR or hidden/binary-content certification",
                             "No remote or unreachable-history scan", "Pattern matching cannot prove the absence of all secrets",
                             "Artifact notices do not establish rights to project code, branding or historical assets"]
    serialized = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized)
    print(serialized)


if __name__ == "__main__":
    main()
