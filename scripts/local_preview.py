#!/usr/bin/env python3
"""Build RITSO plus sibling ontology sites onto one local host and serve them.

Published layout is mirrored under http://127.0.0.1:8080/:
  /ritso/
  /ontology-import-foaf/
  /ontology-its-core-v1/
  ...

Cross-links use {{ site_base }} (or hard-coded https://isotc204.org mesh URLs),
rewritten for the local host during preview builds only.
"""

from __future__ import annotations

import argparse
import http.server
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "catalog" / "ontologies.yml"
PREVIEW_DIR = ROOT / ".local-preview"
DEFAULT_PORT = 8080
PLACEHOLDER = "{{ site_base }}"
PUBLISH_HOST = "https://isotc204.org"

# Mesh paths that should point at the local preview host.
MESH_PATH_RE = re.compile(
    r"https://isotc204\.org/(ritso(?:/[^\"'\\s)\\]]*)?|ontology-[^\"'\\s)\\]]*)"
)
SITE_URL_RE = re.compile(r"(?m)^site_url:\s*.*$")


def _parse_scalar(raw: str):
    value = raw.strip()
    if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
        return value[1:-1]
    if value.lower() in {"true", "yes"}:
        return True
    if value.lower() in {"false", "no"}:
        return False
    return value


def load_catalog(path: Path) -> dict:
    """Parse the small catalog YAML without requiring PyYAML."""
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "sites" in data:
            return data
    except Exception:
        pass

    publish_host = PUBLISH_HOST
    local = f"http://127.0.0.1:{DEFAULT_PORT}"
    sites: list[dict] = []
    current: dict | None = None

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("publish_host:"):
            publish_host = str(_parse_scalar(stripped.split(":", 1)[1]))
            continue
        if stripped.startswith("local_host:"):
            local = str(_parse_scalar(stripped.split(":", 1)[1]))
            continue
        if stripped == "sites:":
            continue
        if stripped.startswith("- "):
            if current:
                sites.append(current)
            current = {}
            rest = stripped[2:]
            if ":" in rest:
                key, val = rest.split(":", 1)
                current[key.strip()] = _parse_scalar(val)
            continue
        if current is not None and ":" in stripped:
            key, val = stripped.split(":", 1)
            current[key.strip()] = _parse_scalar(val)

    if current:
        sites.append(current)

    if not sites:
        raise SystemExit(f"Invalid catalog (no sites): {path}")
    return {
        "publish_host": publish_host,
        "local_host": local,
        "sites": sites,
    }


def local_host(catalog: dict, port: int) -> str:
    host = catalog.get("local_host") or f"http://127.0.0.1:{port}"
    # Allow overriding port while keeping host from catalog when ports match pattern.
    if port != DEFAULT_PORT:
        return f"http://127.0.0.1:{port}"
    return host.rstrip("/")


def publish_host(catalog: dict) -> str:
    return (catalog.get("publish_host") or PUBLISH_HOST).rstrip("/")


def substitute_mesh(text: str, site_base: str) -> str:
    text = text.replace(PLACEHOLDER, site_base)

    def _repl(match: re.Match[str]) -> str:
        return f"{site_base}/{match.group(1)}"

    return MESH_PATH_RE.sub(_repl, text)


def rewrite_file(path: Path, site_base: str, site_url: str | None = None) -> str | None:
    """Rewrite mesh URLs in place. Returns original text if changed, else None."""
    if not path.is_file():
        return None
    original = path.read_text(encoding="utf-8")
    updated = substitute_mesh(original, site_base)
    if site_url is not None:
        if SITE_URL_RE.search(updated):
            updated = SITE_URL_RE.sub(f"site_url: {site_url}", updated, count=1)
        else:
            updated = f"site_url: {site_url}\n{updated}"
    if updated == original:
        return None
    path.write_text(updated, encoding="utf-8")
    return original


