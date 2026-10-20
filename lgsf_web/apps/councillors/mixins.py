import csv

from councillors.constants import DATA_DIR
from councillors.models import ScrapedCouncillor


class CouncilMixin:
    def get_council_official_name(self) -> str:
        with open(DATA_DIR / "councils.csv") as f:
            reader = csv.DictReader(f)
            councils = {
                row["official_identifier"]: row["official_name"]
                for row in reader
            }
            return councils.get(self.council_id)

    def get_scraped_councillors(
        self,
        council_id: str,
    ) -> list[ScrapedCouncillor]:
        return ScrapedCouncillor.objects.filter(council_id=council_id)

    def get_council_divisions(self, council_id: str) -> list[dict]:
        with open(DATA_DIR / "ee_divisions.csv") as f:
            reader = csv.DictReader(f)
            return [row for row in reader if row["org_id"] == council_id]
