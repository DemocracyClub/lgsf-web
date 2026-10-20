from councillors import views
from django.urls import path

app_name = "councillors"

urlpatterns = [
    path("", views.LandingView.as_view(), name="landing"),
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
    path(
        "compare/",
        views.CompareListView.as_view(),
        name="compare_list",
    ),
    path(
        "compare/<int:pk>/",
        views.CompareDetailView.as_view(),
        name="compare_detail",
    ),
    path(
        "summary/",
        views.CouncilSummaryListView.as_view(),
        name="summary_list",
    ),
    path(
        "summary/<str:council_id>/",
        views.CouncilSummaryDetailView.as_view(),
        name="summary_detail",
    ),
]
