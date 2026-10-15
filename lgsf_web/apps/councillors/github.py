import shutil
import subprocess
import sys
from pathlib import Path

import requests
from django.conf import settings


class GithubAPIClient:
    """
    A client for interacting with github repos via the GitHub API
    """

    def __init__(
        self,
        organisation: str = settings.GITHUB_ORGANISATION,
        github_token: str = settings.GITHUB_API_TOKEN,
        stdout=sys.stdout,
    ):
        self.organisation = organisation
        self.github_token = github_token
        self.session = self._create_session()
        self.stdout = stdout

    def _create_session(self) -> requests.Session:
        """Create and configure the GitHub API session."""
        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "LGSF-Sync/1.0",
            }
        )
        return session

    def repo_exists(self, repo_name: str) -> bool:
        """Check if a repository exists in the organisation."""
        url = f"https://api.github.com/repos/{self.organisation}/{repo_name}"
        try:
            response = self.session.get(url, timeout=30)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def get_default_branch(self, repo_name: str) -> str:
        """Get the default branch of a repository."""
        url = f"https://api.github.com/repos/{self.organisation}/{repo_name}"
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.json().get("default_branch", "main")
        except requests.RequestException:
            return "main"

    def get_tree(self, repo_name: str, branch: str = "main") -> list[dict]:
        """
        Get the full file tree from a repository.

        Args:
            repo_name: The repository name
            branch: The branch to get the tree from

        Returns:
            List of file objects with path, type, and sha
        """
        url = f"https://api.github.com/repos/{self.organisation}/{repo_name}/git/trees/{branch}?recursive=1"
        try:
            response = self.session.get(url, timeout=60)
            response.raise_for_status()
            data = response.json()
            # Filter to only include blobs (files), not trees (directories)
            return [
                item for item in data.get("tree", []) if item["type"] == "blob"
            ]
        except requests.RequestException as e:
            self.stdout.write(f"Failed to get tree for {repo_name}: {e}")
            return []

    def get_repo_url(self, repo_name: str) -> str:
        """Get the URL of a repository."""
        return f"https://x-access-token:{self.github_token}@github.com/{self.organisation}/{repo_name}.git"

    def download_file(self, repo_name: str, file_path: str) -> bytes | None:
        """
        Download a file's contents from a repository.

        Args:
            repo_name: The repository name
            file_path: Path to the file within the repository

        Returns:
            File contents as bytes, or None if download failed
        """
        url = f"https://api.github.com/repos/{self.organisation}/{repo_name}/contents/{file_path}"
        try:
            response = self.session.get(url, timeout=60)
            response.raise_for_status()
            data = response.json()

            # GitHub returns base64-encoded content for small files
            if "content" in data:
                import base64

                return base64.b64decode(data["content"])

            # For larger files, we need to download from the raw URL
            if data.get("download_url"):
                raw_response = self.session.get(
                    data["download_url"], timeout=120
                )
                raw_response.raise_for_status()
                return raw_response.content

            return None
        except requests.RequestException as e:
            self.stdout.write(f"Failed to download {file_path}: {e}")
            return None

    def sync_repository(
        self,
        target_dir: Path,
        repo_name: str,
    ) -> dict:
        """
        Sync all files from a repository to a local directory.

        Args:
            repo_name: The repository name (usually council code)
            target_dir: Local directory to sync files to
            show_progress: Whether to show progress during sync

        Returns:
            Dict with sync statistics
        """

        stats = {
            "files_downloaded": 0,
            "files_skipped": 0,
            "errors": 0,
            "total_bytes": 0,
        }

        # Get the default branch
        branch = self.gh_client.get_default_branch(repo_name)

        # Get file tree
        files = self.gh_client.get_tree(repo_name, branch)
        if not files:
            return {"skipped": True, "reason": "no_files"}

        # Filter non-JSON files
        data_files = [f for f in files if f["path"].startswith("json")]

        if not data_files:
            return {"skipped": True, "reason": "no_data_files"}

        # Clean target directory
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        # Download files
        for file_info in data_files:
            file_path = file_info["path"]
            content = self.gh_client.download_file(repo_name, file_path)
            if content is not None:
                local_path = target_dir / file_path
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_bytes(content)
                stats["files_downloaded"] += 1
                stats["total_bytes"] += len(content)
            else:
                stats["errors"] += 1

        return stats

    def sync_repository_git_clone(
        self,
        target_dir: Path,
        repo_name: str,
    ) -> dict:
        """
        Sync a repository using shallow git clone.

        This is faster than the API method and avoids rate limits.
        Only fetches the latest state of the default branch (no history).

        Args:
            repo_name: The repository name (usually council code)
            target_dir: Local directory to sync files to
        Returns:
            Dict with sync statistics
        """

        repo_url = self.get_repo_url(repo_name)

        # Clean target directory
        if target_dir.exists():
            shutil.rmtree(target_dir)

        # Create parent directory
        target_dir.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Shallow clone with depth=1 (only latest commit, no history)
            cmd = [
                "git",
                "clone",
                "--depth",
                "1",
                "--single-branch",
                repo_url,
                str(target_dir),
            ]

            self.stdout.write(f"Cloning {repo_name}...")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )

            if result.returncode != 0:
                raise requests.RequestException(
                    f"Git clone failed for repository {repo_name}: {result.stderr}"
                )

            # Remove .git directory to save space and avoid confusion
            git_dir = target_dir / ".git"
            if git_dir.exists():
                shutil.rmtree(git_dir)

            # Remove README.md and other non-data files
            for filename in ["README.md", "LICENSE", ".gitignore"]:
                filepath = target_dir / filename
                if filepath.exists():
                    filepath.unlink()

            # Count files and calculate size
            files_count = 0
            total_bytes = 0
            for file_path in target_dir.rglob("*"):
                if file_path.is_file():
                    files_count += 1
                    total_bytes += file_path.stat().st_size

            return {
                "files_downloaded": files_count,
                "total_bytes": total_bytes,
                "errors": 0,
                "method": "git",
            }

        except subprocess.TimeoutExpired:
            return {"skipped": True, "reason": "git_timeout"}
        except FileNotFoundError:
            return {"skipped": True, "reason": "git_not_installed"}
        except Exception as e:  # noqa: BLE001
            return {"skipped": True, "reason": f"git_error: {str(e)[:100]}"}
