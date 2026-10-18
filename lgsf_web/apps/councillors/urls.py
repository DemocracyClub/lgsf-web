from councillors import views
from django.urls import path

app_name = "councillors"

urlpatterns = [
    path(
        "scraped/",
        views.ScrapedCouncillorListView.as_view(),
        name="scraped_list",
    ),
    path(
        "scraped/<int:pk>/",
        views.ScrapedCouncillorDetailView.as_view(),
        name="scraped_detail",
    ),
    path(
        "enriched/",
        views.EnrichedCouncillorListView.as_view(),
        name="enriched_list",
    ),
    path(
        "enriched/<int:pk>/",
        views.EnrichedCouncillorDetailView.as_view(),
        name="enriched_detail",
    ),
]
