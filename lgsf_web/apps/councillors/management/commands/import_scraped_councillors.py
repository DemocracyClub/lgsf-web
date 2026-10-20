# from councillors.models import ScrapedCouncillor
from core.models import Council
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

    def get_councils(self):
        return Council.objects.all()

    def handle(self, *args, **options):
        self.options = options

        try:
            importer = GithubCouncillorImporter(stdout=self.stdout)
            if options["council_id"]:
                importer.import_council(
                    council=options["council_id"],
                    use_git_clone=True,
                )
            else:
                for council in self.get_councils():
                    importer.import_council(
                        council=council,
                        use_git_clone=True,
                    )
        except GithubCouncillorImportError as e:
            raise CommandError(f"Council Import Failed: {e}")

        self.stdout.write("Council import completed successfully.")
