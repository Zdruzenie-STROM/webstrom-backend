import datetime
from typing import Optional

from django.conf import settings
from django.contrib.sites.models import Site
from django.core.files.storage import FileSystemStorage
from django.core.validators import validate_slug
from django.db import models
from django.db.models.constraints import UniqueConstraint
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.shortcuts import get_object_or_404
from django.utils.functional import cached_property
from django.utils.timezone import now
from unidecode import unidecode

from base.managers import UnspecifiedValueManager
from base.models import RestrictedFileField
from base.validators import school_year_validator
from competition.exceptions import FreezingNotClosedResults
from competition.querysets import ActiveQuerySet
from competition.utils.school_year_manipulation import (
    get_school_year_end_by_date)
from personal.models import Profile, School
from user.models import User

private_storage = FileSystemStorage(location=settings.PRIVATE_STORAGE_ROOT)


class CompetitionType(models.Model):
    "Druh súťaže"
    class Meta:
        verbose_name = 'Typ súťaže'
        verbose_name_plural = 'Typy súťaží'

    name = models.CharField('typ súťaže', max_length=200)

    def __str__(self):
        return self.name


class Competition(models.Model):
    """
    Model súťaže, ktorý pokrýva súťaž ako koncept. Napríklad Matboj, Seminár STROM, Kôš
    """
    class Meta:
        verbose_name = 'súťaž'
        verbose_name_plural = 'súťaže'

    name = models.CharField(verbose_name='názov', max_length=50)
    slug = models.SlugField()
    start_year = models.PositiveSmallIntegerField(
        verbose_name='rok prvého ročníka súťaže', blank=True)
    description = models.TextField(verbose_name='Popis súťaže', blank=True)
    rules = models.TextField(
        verbose_name='Pravidlá súťaže', blank=True, null=True)
    who_can_participate = models.CharField(
        verbose_name='Pre koho je súťaž určená', blank=True,
        max_length=50)

    sites = models.ManyToManyField(Site)

    competition_type = models.ForeignKey(
        CompetitionType,
        null=True,
        on_delete=models.SET_NULL,
        verbose_name='typ súťaže')

    min_years_until_graduation = models.PositiveSmallIntegerField(
        verbose_name='Minimálny počet rokov do maturity', null=True,
        help_text='Horná hranica na účasť v súťaži. '
        'Zadáva sa v počte rokov do maturity. '
        'Ak najstraší, kto môže riešiť súťaž je deviatak, zadá sa 4.')

    permission_group = models.ManyToManyField('auth.Group',
                                              blank=True,
                                              verbose_name='Skupiny práv',
                                              related_name='competition_permissions')

    def can_user_participate(self, user):
        if self.min_years_until_graduation is not None:
            return user.profile.year_of_graduation-get_school_year_end_by_date() \
                >= self.min_years_until_graduation
        return True

    @classmethod
    def can_user_create(cls, user: User, data):  # pylint:disable=unused-argument
        return user.is_authenticated and user.is_superuser

    def __str__(self):
        return self.name

    @cached_property
    def semester_set(self):
        return Semester.objects.filter(competition=self.pk)

    @classmethod
    def get_seminar_by_site(cls, site):
        return get_object_or_404(cls, sites=site, competition_type=0)

    @classmethod
    def get_seminar_by_current_site(cls):
        return cls.get_seminar_by_site(Site.objects.get_current())

    def can_user_modify(self, user: User):
        return len(set(self.permission_group.all()).intersection(set(user.groups.all()))) > 0


class LateTag(models.Model):
    """
    Slúži na označenie riešenia po termíne.
    Každý LateTag vyjadruje druh omeškania (napríklad do 24 hodín)
    """
    class Meta:
        verbose_name = 'omeškanie'
        verbose_name_plural = 'omeškanie'

    name = models.CharField(
        verbose_name='označenie štítku pre riešiteľa', max_length=50)
    slug = models.CharField(
        verbose_name='označenie priečinku pri stiahnutí', max_length=50, validators=[validate_slug])
    upper_bound = models.DurationField(
        verbose_name='maximálna dĺžka omeškania')
    comment = models.TextField(verbose_name='komentár pre opravovateľa')
    can_resubmit = models.BooleanField(
        verbose_name='Možnosť prepísať odovzdané riešenie')

    def __str__(self):
        return self.name


