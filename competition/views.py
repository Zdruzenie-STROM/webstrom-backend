import json
import os
import zipfile
from io import BytesIO
from operator import itemgetter

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.core.files.move import file_move_safe
from django.http import HttpResponse

from rest_framework import exceptions, status, viewsets, mixins
from rest_framework.decorators import action

from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from webstrom import settings

from base.utils import mime_type

from personal.models import School, Profile
from personal.serializers import SchoolSerializer, ProfileMailSerializer
from competition.models import (Competition, Event, EventRegistration, Grade,
                                LateTag, Problem,
                                Semester, Series, Solution, Vote, UnspecifiedPublication,
                                SemesterPublication, Comment)
from competition import utils
from competition.permissions import CompetitionRestrictedPermission
from competition.serializers import (CompetitionSerializer,
                                     EventRegistrationSerializer,
                                     GradeSerializer,
                                     LateTagSerializer,
                                     ProblemSerializer,
                                     EventSerializer,
                                     SemesterSerializer,
                                     SemesterWithProblemsSerializer,
                                     SeriesWithProblemsSerializer,
                                     SolutionSerializer,
                                     UnspecifiedPublicationSerializer,
                                     SemesterPublicationSerializer,
                                     CommentSerializer)

from competition.permissions import CommentPermission

# pylint: disable=unused-argument


class ModelViewSetWithSerializerContext(viewsets.ModelViewSet):

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context


def generate_result_row(
    semester_registration: EventRegistration,
    semester: Semester = None,
    only_series: Series = None
):
    """
    Vygeneruje riadok výsledku pre používateľa.
    Ak je uvedený only_semester vygenerujú sa výsledky iba sa daný semester
    """
    user_solutions = semester_registration.solution_set
    series_set = semester.series_set.order_by(
        'order') if semester is not None else [only_series]
    solutions = []
    subtotal = []
    for series in series_set:
        series_solutions = []
        solution_points = []
        for problem in series.problems.order_by('order'):
            sol = user_solutions.filter(problem=problem).first()

            solution_points.append(sol.score or 0 if sol is not None else 0)
            series_solutions.append(
                {
                    'points': str(sol.score or '?') if sol is not None else '-',
                    'solution_pk': sol.pk if sol is not None else None,
                    'problem_pk': problem.pk,
                    'votes': 0  # TODO: Implement votes sol.vote
                }
            )
        series_sum_func = getattr(utils, series.sum_method or '',
                                  utils.series_simple_sum)
        solutions.append(series_solutions)
        subtotal.append(
            series_sum_func(solution_points, semester_registration)
        )
    return {
        # Poradie - horná hranica, v prípade deleného miesto(napr. 1.-3.) ide o nižšie miesto(1)
        'rank_start': 0,
        # Poradie - dolná hranica, v prípade deleného miesto(napr. 1.-3.) ide o vyššie miesto(3)
        'rank_end': 0,
        # Indikuje či sa zmenilo poradie od minulej priečky, slúži na delené miesta
        'rank_changed': True,
        # primary key riešiteľovej registrácie do semestra
        'registration': EventRegistrationSerializer(semester_registration).data,
        # Súčty bodov po sériách
        'subtotal': subtotal,
        # Celkový súčet za danú entitu
        'total': sum(subtotal),
        # Zoznam riešení,
        'solutions': solutions
    }


class CompetitionViewSet(viewsets.ReadOnlyModelViewSet):
    """Naše aktivity"""
    queryset = Competition.objects.all()
    serializer_class = CompetitionSerializer
    permission_classes = (CompetitionRestrictedPermission,)


class CommentViewSet(
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet
):
    """Komentáre(otázky) k úlohám"""
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = (CommentPermission, )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context.update({"request": self.request})
        return context

    @action(methods=['post'], detail=True)
    def publish(self, request, pk=None):
        """Publikovanie, teda zverejnenie komentára"""
        comment = self.get_object()
        comment.publish()
        comment.save()

        return Response("Komentár bol publikovaný.", status=status.HTTP_200_OK)

    @action(methods=['post'], detail=True)
    def hide(self, request, pk=None):
        """Skrytie komentára"""
        comment = self.get_object()
        comment.hide()
        comment.save()

        return Response("Komentár bol skrytý.", status=status.HTTP_200_OK)

    @action(methods=['post'], detail=True)
    def edit(self, request, pk=None):
        """Upravenie existujúceho komentára"""
        comment = self.get_object()
        comment.change_text(request.data['text'])
        comment.save()

        return Response("Komentár bol upravený.", status=status.HTTP_200_OK)


