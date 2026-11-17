"""Deploy the API to a Hugging Face Space (Docker, free CPU).

Creates the Space if needed, sets its secrets and variables from .env, and uploads only
what the Docker image needs (Dockerfile, requirements.txt, app/) plus the Space README.

    $env:HF_TOKEN = "hf_..."   # a token with write access
    python deploy/hf_space.py --space USER/resumefit-api --cors https://SITE.vercel.app
    python deploy/hf_space.py --space USER/resumefit-api --dry-run   # show, change nothing

Values read from .env:
  NEON_DATABASE_URL (secret)            -> RESUMEFIT_DATABASE_URL
  RESUMEFIT_LLM_API_KEY (secret)
  RESUMEFIT_LLM_PROVIDER/BASE_URL/MODEL/TIMEOUT_S, RESUMEFIT_FIREBASE_* (variables)
Secret values are never printed.
"""

import argparse
import os
import sys
from pathlib import Path

from huggingface_hub import CommitOperationAdd, HfApi

ROOT = Path(__file__).resolve().parent.parent
SECRETS = {"RESUMEFIT_DATABASE_URL": "NEON_DATABASE_URL", "RESUMEFIT_LLM_API_KEY": None}
VARIABLES = [
    "RESUMEFIT_LLM_PROVIDER",
    "RESUMEFIT_LLM_BASE_URL",
    "RESUMEFIT_LLM_MODEL",
    "RESUMEFIT_LLM_TIMEOUT_S",
    "RESUMEFIT_FIREBASE_PROJECT_ID",
    "RESUMEFIT_FIREBASE_API_KEY",
    "RESUMEFIT_FIREBASE_AUTH_DOMAIN",
]


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def files_to_upload() -> list[tuple[str, Path]]:
    files = [(name, ROOT / name) for name in ("Dockerfile", ".dockerignore", "requirements.txt")]
    for path in sorted((ROOT / "app").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            files.append((path.relative_to(ROOT).as_posix(), path))
    files.append(("README.md", ROOT / "deploy" / "hf-space" / "README.md"))
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--space", required=True, help="USER/NAME of the Space")
    parser.add_argument("--cors", default="", help="web front end origin(s), comma-separated")
    parser.add_argument("--admins", default="", help="admin emails, comma-separated")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env = read_env(ROOT / ".env")
    secrets = {name: env.get(source or name, "") for name, source in SECRETS.items()}
    variables = {name: env.get(name, "") for name in VARIABLES}
    variables["RESUMEFIT_CORS_ORIGINS"] = args.cors
    variables["RESUMEFIT_ADMIN_EMAILS"] = args.admins
    missing = [k for k, v in {**secrets, **variables}.items() if not v and "CORS" not in k]
    missing = [k for k in missing if k != "RESUMEFIT_ADMIN_EMAILS"]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")

    files = files_to_upload()
    print(f"Space: {args.space} (docker, public)")
    print("Secrets:", ", ".join(f"{k} (set)" for k in secrets))
    for k, v in variables.items():
        print(f"Variable: {k} = {v or '(empty)'}")
    print(f"Files: {len(files)} ({', '.join(n for n, _ in files[:3])}, app/..., README.md)")
    if args.dry_run:
        print("Dry run: nothing changed.")
        return

    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit("Set HF_TOKEN to a Hugging Face token with write access.")
    api = HfApi(token=token)
    api.create_repo(args.space, repo_type="space", space_sdk="docker", exist_ok=True)
    for key, value in secrets.items():
        api.add_space_secret(args.space, key, value)
    for key, value in variables.items():
        if value:
            api.add_space_variable(args.space, key, value)
        else:
            try:
                api.delete_space_variable(args.space, key)
            except Exception:  # not set before
                pass
    api.create_commit(
        args.space,
        repo_type="space",
        operations=[CommitOperationAdd(name, str(path)) for name, path in files],
        commit_message="Deploy ResumeFit API from GitHub main",
    )
    user, name = args.space.split("/")
    print(f"Deployed. Build log: https://huggingface.co/spaces/{args.space}")
    print(f"API URL once built: https://{user.lower()}-{name.lower()}.hf.space".replace("_", "-"))


if __name__ == "__main__":
    main()
