import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from councillors.github import GithubAPIClient
from councillors.models import ScrapedCouncillor
from django.conf import settings
from django.db import transaction


class GithubCouncillorImportError(Exception):
    """Custom exception for GithubCouncillorImporter errors."""


class GithubCouncillorImporter:
    """
    Handles importing scraped councillors from a GitHub repository.

    Uses the GitHub API with a personal access token to download
    all files from a repository's default branch.
    """

    def __init__(
        self,
        organisation: str = settings.GITHUB_ORGANISATION,
        github_token: str = settings.GITHUB_API_TOKEN,
        stdout=sys.stdout,
    ):
        self.stdout = stdout
        self.gh_client = GithubAPIClient(
            organisation=organisation,
            github_token=github_token,
            stdout=stdout,
        )

    def import_council(
        self,
        council_id: str,
        use_git_clone: bool = True,
    ):
        """
        Import councillors for the specified council.

        Args:
            use_git_clone: Whether to use git clone to download the repository

        Raises:
            GithubCouncillorImportError: If there are issues with importing councillors
        """
        repo_name = f"{council_id.upper()}"

        if not self.gh_client.repo_exists(repo_name):
            raise GithubCouncillorImportError(
                f"Repository {repo_name} does not exist in {self.gh_client.organisation} "
            )

        self.stdout.write(f"Starting import for repository {repo_name}")
        with TemporaryDirectory() as tmp_dir:
            target_dir = Path(tmp_dir) / repo_name
            council_repo_dir = self.sync_council_repo(
                target_dir,
                repo_name,
                use_git_clone,
            )

            councillor_json_files = list(council_repo_dir.rglob("*.json"))

            if not councillor_json_files:
                raise GithubCouncillorImportError(
                    f"No councillor JSON files found in repository {repo_name}"
                )
            councillor_json_data = []
            for json_file in councillor_json_files:
                self.parse_councillor_json(councillor_json_data, json_file)
            self.stdout.write(
                f"Found {len(councillor_json_data)} councillor JSON files."
            )
            councillors_to_save = []
            for json_data in councillor_json_data:
                councillor = ScrapedCouncillor(
                    council_id=council_id,
                    photo_url=json_data.get("photo_url") or "",
                    raw_division=json_data.get("raw_division") or "",
                    raw_email=json_data.get("email") or "",
                    raw_identifier=json_data.get("raw_identifier") or "",
                    raw_name=json_data.get("raw_name") or "",
                    raw_party=json_data.get("raw_party") or "",
                    url=json_data.get("url") or "",
                )
                councillors_to_save.append(councillor)

            with transaction.atomic():
                ScrapedCouncillor.objects.bulk_create(
                    councillors_to_save,
                    update_conflicts=True,
                    update_fields=[
                        "photo_url",
                        "raw_division",
                        "raw_email",
                        "raw_party",
                        "url",
                    ],
                    unique_fields=["raw_identifier", "raw_name"],
                )

    def sync_council_repo(
        self,
        target_dir: Path,
        repo_name: str,
        use_git_clone: bool,
    ) -> Path:
        if use_git_clone:
            self.gh_client.sync_repository_git_clone(target_dir, repo_name)
        else:
            self.gh_client.sync_repository(target_dir, repo_name)
        return target_dir

    def parse_councillor_json(self, councillor_json_data, json_file):
        with open(json_file, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                councillor_json_data.append(data)
            except json.JSONDecodeError:
                raise GithubCouncillorImportError(
                    f"Invalid JSON in file {json_file}"
                )