class ProblemViewSet(ModelViewSetWithSerializerContext):
    """
    Obsluhuje API endpoint pre Úlohy
    """
    queryset = Problem.objects.all()
    serializer_class = ProblemSerializer
    permission_classes = (CompetitionRestrictedPermission,)

    def perform_create(self, serializer):
        """
        Volá sa pri vytvarani objektu,
        checkuju sa tu permissions, ci user vie vytvorit problem v danej sutazi
        """
        series = serializer.validated_data['series']
        if series.can_user_modify(self.request.user):
            serializer.save()
        else:
            raise exceptions.PermissionDenied(
                'Nedostatočné práva na vytvorenie tohoto objektu')

    @action(methods=['get'], detail=True)
    def comments(self, request, pk=None):
        """Vráti komentáre (otázky) k úlohe"""
        comments_objects = self.get_object().get_comments(request.user)
        comments_serialized = map(
            (lambda obj: CommentSerializer(
                obj, context={'request': request}).data),
            comments_objects)
        return Response(comments_serialized, status=status.HTTP_200_OK)

    @action(methods=['post'], detail=True, url_path=r'add-comment',
            permission_classes=[IsAuthenticated])
    def add_comment(self, request, pk=None):
        """Pridá komentár (otázku) k úlohe"""
        problem = self.get_object()
        problem.add_comment(
            request.data['text'], request.user, problem.can_user_modify(request.user))
        return Response("Komentár bol pridaný", status=status.HTTP_201_CREATED)

    @action(methods=['get'], detail=True, permission_classes=[IsAdminUser])
    def stats(self, request, pk=None):
        """Vráti štatistiky úlohy (histogram, počet riešiteľov...)"""
        return Response(self.get_object().get_stats())

    @action(methods=['post'], detail=True, url_name='upload-solution', url_path='upload-solution')
    def upload_solution(self, request, pk=None):
        """Nahrá užívateľské riešenie k úlohe"""
        problem = self.get_object()

        if not request.user.is_authenticated:
            raise exceptions.PermissionDenied('Je potrebné sa prihlásiť')

        event_registration = EventRegistration.get_registration_by_profile_and_event(
            request.user.profile, problem.series.semester)

        if event_registration is None:
            raise exceptions.MethodNotAllowed(method='upload-solution')

        if 'file' not in request.data:
            raise exceptions.ParseError(detail='Request neobsahoval súbor')

        file = request.data['file']
        if mime_type(file) != 'application/pdf':
            raise exceptions.ParseError(
                detail='Riešenie nie je vo formáte pdf')
        late_tag = problem.series.get_actual_late_flag()
        solution = Solution.objects.create(
            problem=problem,
            semester_registration=event_registration,
            late_tag=late_tag,
            is_online=True
        )
        solution.solution.save(
            solution.get_solution_file_name(), file, save=True)

        return Response(status=status.HTTP_201_CREATED)

    @action(detail=True, url_path='my-solution')
    def my_solution(self, request, pk=None):
        """Vráti riešenie k úlohe pre práve prihláseného užívateľa"""
        problem = self.get_object()
        if not request.user.is_authenticated:
            raise exceptions.PermissionDenied('Je potrebné sa prihlásiť')
        event_registration = EventRegistration.get_registration_by_profile_and_event(
            request.user.profile, problem.series.semester)
        if event_registration is None:
            raise exceptions.MethodNotAllowed(method='my-solution')
        solution = Solution.objects.filter(
            problem=problem, semester_registration=event_registration).first()
        serializer = SolutionSerializer(solution)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(methods=['get'], detail=True, permission_classes=[IsAdminUser],
            url_path='download-solutions')
    def download_solutions(self, request, pk=None):
        """Vráti .zip archív všetkých užívateľských riešení k úlohe"""
        solutions = self.get_object().solution_set.all()
        # Open StringIO to grab in-memory ZIP contents
        stream = BytesIO()
        with zipfile.ZipFile(stream, 'w') as zipf:
            for solution in solutions:
                if solution.is_online and solution.solution.name is not None:
                    prefix = ''
                    if solution.late_tag is not None:
                        prefix = f'{solution.late_tag.slug}/'
                    _, fname = os.path.split(solution.solution.path)
                    zipf.write(solution.solution.path,
                               f'{prefix}{fname}')
        response = HttpResponse(stream.getvalue(),
                                content_type="application/x-zip-compressed")

        response['Content-Disposition'] = (
            'attachment; filename=export.zip'
        )

        return response

    @action(methods=['post'], detail=True, permission_classes=[IsAdminUser],
            url_path='upload-corrected')
    def upload_solutions_with_points(self, request, pk=None):
        """Nahrá .zip archív s opravenými riešeniami (pdf-kami)."""
        if 'file' not in request.data:
            raise exceptions.ParseError(detail='No file attached')
        zfile = request.data['file']
        if not zipfile.is_zipfile(zfile):
            raise exceptions.ParseError(
                detail='Attached file is not a zip file')
        with zipfile.ZipFile(zfile) as zfile:
            if zfile.testzip():
                raise exceptions.ParseError(detail='Zip file is corrupted')
            pdf_files = [name for name in zfile.namelist()
                         if name.endswith('.pdf')]
            errors = []
            for filename in pdf_files:
                try:
                    parts = filename.rstrip('.pdf').split('-')
                    score = int(parts[0])
                    problem_pk = int(parts[-2])
                    registration_pk = int(parts[-1])
                    event_reg = EventRegistration.objects.get(
                        pk=registration_pk)
                    solution = Solution.objects.get(semester_registration=event_reg,
                                                    problem=problem_pk)
                except (IndexError, ValueError, AssertionError):
                    errors.append({
                        'filename': filename,
                        'status': 'Cannot parse file'
                    })
                    continue
                except EventRegistration.DoesNotExist:
                    errors.append({
                        'filename': filename,
                        'status': f'User registration with id {registration_pk} does not exist'
                    })
                    continue
                except Solution.DoesNotExist:
                    errors.append({
                        'filename': filename,
                        'status': f'Solution with registration id {registration_pk}'
                        f'and problem id {problem_pk} does not exist'
                    })
                    continue

                extracted_path = zfile.extract(filename, path='/tmp')
                new_path = os.path.join(
                    settings.MEDIA_ROOT, 'solutions', solution.get_corrected_solution_file_name())
                file_move_safe(extracted_path, new_path, allow_overwrite=True)

                solution.score = score
                solution.corrected_solution = solution.get_corrected_solution_file_name()
                solution.save()
                errors.append({
                    'filename': filename,
                    'status': f'OK - points: {score}'
                })
        return Response(json.dumps(errors))