class Event(models.Model):
    """
    Slúži na označenie instancie súťaže (Napríklad: Matboj 2020,
    Letný semester 40. ročníka STROMu, Jarný výlet 2021)
    """
    # pylint: disable=no-member
    class Meta:
        verbose_name = 'ročník súťaže'
        verbose_name_plural = 'ročníky súťaží'
        ordering = ['-school_year', ]

    SEASON_CHOICES = [
        (0, 'Zimný'),
        (1, 'Letný'),
        (2, '')
    ]

    competition = models.ForeignKey(
        Competition, on_delete=models.CASCADE)

    year = models.PositiveSmallIntegerField(verbose_name='ročník', blank=True)
    school_year = models.CharField(
        verbose_name='školský rok', max_length=10, blank=True,
        validators=[school_year_validator])

    season_code = models.PositiveSmallIntegerField(
        choices=SEASON_CHOICES, default=2)

    start = models.DateTimeField(verbose_name='dátum začiatku súťaže')
    end = models.DateTimeField(verbose_name='dátum konca súťaže')
    additional_name = models.CharField(
        max_length=50, verbose_name='Prívlastok súťaže', null=True, blank=True)

    registration_link = models.OneToOneField(
        "competition.RegistrationLink",
        on_delete=models.SET_NULL,
        null=True,
    )

    objects = ActiveQuerySet.as_manager()

    def is_user_registered(self, user):
        return EventRegistration.objects.filter(event=self.pk, user=user).exists()

    @property
    def registered_profiles(self):
        return Profile.objects.filter(eventregistration_set__event=self.pk)

    def __str__(self):
        try:
            return str(self.semester)
        except Event.semester.RelatedObjectDoesNotExist:
            name_components = [f'{self.competition.name}, {self.year}. ročník']
            if self.season_code != 2:
                name_components.append(self.season)
            if self.additional_name:
                name_components.append(self.additional_name)
            return ' - '.join(name_components)

    @property
    def is_active(self):
        return now() <= self.end

    def can_user_modify(self, user):
        return self.competition.can_user_modify(user)

    @classmethod
    def can_user_create(cls, user: User, data: dict) -> bool:
        competition = Competition.objects.get(pk=data['competition'])
        return competition.can_user_modify(user)

    def can_user_participate(self, user):
        return self.competition.can_user_participate(user)

    @property
    def season(self):
        return self.get_season_code_display()

    @property
    def season_short(self):
        return self.get_season_code_display()[:3].lower()


class Semester(Event):
    """
    Špeciálny prípad eventu pridávajúci niekoľko ďalších polí
    pre funkcionalitu semestrov korešpondenčných seminárov.
    S dodatočnými informáciami ako season(letný, zimný) a povolené kategórie omeškaní riešení
    """
    class Meta:
        verbose_name = 'semester'
        verbose_name_plural = 'semestre'
        ordering = ['-year', '-season_code', ]

    late_tags = models.ManyToManyField(
        LateTag, verbose_name='Stavy omeškania', blank=True)
    frozen_results = models.TextField(
        null=True,
        blank=True,
        default=None)

    def save(self, *args, **kwargs) -> None:
        if not self.frozen_results:
            self.frozen_results = None
        return super().save(*args, **kwargs)

    def get_first_series(self) -> 'Series':
        return self.series_set.get(order=1)

    def get_second_series(self) -> 'Series':
        return self.series_set.get(order=2)

    def freeze_results(self, results):
        if any(not series.complete for series in self.series_set.all()):
            raise FreezingNotClosedResults()
        self.frozen_results = results

    @property
    def complete(self) -> bool:
        return self.frozen_results is not None

    @property
    def is_active(self) -> bool:
        return self.series_set.filter(complete=False).exists()

    @property
    def is_at_least_one_series_open(self) -> bool:
        return self.series_set.filter(can_submit=True).exists()

    def __str__(self):
        return f'{self.competition.name}, {self.year}. ročník - {self.season} semester'


