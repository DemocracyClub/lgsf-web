# from councillors.models import ScrapedCouncillor
from councillors.constants import ALL_COUNCILS
from councillors.importer import (
    GithubCouncillorImporter,
    GithubCouncillorImportError,
)
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Import scraped councillors into the database"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--council_id",
            type=str,
            help="The ID of the council to sync",
        )
        group.add_argument(
            "--all-councils",
            action="store_true",
            help="Sync all councils",
        )

    def get_council_ids(self):
        # TODO: get council IDs from source synced to EE
        return ALL_COUNCILS

    def handle(self, *args, **options):
        self.options = options

        try:
            importer = GithubCouncillorImporter(stdout=self.stdout)
            if options["council_id"]:
                importer.import_council(
                    council_id=options["council_id"],
                    use_git_clone=True,
                )
            else:
                for council_id in self.get_council_ids():
                    importer.import_council(
                        council_id=council_id,
                        use_git_clone=True,
                    )
        except GithubCouncillorImportError as e:
            raise CommandError(f"Council Import Failed: {e}")

        self.stdout.write("Council import completed successfully.")
