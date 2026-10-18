from councillors.models import ScrapedCouncillor
from django.views.generic import DetailView, ListView


class ScrapedCouncillorListView(ListView):
    model = ScrapedCouncillor


class ScrapedCouncillorDetailView(DetailView):
    model = ScrapedCouncillor