SERIES_SUM_METHODS = [
    ('series_simple_sum', 'Jednoduchý súčet bodov'),
    ('series_Malynar_sum', 'Bonifikácia Malynár'),
    ('series_Matik_sum', 'Bonifikácia Matik'),
    ('series_STROM_sum', 'Bonifikácia STROM'),
    ('series_Malynar_sum_until_2021', 'Bonifikácia Malynár (Do 2020/2021)'),
    ('series_Matik_sum_until_2021', 'Bonifikácia Matik (Do 2020/2021)'),
    ('series_STROM_sum_until_2021', 'Bonifikácia STROM (Do 2020/2021)'),
    ('series_STROM_4problems_sum', 'Bonifikácia STROM (4. úlohy)')
]


class Series(models.Model):
    """
    Popisuje jednu sériu semestra
    """
    class Meta:
        verbose_name = 'séria'
        verbose_name_plural = 'série'
        ordering = ['semester', '-order', ]

    semester = models.ForeignKey(
        Semester, verbose_name='semester', on_delete=models.CASCADE)
    order = models.PositiveSmallIntegerField(verbose_name='poradie série')

    deadline = models.DateTimeField(verbose_name='termín série')

    # Implementuje bonfikáciu
    sum_method = models.CharField(
        verbose_name='Súčtová metóda', max_length=50, blank=True,
        choices=SERIES_SUM_METHODS)
    frozen_results = models.TextField(
        null=True,
        blank=True,
        default=None)

    def save(self, *args, **kwargs) -> None:
        if not self.frozen_results:
            self.frozen_results = None
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.semester} - {self.order}. séria'

    @property
    def is_past_deadline(self) -> bool:
        return now() > self.deadline

    @property
    def time_to_deadline(self) -> datetime.timedelta:
        remaining_time = self.deadline - now()

        if remaining_time.total_seconds() < 0:
            return datetime.timedelta(0)

        return remaining_time

    @property
    def can_submit(self) -> bool:
        """
        Vráti True, ak užívateľ ešte môže odovzdať úlohu.
        Pozerá sa na maximálne možné omeškanie v LateFlagoch.
        """
        max_late_tag_value = self.semester.late_tags.aggregate(
            models.Max('upper_bound'))['upper_bound__max']
        if max_late_tag_value is None:
            max_late_tag_value = datetime.timedelta(0)
        return now() < self.deadline + max_late_tag_value

    @property
    def can_resubmit(self) -> bool:
        late_flag = self.get_actual_late_flag()
        if late_flag:
            return late_flag.can_resubmit
        return self.can_submit

    @property
    def complete(self) -> bool:
        return self.frozen_results is not None

    def get_actual_late_flag(self) -> Optional[LateTag]:
        """
        Vráti late flag, ktorý má byť v tomto okamihu priradený riešeniu,
        teda jeho aktuálne omeškanie
        """
        if not self.is_past_deadline:
            return None
        if not self.can_submit:
            return None
        return self.semester.late_tags.filter(upper_bound__gte=now()-self.deadline)\
            .order_by('upper_bound')\
            .first()

    def freeze_results(self, results):
        if any(
            problem.num_solutions != problem.num_corrected_solutions
            for problem in self.problems.all()
        ):
            raise FreezingNotClosedResults()
        self.frozen_results = results

    @property
    def num_problems(self) -> int:
        return self.problems.count()

    def can_user_modify(self, user: User) -> bool:
        return self.semester.can_user_modify(user)

    @classmethod
    def can_user_create(cls, user: User, data: dict) -> bool:
        semester = Semester.objects.get(pk=data['semester'])
        return semester.can_user_modify(user)

    def can_user_participate(self, user: User) -> bool:
        return self.semester.can_user_participate(user)


