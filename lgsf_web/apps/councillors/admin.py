from councillors.models import EnrichedCouncillor, ScrapedCouncillor
from django.contrib import admin


class ScrapedCouncillorAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "council_id",
        "raw_identifier",
        "raw_name",
    )
    list_filter = ("council_id",)


class EnrichedCouncillorAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "council_id",
        "ee_division_id",
        "ee_division_name",
        "ynr_party_id",
        "ynr_id",
        "ynr_name",
    )
    list_filter = ("base_councillor__council_id",)

    def council_id(self, obj):
        return obj.base_councillor.council_id


admin.site.register(ScrapedCouncillor, ScrapedCouncillorAdmin)
admin.site.register(EnrichedCouncillor, EnrichedCouncillorAdmin)