def resolve_mkdocs() -> list[str]:
    mkdocs = shutil.which("mkdocs")
    if mkdocs:
        return [mkdocs]
    # Fall back to the interpreter that can import mkdocs.
    return [sys.executable, "-m", "mkdocs"]


def run_mkdocs_build(repo: Path, site_dir: Path) -> None:
    site_dir.parent.mkdir(parents=True, exist_ok=True)
    if site_dir.exists():
        shutil.rmtree(site_dir)
    cmd = resolve_mkdocs() + ["build", "--clean", "-d", str(site_dir)]
    subprocess.run(cmd, cwd=repo, check=True)


def parse_only(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {part.strip() for part in value.split(",") if part.strip()}


def selected(path_name: str, only: set[str] | None) -> bool:
    if only is None:
        return True
    return path_name in only


def write_root_index(preview_dir: Path, site_base: str) -> None:
    preview_dir.mkdir(parents=True, exist_ok=True)
    target = f"{site_base}/ritso/"
    (preview_dir / "index.html").write_text(
        f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url={target}">
  <title>RITSO local preview</title>
</head>
<body>
  <p>Local ontology preview. Continue to <a href="{target}">RITSO</a>.</p>
</body>
</html>
""",
        encoding="utf-8",
    )


def collect_rewrite_targets(repo: Path) -> list[Path]:
    targets = [
        repo / "mkdocs.yml",
        repo / "mkdocs.common.yml",
        repo / "top-nav.yml",
    ]
    docs = repo / "docs"
    if docs.is_dir():
        targets.extend(sorted(docs.rglob("*.md")))
    return [p for p in targets if p.is_file()]


def build_ritso(site_base: str, only: set[str] | None) -> bool:
    if not selected("ritso", only):
        print("Skipping ritso (--only filter)")
        return False

    dest = PREVIEW_DIR / "ritso"
    print(f"Building ritso -> {dest}")
    try:
        with tempfile.TemporaryDirectory(prefix="preview-ritso-") as tmp:
            work = Path(tmp) / "src"
            shutil.copytree(ROOT, work, ignore=_ignore_for_preview_copy)
            # Avoid copying a nested previous preview into the build tree.
            nested = work / ".local-preview"
            if nested.exists():
                shutil.rmtree(nested)
            for path in collect_rewrite_targets(work):
                rewrite_file(
                    path,
                    site_base=site_base,
                    site_url=f"{site_base}/ritso/" if path.name == "mkdocs.yml" else None,
                )
            strip_git_revision_plugin(work / "mkdocs.yml")
            tmp_site = Path(tmp) / "site"
            run_mkdocs_build(work, tmp_site)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(tmp_site, dest)
        print("  ok: ritso")
        return True
    except subprocess.CalledProcessError as exc:
        print(f"  FAILED ritso build (exit {exc.returncode})", file=sys.stderr)
        return False
    except Exception as exc:  # noqa: BLE001 - surface and continue
        print(f"  FAILED ritso: {exc}", file=sys.stderr)
        return False


def _ignore_for_preview_copy(_dir: str, names: list[str]) -> set[str]:
    skip = {
        ".git",
        ".github",
        ".vscode",
        ".cursor",
        ".idea",
        ".local-preview",
        "site",
        "venv",
        ".venv",
        "__pycache__",
        ".DS_Store",
        "node_modules",
        "ReqView",
    }
    return {name for name in names if name in skip or name.endswith(".pyc")}


def strip_git_revision_plugin(mkdocs_yml: Path) -> None:
    """Drop git-revision-date-localized when building from a copy without .git."""
    text = mkdocs_yml.read_text(encoding="utf-8")
    # Remove list entries for the plugin in either short or mapping form.
    updated = re.sub(
        r"(?m)^([ \t]*-[ \t]*git-revision-date-localized(?:[ \t]*:[ \t]*.*)?\n"
        r"(?:[ \t]+[^\n]*\n)*)",
        "",
        text,
    )
    if updated != text:
        mkdocs_yml.write_text(updated, encoding="utf-8")


def build_ontology(
    site: dict,
    parent_dir: Path,
    site_base: str,
    only: set[str] | None,
) -> bool:
    path_name = site["path"]
    if not site.get("enabled", True):
        print(f"Skipping {path_name} (disabled in catalog)")
        return False
    if not selected(path_name, only):
        print(f"Skipping {path_name} (--only filter)")
        return False

    repo_name = site["repo"]
    repo = parent_dir / repo_name
    if not repo.is_dir():
        print(f"WARNING: missing checkout for {path_name}: {repo}", file=sys.stderr)
        return False
    if not (repo / "mkdocs.yml").is_file():
        print(f"WARNING: no mkdocs.yml in {repo}", file=sys.stderr)
        return False

    dest = PREVIEW_DIR / path_name
    print(f"Building {repo_name} -> {dest}")
    try:
        # Copy into a temp tree so sibling working copies are never modified.
        with tempfile.TemporaryDirectory(prefix=f"preview-{path_name}-") as tmp:
            work = Path(tmp) / "src"
            shutil.copytree(repo, work, ignore=_ignore_for_preview_copy)
            for path in collect_rewrite_targets(work):
                rewrite_file(
                    path,
                    site_base=site_base,
                    site_url=f"{site_base}/{path_name}/"
                    if path.name == "mkdocs.yml"
                    else None,
                )
            strip_git_revision_plugin(work / "mkdocs.yml")
            common = work / "mkdocs.common.yml"
            if common.is_file():
                strip_git_revision_plugin(common)

            tmp_site = Path(tmp) / "site"
            run_mkdocs_build(work, tmp_site)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(tmp_site, dest)
        print(f"  ok: {path_name}")
        return True
    except subprocess.CalledProcessError as exc:
        print(
            f"  FAILED {path_name} build (exit {exc.returncode})",
            file=sys.stderr,
        )
        return False
    except Exception as exc:  # noqa: BLE001 - surface and continue
        print(f"  FAILED {path_name}: {exc}", file=sys.stderr)
        return False


def serve(preview_dir: Path, host: str, port: int) -> None:
    if not preview_dir.is_dir():
        raise SystemExit(f"Preview directory missing: {preview_dir}. Run a build first.")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(preview_dir), **kwargs)

    print(f"Serving {preview_dir} at http://{host}:{port}/")
    print(f"Open http://{host}:{port}/ritso/")
    with socketserver.TCPServer((host, port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--parent-dir",
        type=Path,
        default=ROOT.parent,
        help="Directory containing sibling ontology checkouts (default: ..)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Local preview port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--bind",
        default="127.0.0.1",
        help="Address to bind the preview server (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="Comma-separated path names to build (e.g. ritso,ontology-its-core-v1)",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve an existing .local-preview build without rebuilding",
    )
    parser.add_argument(
        "--build-only",
        action="store_true",
        help="Build sites but do not start the HTTP server",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove .local-preview before building",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    catalog = load_catalog(CATALOG_PATH)
    site_base = local_host(catalog, args.port)
    only = parse_only(args.only)

    if args.serve:
        serve(PREVIEW_DIR, args.bind, args.port)
        return 0

    if args.clean and PREVIEW_DIR.exists():
        shutil.rmtree(PREVIEW_DIR)

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    write_root_index(PREVIEW_DIR, site_base)

    built = 0
    if build_ritso(site_base, only):
        built += 1

    for site in catalog.get("sites") or []:
        if build_ontology(site, args.parent_dir.resolve(), site_base, only):
            built += 1

    print(f"Built {built} site(s) into {PREVIEW_DIR}")
    print(f"Publish host reference: {publish_host(catalog)}")
    print(f"Local site base: {site_base}")

    if args.build_only:
        return 0 if built else 1

    if built == 0 and not (PREVIEW_DIR / "ritso").exists():
        print("Nothing to serve.", file=sys.stderr)
        return 1

    serve(PREVIEW_DIR, args.bind, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
