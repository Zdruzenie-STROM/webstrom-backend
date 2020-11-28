from rest_framework.routers import DefaultRouter

from competition import views

app_name = 'competition'

router = DefaultRouter()
router.register(r'competition', views.CompetitionViewSet)
router.register(r'problem', views.ProblemViewSet)
router.register(r'series', views.SeriesViewSet)
router.register(r'semester', views.SemesterViewSet)
router.register(r'solution', views.SolutionViewSet)
router.register(r'event', views.EventViewSet)
router.register(r'publication', views.UnspecifiedPublicationViewSet)
router.register(r'semester-publication', views.SemesterPublicationViewSet)

urlpatterns = []

urlpatterns += router.urls
