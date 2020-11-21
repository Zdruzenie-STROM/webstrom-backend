from rest_framework.routers import DefaultRouter

from cms import views

app_name = 'cms'


# Create a router and register our viewsets with it.
router = DefaultRouter()
router.register(r'post', views.PostViewSet)
router.register(r'menu-item', views.MenuItemViewSet)


urlpatterns = [

]

urlpatterns += router.urls
