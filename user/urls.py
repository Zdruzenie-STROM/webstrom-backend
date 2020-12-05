from django.contrib.auth.views import (  # LogoutView, LoginView,
    PasswordChangeDoneView,
    PasswordChangeView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView)
from django.urls import path, reverse_lazy

from user.views import LoginView, LogoutView, UserDetailsView
from user.views import UserProfileView, profile_update, register, verify

app_name = 'user'

urlpatterns = [
    # Registrácia a prihlásenie
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('details/', UserDetailsView.as_view(), name='user-details'),

    # Url ktoré neboli zatiaľ prepísané do restu.

    path('profile/update/', profile_update, name='profile-update'),
    path('profile/<int:pk>/', UserProfileView.as_view(), name='profile-detail'),

    # Obnovenie hesla
    path('password-reset/',
         PasswordResetView.as_view(
             template_name='user/password_reset.html',
             success_url=reverse_lazy('user:password-reset-done'),
             email_template_name='user/emails/password_reset.txt',
             html_email_template_name='user/emails/password_reset.html'),
         name='password-reset'),

    path('password-reset-confirm/<uidb64>/<token>/',
         PasswordResetConfirmView.as_view(
             template_name='user/password_reset_confirm.html',
             success_url=reverse_lazy('user:password-reset-complete')),
         name='password-reset-confirm'),

    path('password-reset/done/',
         PasswordResetDoneView.as_view(
             template_name='user/password_reset_done.html'),
         name='password-reset-done'),

    # Zmena hesla
    path('password-reset-complete/',
         PasswordResetCompleteView.as_view(
             template_name='user/password_reset_complete.html'),
         name='password-reset-complete'),

    path('password-change/',
         PasswordChangeView.as_view(
             template_name='user/password_change.html',
             success_url=reverse_lazy('user:password-change-done')),
         name='password-change'),

    path('password-change/done/',
         PasswordChangeDoneView.as_view(
             template_name='user/password_change_done.html'),
         name='password-change-done'),
]
