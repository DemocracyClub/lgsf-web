from django.db import models


class ScrapedCouncillor(models.Model):
    council_id = models.CharField(max_length=5)
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
        constraints = [
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
    ee_division_id = models.IntegerField(null=True, blank=True)
    ee_division_name = models.CharField(max_length=255, blank=True)
    ynr_party_id = models.CharField(max_length=255, blank=True)
    ynr_party_name = models.CharField(max_length=255, blank=True)
    ynr_id = models.IntegerField(null=True, blank=True, unique=True)
    ynr_name = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.base_councillor}-Enriched"
