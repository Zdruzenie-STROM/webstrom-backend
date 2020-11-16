from django.urls import path
from rest_framework.routers import DefaultRouter
from competition import views


app_name = 'competition'

router = DefaultRouter()
router.register(r'problem', views.ProblemViewSet)
router.register(r'series', views.SeriesViewSet)
router.register(r'semester', views.SemesterViewSet)
router.register(r'solution', views.SolutionViewSet)


urlpatterns = [
]


urlpatterns += router.urls