class SeriesViewSet(ModelViewSetWithSerializerContext):
    """
    Obsluhuje API endpoint pre Úlohy
    """
    queryset = Series.objects.all()
    serializer_class = SeriesWithProblemsSerializer
    permission_classes = (CompetitionRestrictedPermission,)
    http_method_names = ['get', 'head']

    @action(methods=['get'], detail=True)
    def results(self, request, pk=None):
        """Vráti výsledkovku pre sériu"""
        series = self.get_object()
        if series.frozen_results is not None:
            return series.frozen_results
        results = []
        for registration in series.semester.eventregistration_set.all():
            results.append(
                generate_result_row(registration, only_series=series)
            )
        results.sort(key=itemgetter('total'), reverse=True)
        results = utils.rank_results(results)
        return Response(results, status=status.HTTP_200_OK)

    @action(methods=['get'], detail=True)
    def stats(self, request, pk=None):
        """Vráti štatistiky (histogramy, počty riešiteľov) všetkých úloh v sérií"""
        problems = self.get_object().problems
        stats = []
        for problem in problems:
            stats.append(problem.get_stats())
        return Response(stats, status=status.HTTP_200_OK)

    @action(methods=['get'], detail=False, url_path=r'current/(?P<competition_id>\d+)')
    def current(self, request, competition_id=None):
        """Vráti aktuálnu sériu"""
        items = Semester.objects.filter(
            competition=competition_id
        ).current().series_set.filter(complete=False)\
            .order_by('-deadline')\
            .first()
        serializer = SeriesWithProblemsSerializer(items, many=False)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SolutionViewSet(viewsets.ModelViewSet):
    """Užívateľské riešenia"""
    queryset = Solution.objects.all()
    serializer_class = SolutionSerializer

    @action(methods=['post'], detail=True, url_path='add-positive-vote',
            permission_classes=[IsAdminUser])
    def add_positive_vote(self, request, pk=None):
        """Pridá riešeniu kladný hlas"""
        self.get_object().set_vote(Vote.POSITIVE)
        return Response('Pridaný pozitívny hlas.', status=status.HTTP_200_OK)

    @action(methods=['post'], detail=True, url_path='add-negative-vote',
            permission_classes=[IsAdminUser])
    def add_negative_vote(self, request, pk=None):
        """Pridá riešeniu negatívny hlas"""
        self.get_object().set_vote(Vote.NEGATIVE)
        return Response('Pridaný negatívny hlas.', status=status.HTTP_200_OK)

    @action(methods=['post'], detail=True, url_path='remove-vote',
            permission_classes=[IsAdminUser])
    def remove_vote(self, request, pk=None):
        """Odoberie riešeniu hlas"""
        self.get_object().set_vote(Vote.NONE)
        return Response('Hlas Odobraný.', status=status.HTTP_200_OK)

    @action(methods=['get'], detail=True, url_path='download-solution')
    def download_solution(self, request, pk=None):
        """Stiahne riešenie"""
        solution = self.get_object()
        response = HttpResponse(
            solution.solution, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{solution.solution}"'
        return response

    @action(methods=['get'], detail=True, url_path='download-corrected')
    def download_corrected(self, request, pk=None):
        """Stiahne opravenú verziu riešenia"""
        solution = self.get_object()
        response = HttpResponse(
            solution.solution, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{solution.corrected_solution}"'
        return response


class SemesterListViewSet(viewsets.ReadOnlyModelViewSet):
    """Zoznam semestrov (iba základné informácie)"""
    queryset = Semester.objects.all()
    serializer_class = SemesterSerializer
    permission_classes = (CompetitionRestrictedPermission,)
    http_method_names = ['get', 'post', 'head']
    filterset_fields = ['competition']


class SemesterViewSet(ModelViewSetWithSerializerContext):
    """Semestre - aj so sériami a problémami"""
    queryset = Semester.objects.all()
    serializer_class = SemesterWithProblemsSerializer
    permission_classes = (CompetitionRestrictedPermission,)
    filterset_fields = ['competition']
    http_method_names = ['get', 'post', 'head']

    def perform_create(self, serializer):
        """
        Vola sa pri vytvarani objektu,
        checkuju sa tu permissions, ci user vie vytvorit semester v danej sutazi
        """
        competition = serializer.validated_data['competition']
        if competition.can_user_modify(self.request.user):
            serializer.save()
        else:
            raise exceptions.PermissionDenied(
                'Nedostatočné práva na vytvorenie tohoto objektu')

    @staticmethod
    def semester_results(semester):
        """Vyrobí výsledky semestra"""
        if semester.frozen_results is not None:
            return semester.frozen_results
        results = []
        for registration in semester.eventregistration_set.all():
            results.append(generate_result_row(registration, semester))

        results.sort(key=itemgetter('total'), reverse=True)
        results = utils.rank_results(results)
        return results

    @action(methods=['get'], detail=True)
    def results(self, request, pk=None):
        """Vráti výsledkovku semestra"""
        semester = self.get_object()
        current_results = SemesterViewSet.semester_results(semester)
        return Response(current_results, status=status.HTTP_200_OK)

    @action(methods=['get'], detail=True, permission_classes=[IsAdminUser])
    def schools(self, request, pk=None):
        """Vráti školy, ktorých žiaci boli zapojený do semestra"""
        schools = School.objects.filter(eventregistration__event=pk)\
            .distinct()\
            .order_by('city', 'street')
        serializer = SchoolSerializer(schools, many=True)
        return Response(serializer.data)

    @action(methods=['get'], detail=True,
            url_path='offline-schools', permission_classes=[IsAdminUser])
    def offline_schools(self, request, pk=None):
        """Vráti školy, ktorých aspoň nejaký žiaci odovzdali papierové riešenia"""
        schools = School.objects.filter(eventregistration__event=pk)\
            .filter(eventregistration__solution__is_online=False)\
            .distinct()\
            .order_by('city', 'street')
        serializer = SchoolSerializer(schools, many=True)
        return Response(serializer.data)

    @action(methods=['get'], detail=True,
            url_path=r'invitations/(?P<num_participants>\d+)/(?P<num_substitutes>\d+)',
            permission_classes=[IsAdminUser])
    def invitations(self, request, pk=None, num_participants=32, num_substitutes=20):
        """Vráti TeXovský kus zdrojáku pre výrobu pozvánky na sústredenie pre účastníka"""
        semester = self.get_object()
        num_participants = int(num_participants)
        num_substitutes = int(num_substitutes)
        participants = utils.generate_praticipant_invitations(
            SemesterViewSet.semester_results(semester),
            num_participants,
            num_substitutes
        )
        participants.sort(key=itemgetter('first_name'))
        participants.sort(key=itemgetter('last_name'))

        return Response(participants, status=status.HTTP_200_OK)

    @action(methods=['get'], detail=True,
            url_path=r'school-invitations/(?P<num_participants>\d+)/(?P<num_substitutes>\d+)',
            permission_classes=[IsAdminUser])
    def school_invitations(self, request, pk=None, num_participants=32, num_substitutes=20):
        """Vráti TeXovský kus zdrojáku pre výrobu pozvánky na sústredenie pre školu"""
        num_participants = int(num_participants)
        num_substitutes = int(num_substitutes)
        semester = self.get_object()
        participants = utils.generate_praticipant_invitations(
            SemesterViewSet.semester_results(semester),
            num_participants,
            num_substitutes
        )
        participants.sort(key=itemgetter('first_name'))
        participants.sort(key=itemgetter('last_name'))
        participants.sort(key=lambda p: p['school']['code'])
        last_school = None
        schools = []
        for participant in participants:
            if last_school != participant['school']:
                last_school = participant['school']
                schools.append(
                    {'school_name': last_school, 'participants': []})
            schools[-1]['participants'].append(participant)

        return Response(schools, status=status.HTTP_200_OK)

    @action(methods=['get'], detail=False, url_path=r'current/(?P<competition_id>\d+)')
    def current(self, request, competition_id=None):
        """Vráti aktuálny semester"""
        current_semester = self.get_queryset().filter(
            competition=competition_id).current()
        serializer = SemesterWithProblemsSerializer(
            current_semester, many=False)
        return Response(serializer.data)

    @action(methods=['get'], detail=False, url_path=r'current-results/(?P<competition_id>\d+)')
    def current_results(self, request, competition_id=None):
        """Vráti výsledky pre aktuálny semester"""
        current_semester = self.get_queryset().filter(
            competition=competition_id).current()
        current_results = SemesterViewSet.semester_results(current_semester)
        return Response(current_results, status=status.HTTP_201_CREATED)

    @action(methods=['get'], detail=True)
    def participants(self, request, pk=None):
        """Vráti všetkých užívateľov zapojených do semestra"""
        semester = self.get_object()
        participants_id = []

        for series in semester.series_set.all():
            solutions = Solution.objects.only('semester_registration')\
                .filter(problem__series=series)\
                .order_by('semester_registration')

            for solution in solutions:
                participants_id.append(
                    solution.semester_registration.profile.pk)

        profiles = Profile.objects.only("user").filter(pk__in=participants_id)
        serializer = ProfileMailSerializer(profiles, many=True)
        return Response(serializer.data)

    def post(self, request, format_post):
        """Založí nový semester"""
        serializer = SemesterSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class EventViewSet(ModelViewSetWithSerializerContext):
    """Ročníky akcií (napríklad Matboj 2021)"""
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    filterset_fields = ['school_year', 'competition', ]
    permission_classes = (CompetitionRestrictedPermission,)

    def perform_create(self, serializer):
        """
        Vola sa pri vytvarani objektu,
        checkuju sa tu permissions, ci user vie vytvorit event v danej sutazi
        """
        competition = serializer.validated_data['competition']
        if competition.can_user_modify(self.request.user):
            serializer.save()
        else:
            raise exceptions.PermissionDenied(
                'Nedostatočné práva na vytvorenie tohoto objektu')

    @action(methods=['post'], detail=True, permission_classes=[IsAuthenticated])
    def register(self, request, pk=None):
        """Registruje prihláseného užívateľa na akciu"""
        event = self.get_object()
        profile = request.user.profile
        if not event.can_user_participate(request.user):
            return Response('Používateľa nie je možné registrovať - Zlá veková kategória',
                            status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        if EventRegistration.get_registration_by_profile_and_event(
                profile, event):
            return Response('Používateľ je už zaregistrovaný', status=status.HTTP_409_CONFLICT)
        EventRegistration.objects.create(
            event=event,
            school=profile.school,
            profile=profile,
            grade=Grade.get_grade_by_year_of_graduation(
                profile.year_of_graduation),
        )

        return Response(status=status.HTTP_201_CREATED)

    @action(methods=['get'], detail=True, permission_classes=[IsAuthenticated])
    def can_participate(self, request, pk=None):
        event = self.get_object()
        return Response(
            {'can-participate': event.can_user_participate(request.user)},
            status=status.HTTP_200_OK
        )

    @action(methods=['get'], detail=True, permission_classes=[IsAuthenticated])
    def participants(self, request, pk=None):
        event = self.get_object()
        # Profile serializer
        return event.registered_profiles()

    @action(methods=['post'], detail=False, permission_classes=[IsAuthenticated])
    def active(self):
        """Get all active events"""
        active_events = self.get_queryset().active()
        serializer = self.serializer_class(active_events, many=True)
        return Response(serializer.data)


class EventRegistrationViewSet(viewsets.ModelViewSet):
    """Registrácie na akcie"""
    queryset = EventRegistration.objects.all()
    serializer_class = EventRegistrationSerializer
    filterset_fields = ['event', 'profile', ]
    permission_classes = (CompetitionRestrictedPermission,)


class UnspecifiedPublicationViewSet(viewsets.ModelViewSet):
    """Publikácie(výsledky, brožúrky ... nie časopis)"""
    queryset = UnspecifiedPublication.objects.all()
    serializer_class = UnspecifiedPublicationSerializer
    permission_classes = (CompetitionRestrictedPermission,)

    def perform_create(self, serializer):
        '''
        Vola sa pri vytvarani objektu,
        checkuju sa tu permissions, ci user vie vytvorit publication v danom evente
        '''
        event = serializer.validated_data['event']
        if event.can_user_modify(self.request.user):
            serializer.save()
        else:
            raise exceptions.PermissionDenied(
                'Nedostatočné práva na vytvorenie tohoto objektu')

    @action(methods=['get'], detail=True, url_path='download')
    def download_publication(self, request, pk=None):
        """Stiahne súbor publikácie"""
        publication = self.get_object()
        response = HttpResponse(
            publication.file, content_type=mime_type(publication.file))
        response['Content-Disposition'] = f'attachment; filename="{publication.name}"'
        return response

    @action(methods=['post'], detail=False, url_path='upload', permission_classes=[IsAdminUser])
    def upload_publication(self, request):
        """Nahrá súbor publikácie"""
        if 'file' not in request.data:
            raise exceptions.ParseError(detail='Request neobsahoval súbor')

        file = request.data['file']
        if mime_type(file) not in ['application/pdf', 'application/zip']:
            raise exceptions.ParseError(detail='Nesprávny formát')

        event = Event.objects.filter(pk=request.data['event']).first()
        publication = UnspecifiedPublication.objects.create(
            file=file,
            event=event
        )
        publication.generate_name()
        publication.file.save(publication.name, file)
        return Response(status=status.HTTP_201_CREATED)


class SemesterPublicationViewSet(viewsets.ModelViewSet):
    """Časáky"""
    queryset = SemesterPublication.objects.all()
    serializer_class = SemesterPublicationSerializer
    permission_classes = (CompetitionRestrictedPermission,)

    @action(methods=['get'], detail=True, url_path='download')
    def download_publication(self, request, pk=None):
        """Stiahne časopis"""
        publication = self.get_object()
        response = HttpResponse(
            publication.file, content_type=mime_type(publication.file))
        response['Content-Disposition'] = f'attachment; filename="{publication.name}"'
        return response

    @action(methods=['post'], detail=False, url_path='upload', permission_classes=[IsAdminUser])
    def upload_publication(self, request):
        """Uploadne časopis"""
        if 'file' not in request.data:
            raise exceptions.ParseError(detail='Request neobsahoval súbor')

        file = request.data['file']
        if mime_type(file) != 'application/pdf':
            raise exceptions.ParseError(detail='Nesprávny formát')

        semester = Semester.objects.filter(pk=request.data['semester']).first()
        primary_key = request.data['semester']
        if SemesterPublication.objects.filter(semester=semester) \
            .filter(~Q(pk=primary_key), order=request.data['order']) \
                .exists():
            raise ValidationError({
                'order': 'Časopis s týmto číslom už v danom semestri existuje',
            })

        publication = SemesterPublication.objects.create(
            file=file,
            semester=semester,
            order=request.data['order'],
        )
        publication.generate_name()
        publication.file.save(
            publication.name, file)
        return Response(status=status.HTTP_201_CREATED)


class GradeViewSet(viewsets.ReadOnlyModelViewSet):
    """Ročníky riešiteľov (Z9,S1 ...)"""
    queryset = Grade.objects.filter(is_active=True).all()
    serializer_class = GradeSerializer


class LateTagViewSet(viewsets.ReadOnlyModelViewSet):
    """Omeškania"""
    queryset = LateTag.objects.all()
    serializer_class = LateTagSerializer