class Problem(models.Model):
    """
    Popisuje jednu úlohu v sérií
    """
    class Meta:
        verbose_name = 'úloha'
        verbose_name_plural = 'úlohy'

        ordering = ['series', 'order', ]

    text = models.TextField(verbose_name='znenie úlohy')
    order = models.PositiveSmallIntegerField(verbose_name='poradie v sérii')
    series = models.ForeignKey(
        Series, verbose_name='úloha zaradená do série',
        related_name='problems',
        on_delete=models.CASCADE,)

    image = models.ImageField(
        upload_to='problem_images/',
        verbose_name='Obrázok k úlohe',
        null=True,
        blank=True,
    )

    solution_pdf = RestrictedFileField(
        content_types=['application/pdf'],
        verbose_name='Vzorové riešenie', null=True, blank=True,
        upload_to='model_solutions/')

    def __str__(self):
        return f'{self.series.semester.competition.name}-{self.series.semester.year}' \
            f'-{self.series.semester.season[0]}S-S{self.series.order} - {self.order}. úloha'

    def get_stats(self):
        stats = {}
        stats['histogram'] = []
        total_solutions = 0
        total_points = 0
        for score in range(10):
            count = self.solution_set.filter(score=score).count()
            total_solutions += count
            total_points += count*score
            stats['histogram'].append({'score': score, 'count': count})
        stats['num_solutions'] = total_solutions

        stats['mean'] = total_points / \
            total_solutions if total_solutions else '?'
        return stats

    @property
    def num_solutions(self):
        return self.solution_set.count()

    @property
    def num_corrected_solutions(self):
        return self.solution_set.filter(score__isnull=False).count()

    def can_user_modify(self, user):
        return self.series.can_user_modify(user)

    @classmethod
    def can_user_create(cls, user: User, data: dict) -> bool:
        series = Series.objects.get(pk=data['series'])
        return series.can_user_modify(user)

    def get_comments(self, user: User):
        def filter_by_permissions(obj: 'Comment'):
            if not user.is_anonymous and obj.can_user_modify(user):
                return True
            if obj.state == CommentPublishState.PUBLISHED:
                return True
            if obj.posted_by == user:
                return True
            return False

        return filter(filter_by_permissions, Comment.objects.filter(problem=self))

    def add_comment(self, text, user, also_publish):
        Comment.objects.create(
            problem=Problem.objects.get(pk=self.pk),
            text=text,
            posted_by=user,
            state=CommentPublishState.PUBLISHED if also_publish
            else CommentPublishState.WAITING_FOR_REVIEW,
        )


class CommentPublishState(models.IntegerChoices):
    '''
    Enum stavov komentárov
    '''
    WAITING_FOR_REVIEW = 1, 'čaká'
    PUBLISHED = 2, 'zverejnený'
    HIDDEN = 3, 'skrytý'


class Comment(models.Model):
    class Meta:
        verbose_name = 'komentár'
        verbose_name_plural = 'komentáre'
        ordering = ['posted_at']

    problem = models.ForeignKey(
        Problem, verbose_name='komentár k úlohe',
        on_delete=models.CASCADE,)
    text = models.TextField()
    posted_at = models.DateTimeField(
        verbose_name='dátum pridania', auto_now_add=True)
    posted_by = models.ForeignKey(
        User, verbose_name='autor komentára',
        on_delete=models.CASCADE)
    state = models.IntegerField(
        choices=CommentPublishState.choices,
        verbose_name='komentár publikovaný',
        default=CommentPublishState.WAITING_FOR_REVIEW
    )
    hidden_response = models.TextField(
        null=True, blank=True, verbose_name='Skrytá odpoveď na komentár')

    def save(self, *args, **kwargs) -> None:
        if not self.hidden_response:
            self.hidden_response = None
        return super().save(*args, **kwargs)

    def publish(self):
        self.state = CommentPublishState.PUBLISHED
        self.hidden_response = None

    def hide(self, message: str):
        self.state = CommentPublishState.HIDDEN
        self.hidden_response = message

    def change_text(self, new_text):
        if self.state != CommentPublishState.PUBLISHED:
            self.text = new_text
        else:
            raise ValueError('Publikovaný komentár nemôže byť zmenený')

    def can_user_modify(self, user):
        return self.problem.can_user_modify(user)

    @classmethod
    def can_user_create(cls, user: User, data: dict) -> bool:
        problem = Problem.objects.get(pk=data['problem'])
        return problem.can_user_modify(user)


