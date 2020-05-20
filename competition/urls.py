from django.urls import path

from competition.views import (ArchiveView, LatestSeriesProblemsView,
                               load_semester_data,
                               SemesterInvitationsLatexView,
                               SemesterPublicationView,
                               SemesterResultsLatexView, SemesterResultsView,
                               SeriesProblemsView, SeriesResultsLatexView,
                               SeriesResultsView)

app_name = 'competition'

urlpatterns = [
    # Úlohy
    path('series/<int:pk>/problems', SeriesProblemsView.as_view(),
         name='series-problems-detail'),
    path('series/latest-problems', LatestSeriesProblemsView.as_view(),
         name='latest-series-problems'),

    # Výsledky
    path('series/<int:pk>/results', SeriesResultsView.as_view(),
         name='series-results'),
    path('series/<int:pk>/results/latex', SeriesResultsLatexView.as_view(),
         name='series-results-latex'),
    path('semester/<int:pk>/results', SemesterResultsView.as_view(),
         name='semester-results'),
    path('semester/<int:pk>/results/latex', SemesterResultsLatexView.as_view(),
         name='semester-results-latex'),

    # Pozvánky
    path('semester/<int:pk>/invitations/<int:num_participants>/<int:num_substitutes>', SemesterInvitationsLatexView.as_view(),
         name='semester-invitations-latex'),
    # Publikácie
    path('semester/<int:pk>/publications',
         SemesterPublicationView.as_view(), name='semester-publications'),

    # Vedúcovské funkcie
    path('load/semester', load_semester_data, name='load-semester-data'),

    # Archív
    path('archive/', ArchiveView.as_view(),
         name='archive-view'),
]
