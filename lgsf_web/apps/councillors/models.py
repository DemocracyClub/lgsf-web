from django.db import models


class ScrapedCouncillor(models.Model):
    council = models.ForeignKey(
        "core.Council",
        on_delete=models.PROTECT,
        related_name="scraped_councillors",
    )
    photo_url = models.CharField(max_length=255)
    raw_division = models.CharField(max_length=255)
    raw_email = models.CharField(max_length=255)
    raw_identifier = models.CharField(max_length=255)
    raw_name = models.CharField(max_length=255)
    raw_party = models.CharField(max_length=255)
    url = models.CharField(max_length=255)

    def __str__(self):
        return f"{self.council_id}-{self.raw_identifier}-{self.raw_name}"

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=["raw_identifier", "raw_name"],
                name="unique_raw_identifier_raw_name",
            )
        ]


class EnrichedCouncillor(models.Model):
    base_councillor = models.OneToOneField(
        ScrapedCouncillor,
        on_delete=models.CASCADE,
        related_name="enriched",
    )

    party_match = models.ForeignKey(
        "YNRPartyMatch",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="councillors",
    )
    party_match_backend = models.CharField(max_length=255, blank=True)
    party_match_confidence = models.FloatField(null=True, blank=True)

    division_match = models.ForeignKey(
        "EEDivisionMatch",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="councillors",
    )
    division_match_backend = models.CharField(max_length=255, blank=True)
    division_match_confidence = models.FloatField(null=True, blank=True)

    name_match = models.ForeignKey(
        "YNRNameMatch",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="councillors",
    )
    name_match_backend = models.CharField(max_length=255, blank=True)
    name_match_confidence = models.FloatField(null=True, blank=True)

    @property
    def name_synonym_match(self):
        return bool(
            self.name_match_backend == "exact"
            and self.base_councillor.raw_name != self.name_match.person_name
        )

    @property
    def division_synonym_match(self):
        return bool(
            self.division_match_backend == "exact"
            and self.base_councillor.raw_division
            != self.division_match.division_name
        )

    @property
    def party_synonym_match(self):
        return bool(
            self.party_match_backend == "exact"
            and self.base_councillor.raw_party != self.party_match.party_name
        )

    def __str__(self):
        return f"{self.base_councillor}-Enriched"


class BaseMatch(models.Model):
    # Shared lookup row; per-councillor backend/confidence live on EnrichedCouncillor
    def __str__(self):
        id = getattr(self, self.id_field)
        value = getattr(self, self.value_field)
        return f"{value} ({id})"

    class Meta:
        abstract = True


class EEDivisionMatch(BaseMatch):
    enriched_field = "division_match"
    id_field = "division_id"
    value_field = "division_name"

    division_id = models.IntegerField(unique=True)
    division_name = models.CharField(max_length=255, blank=True)


class YNRPartyMatch(BaseMatch):
    enriched_field = "party_match"
    id_field = "party_id"
    value_field = "party_name"

    party_id = models.CharField(max_length=255, unique=True)
    party_name = models.CharField(max_length=255, blank=True)


class YNRNameMatch(BaseMatch):
    enriched_field = "name_match"
    id_field = "person_id"
    value_field = "person_name"

    person_id = models.IntegerField(unique=True)
    person_name = models.CharField(max_length=255, blank=True)