class Grade(models.Model):
    """
    Popisuje ročník súťažiaceho. Napríklad Z9, S1 ...
    """
    class Meta:
        verbose_name = 'ročník účastníka'
        verbose_name_plural = 'ročníky účastníka'
        ordering = ['years_until_graduation', ]

    name = models.CharField(verbose_name='názov ročníku', max_length=32)
    tag = models.CharField(verbose_name='skratka', max_length=2, unique=True)
    years_until_graduation = models.SmallIntegerField(
        verbose_name='počet rokov do maturity')
    is_active = models.BooleanField(
        verbose_name='aktuálne používaný ročník')

    objects = UnspecifiedValueManager(unspecified_value_pk=13)

    def get_year_of_graduation_by_date(self, date=None):
        return get_school_year_end_by_date(date) + self.years_until_graduation

    @staticmethod
    def get_grade_by_year_of_graduation(year_of_graduation, date=None):
        years_until_graduation = year_of_graduation - \
            get_school_year_end_by_date(date)

        try:
            grade = Grade.objects.get(
                years_until_graduation=years_until_graduation)
        except Grade.DoesNotExist:
            grade = Grade.objects.get_unspecified_value()

        return grade

    def __str__(self):
        return self.name


class EventRegistration(models.Model):
    """
    Registruje účastníka na instanciu súťaže(napríklad Matboj 2020,
    letný semester 40. ročník STROMu).
    V registrácií sú uložené údaje účastníka aktuálne v čase konania súťaže.
    """
    class Meta:
        verbose_name = 'registrácia užívateľa na akciu'
        verbose_name_plural = 'registrácie užívateľov na akcie'
        constraints = [
            UniqueConstraint(fields=['profile', 'event'],
                             name='single_registration_in_event'),
        ]

    profile = models.ForeignKey(
        Profile, verbose_name='profil', on_delete=models.CASCADE)
    school = models.ForeignKey(
        School, verbose_name='škola', on_delete=models.SET_NULL, null=True)
    grade = models.ForeignKey(
        Grade, verbose_name='ročník', on_delete=models.CASCADE)
    event = models.ForeignKey(
        Event, verbose_name='semester', on_delete=models.CASCADE)

    @staticmethod
    def get_registration_by_profile_and_event(profile, event):
        try:
            registration = EventRegistration.objects.get(
                profile=profile, event=event)

        except EventRegistration.DoesNotExist:
            registration = None

        return registration

    def __str__(self):
        return f'{ self.profile.user.get_full_name() } @ { self.event }'

    def can_user_modify(self, user):
        return self.event.can_user_modify(user)

    @classmethod
    def can_user_create(cls, user: User, data: dict) -> bool:
        event = Event.objects.get(pk=data['event'])
        return event.can_user_modify(user)


class Vote(models.IntegerChoices):
    '''
    Enum hlasov
    '''
    NEGATIVE = -1, 'negatívny'
    NONE = 0, 'žiaden'
    POSITIVE = 1, 'pozitívny'


class Solution(models.Model):
    """
    Popisuje riešenie úlohy od užívateľa. Obsahuje nahraté aj opravné riešenie, body
    """
    class Meta:
        verbose_name = 'riešenie'
        verbose_name_plural = 'riešenia'

    problem = models.ForeignKey(Problem, on_delete=models.CASCADE)
    semester_registration = models.ForeignKey(
        EventRegistration, on_delete=models.CASCADE)

    solution = RestrictedFileField(
        content_types=['application/pdf'],
        storage=private_storage,
        verbose_name='účastnícke riešenie', blank=True, upload_to='solutions/user_solutions')
    corrected_solution = RestrictedFileField(
        content_types=['application/pdf'],
        storage=private_storage,
        verbose_name='opravené riešenie', blank=True, upload_to='solutions/corrected/')

    score = models.PositiveSmallIntegerField(
        verbose_name='body', null=True, blank=True)

    vote = models.IntegerField(choices=Vote.choices,
                               default=Vote.NONE)

    uploaded_at = models.DateTimeField(
        verbose_name='dátum pridania', auto_now_add=True)

    # V prípade, že riešenie prišlo po termíne nastaví sa na príslušný tag
    late_tag = models.ForeignKey(
        LateTag, verbose_name='Stavy omeškania',
        on_delete=models.SET_NULL, null=True, blank=True)

    is_online = models.BooleanField(
        verbose_name='internetové riešenie', default=False)

    def __str__(self):
        return f'Riešiteľ: { self.semester_registration } - úloha { self.problem }'

    def get_solution_file_name(self):
        return f'{self.semester_registration.profile.user.get_full_name_camel_case()}'\
               f'-{self.problem.id}-{self.semester_registration.id}.pdf'

    def get_corrected_solution_file_name(self):
        return f'corrected/{self.semester_registration.profile.user.get_full_name_camel_case()}'\
               f'-{self.problem.id}-{self.semester_registration.id}_corrected.pdf'

    def can_user_modify(self, user):
        return self.problem.can_user_modify(user)

    @classmethod
    def can_user_create(cls, user: User, data: dict) -> bool:
        problem = Problem.objects.get(pk=data['problem'])
        return problem.can_user_modify(user)

    def set_vote(self, vote):
        self.vote = vote
        self.save()


