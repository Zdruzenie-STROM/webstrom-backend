from django.contrib import auth
from django.contrib.auth.models import (AbstractBaseUser, BaseUserManager,
                                        PermissionsMixin)
from django.core.mail import send_mail
from django.db import models
from django.utils import timezone
from rest_framework.authtoken.models import Token


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError('Používateľ musí mať nastavený email')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Admin musí mať is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Admins musí mať is_superuser=True.')

        return self._create_user(email, password, **extra_fields)

    def with_perm(self, perm, is_active=True, include_superusers=True, backend=None, obj=None):
        # pylint: disable=too-many-arguments
        if backend is None:
            # pylint: disable=protected-access
            backends = auth._get_backends(return_tuples=True)
            if len(backends) == 1:
                backend, _ = backends[0]
            else:
                raise ValueError(
                    'You have multiple authentication backends configured and '
                    'therefore must provide the `backend` argument.'
                )
        elif not isinstance(backend, str):
            raise TypeError(
                f'backend must be a dotted import path string (got {backend}).'

            )
        else:
            backend = auth.load_backend(backend)
        if hasattr(backend, 'with_perm'):
            return backend.with_perm(
                perm,
                is_active=is_active,
                include_superusers=include_superusers,
                obj=obj,
            )
        return self.none()


class User(AbstractBaseUser, PermissionsMixin):
    # pylint: disable=E1101
    # first_name = models.CharField(verbose_name='krstné meno', max_length=150)
    # last_name = models.CharField(verbose_name='priezvisko', max_length=150)

    email = models.EmailField(verbose_name='email', unique=True)
    verified_email = models.BooleanField(
        verbose_name='overený email', default=False)

    is_staff = models.BooleanField(
        verbose_name='status správcu',
        default=False,
        help_text='Umožňuje prihlásiť sa do administrácie.',)
    is_active = models.BooleanField(
        verbose_name='aktívny',
        default=True,
        help_text='Označuje, či je používateľ aktívny. '
        'Používa sa namiesto mazania účtov.',)
    date_joined = models.DateTimeField(
        'dátum registrácie', default=timezone.now)

    objects = UserManager()

    EMAIL_FIELD = 'email'
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = 'používateľ'
        verbose_name_plural = 'používatelia'

    def clean(self):
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email)

    def get_full_name(self):
        return f'{self.profile.first_name.strip()} {self.profile.last_name.strip()}'

    def get_full_name_camel_case(self):
        return f'{self.profile.first_name.strip()}{self.profile.last_name.strip()}'

    def get_short_name(self):
        return self.profile.first_name

    def email_user(self, subject, message, from_email=None, **kwargs):
        send_mail(subject, message, from_email, [self.email], **kwargs)

    def __str__(self):
        return f'{ self.get_full_name() } <{ self.email }>'


TokenModel = Token
