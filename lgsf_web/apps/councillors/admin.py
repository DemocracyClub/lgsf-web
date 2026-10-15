from councillors.models import ScrapedCouncillor
from django.contrib import admin


# Register your models here.
class ScrapedCouncillorAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "council_id",
        "raw_identifier",
        "raw_name",
    )
    list_filter = ("council_id",)


admin.site.register(ScrapedCouncillor, ScrapedCouncillorAdmin)
