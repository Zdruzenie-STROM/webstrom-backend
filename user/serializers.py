from allauth.account.adapter import get_adapter
from allauth.account.models import EmailAddress
from allauth.account.utils import setup_user_email, user_pk_to_url_str
from dj_rest_auth.serializers import PasswordResetSerializer
from django.contrib.auth import authenticate, get_user_model
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django_typomatic import ts_interface
from django.utils.translation import gettext_lazy
from rest_framework import exceptions, serializers

from competition.models import Grade
from personal.models import Profile
from personal.serializers import ProfileCreateSerializer
from user.models import TokenModel
from webstrom.settings import EMAIL_ALERT, EMAIL_NO_REPLY


def reset_password_url_generator(request, user, temp_key):
    uid = user_pk_to_url_str(user)
    host = request.META.get('HTTP_X_FORWARDED_HOST', 'localhost:3000')
    return f'{request.scheme}://{host}/strom/reset-password/{temp_key}/{uid}'


class FrontendPasswordResetSerializer(PasswordResetSerializer):
    def get_email_options(self):
        return {
            'url_generator': reset_password_url_generator
        }

    def create(self, validated_data):
        pass

    def update(self, instance, validated_data):
        pass


@ts_interface(context='user')
class LoginSerializer(serializers.Serializer):
    # pylint: disable=W0223
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(style={'input_type': 'password'})

    def authenticate(self, **kwargs):
        return authenticate(self.context['request'], **kwargs)

    def _validate_email(self, email, password):
        user = None

        if email and password:
            user = self.authenticate(email=email, password=password)
        else:
            msg = '"email" a "heslo" musia byť vyplnené.'
            raise exceptions.ValidationError(msg)

        return user

    def get_auth_user(self, email, password):
        return self._validate_email(email, password)

    def validate_auth_user_status(self, user):
        if not user.is_active:
            msg = 'Používateľ nie je aktívny'
            raise exceptions.ValidationError(msg)

    def validate_email_verification_status(self, user):
        # pylint: disable=E1101
        email_address = user.emailaddress_set.get(email=user.email)
        if not email_address.verified:
            raise serializers.ValidationError('Email nie je overený.')

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')
        user = self.get_auth_user(email, password)

        if not user:
            msg = 'Nesprávny email alebo heslo.'
            raise exceptions.ValidationError(msg)

        # Did we get back an active user?
        self.validate_auth_user_status(user)

        # If required, is the email verified?
        self.validate_email_verification_status(user)

        attrs['user'] = user
        return attrs


@ts_interface(context='user')
class TokenSerializer(serializers.ModelSerializer):
    """
    Serializer pre Token model.
    """

    class Meta:
        model = TokenModel
        fields = ('key',)


@ts_interface(context='user')
class UserDetailsSerializer(serializers.ModelSerializer):
    """
    Serializer pre User model spolu s Profile modelom
    """
    OTHER_SCHOOL_CODE = 0

    profile = ProfileCreateSerializer(label="")
    new_school_description = serializers.CharField(
        write_only=True, max_length=200, allow_blank=True, required=False)

    def validate_username(self, username):
        username = get_adapter().clean_username(username)
        return username

    class Meta:
        model = get_user_model()
        fields = ('pk', 'email', 'profile', 'new_school_description')
        read_only_fields = ('email',)

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile')

        profile_data['year_of_graduation'] = Grade.objects.get(
            pk=profile_data.get('grade')).get_year_of_graduation_by_date()
        # Profile by mal byť stále vytvorený pomocou post_save User signálu.
        # Pre prípad, že sa tak nestalo, vytvorí sa Profile
        if not instance.profile:
            Profile.objects.create(user=instance, **profile_data)

        # Update Profile
        # Nie všetky polia v modeloch User a Profile sú editovateľné cez API.
        instance.profile.phone = profile_data.get(
            'phone', instance.profile.phone)
        instance.profile.fisrt_name = profile_data.get(
            'first_name', instance.profile.first_name)
        instance.profile.last_name = profile_data.get(
            'last_name', instance.profile.last_name)
        instance.profile.parent_phone = profile_data.get(
            'parent_phone', instance.profile.parent_phone)
        instance.profile.school = profile_data.get(
            'school', instance.profile.school)
        instance.profile.year_of_graduation = profile_data.get(
            'year_of_graduation', instance.profile.year_of_graduation)

        # User sa nikdy neupdatuje preto nie je potrebné volať instance.save()
        instance.profile.save()
        instance.save()
        self.handle_other_school(profile_data.pop(
            'school', None))
        return instance

    def handle_other_school(self, school):
        '''
        Ak je zadana skola "ina skola" tak posle o tom mail.
        '''
        if school is None:
            return
        if school.code == self.OTHER_SCHOOL_CODE:
            email = self.validated_data.get('email', '-')
            first_name = self.validated_data['profile']['first_name']
            last_name = self.validated_data['profile']['last_name']
            school_info = self.validated_data['new_school_description']
            send_mail(
                'Žiadosť o pridanie novej školy',
                render_to_string(
                    'user/emails/new_school_request.txt',
                    {
                        'email': email,
                        'first_name': first_name,
                        'last_name': last_name,
                        'school_info': school_info
                    },
                ),
                EMAIL_NO_REPLY,
                [EMAIL_ALERT]
            )


@ts_interface(context='user')
class RegisterSerializer(UserDetailsSerializer):
    # pylint: disable=arguments-differ,attribute-defined-outside-init
    email = serializers.EmailField(required=True)
    password1 = serializers.CharField(write_only=True)
    password2 = serializers.CharField(write_only=True)
    profile = ProfileCreateSerializer(label="")
    new_school_description = serializers.CharField(write_only=True,
                                                   max_length=200, allow_blank=True)

    class Meta:
        model = get_user_model()
        fields = ('pk', 'email', 'profile', 'password1',
                  'password2', 'new_school_description')
        read_only_fields = ('email',)

    def validate_email(self, email):
        email = get_adapter().clean_email(email)
        if email and EmailAddress.objects.filter(email__iexact=email).exists():
            text = gettext_lazy("Zadaná emailová adresa je už používaná." + 
                "Prosíme skús vyskúsať inú emailovú adresu.")
            raise serializers.ValidationError(text)
        return email

    def validate_password1(self, password):
        return get_adapter().clean_password(password)

    def validate(self, attrs):
        if attrs['password1'] != attrs['password2']:
            raise serializers.ValidationError("Zadané heslá sa nezhodujú.")

        # ak je zadana skola "ina skola", musi byt nejaky description skoly
        if (attrs['profile']['school'].code == self.OTHER_SCHOOL_CODE and
                len(attrs['new_school_description']) == 0):
            raise serializers.ValidationError(
                'Musíš zadať popis tvojej školy.')

        return attrs

    def get_cleaned_data(self):
        return {
            'email': self.validated_data.get('email', ''),
            'password1': self.validated_data.get('password1', '')
        }

    def save(self, request):
        adapter = get_adapter()
        user = adapter.new_user(request)
        self.cleaned_data = self.get_cleaned_data()
        adapter.save_user(request, user, self)
        profile_data = self.validated_data['profile']
        grade = Grade.objects.get(pk=profile_data['grade'])

        Profile.objects.create(user=user,
                               first_name=profile_data['first_name'],
                               last_name=profile_data['last_name'],
                               school=profile_data['school'],
                               year_of_graduation=grade.get_year_of_graduation_by_date(),
                               phone=profile_data['phone'],
                               parent_phone=profile_data['parent_phone']
                               )

        self.handle_other_school(profile_data['school'])
        setup_user_email(request, user, [])

        return user