class PublicationType(models.Model):
    class Meta:
        verbose_name = 'Typ publikácie'
        verbose_name_plural = 'Typy publikácií'

    name = models.CharField(max_length=100, verbose_name='názov typu')

    @property
    def code(self):
        return unidecode(self.name).lower()

    def __str__(self):
        return self.name


class Publication(models.Model):
    """
    Reprezentuje výsledky, brožúrku, časopis alebo akýkoľvek materiál
    zverejnený k nejakému Eventu, respektíve semestru.
    """
    class Meta:
        verbose_name = 'Publikácia'
        verbose_name_plural = 'Publikácie'
        ordering = ['order', ]

    publication_type = models.ForeignKey(
        PublicationType, on_delete=models.SET_NULL, null=True)
    name = models.CharField(max_length=30, blank=True)
    event = models.ForeignKey(Event, null=True, on_delete=models.SET_NULL)

    file = RestrictedFileField(
        upload_to='publications/%Y',
        content_types=['application/pdf', 'application/zip'],
        verbose_name='súbor')

    order = models.PositiveSmallIntegerField(
        verbose_name='poradie', null=True, blank=True)

    def generate_name(self, forced=False):
        if self.name and not forced:
            return

        if self.order:
            self.name = f'{self.publication_type.code}_{self.order}.pdf'
        else:
            self.name = self.publication_type.name
        self.save()

    def __str__(self):
        return f'{self.event} - {self.name}'

    def can_user_modify(self, user):
        return self.event.can_user_modify(user)

    @classmethod
    def can_user_create(cls, user: User, data: dict) -> bool:
        event = Event.objects.get(pk=data['event'])
        return event.can_user_modify(user)


@receiver(post_save, sender=Publication)
def make_name_on_creation(sender, instance, created, **kwargs):
    # pylint: disable=unused-argument
    if created:
        instance.generate_name()


class RegistrationLink(models.Model):
    class Meta:
        verbose_name = 'link na registráciu'
        verbose_name_plural = 'linky na registráciu'

    url = models.URLField(verbose_name='url registrácie')
    start = models.DateTimeField(verbose_name='Začiatok registrácie')
    end = models.DateTimeField(verbose_name='Koniec registrácie')
    additional_info = models.TextField(
        verbose_name='Doplňujúce informácie', null=True, blank=True)

    def save(self, *args, **kwargs) -> None:
        if not self.additional_info:
            self.additional_info = None
        return super().save(*args, **kwargs)

    def can_user_modify(self, user):
        # pylint: disable=no-member
        return self.event.can_user_modify(user)


class ProblemCorrection(models.Model):
    # TODO: Add images
    class Meta:
        verbose_name = 'opravenie úlohy'
        verbose_name_plural = 'opravene ulohy'

    problem = models.OneToOneField(
        Problem,
        on_delete=models.CASCADE,
        related_name='correction',
        primary_key=False
    )

    correct_solution_text = models.TextField(verbose_name='vzorák')
    best_solution = models.ManyToManyField(
        Solution, verbose_name='najkrajšie riešenia')
    corrected_by = models.ManyToManyField(User, verbose_name='opravovatelia')
