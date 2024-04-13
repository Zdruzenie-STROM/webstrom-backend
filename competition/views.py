import csv
import os
import zipfile
from io import BytesIO
from operator import itemgetter
from typing import Optional

from django.core.files import File
from django.core.mail import send_mail
from django.http import FileResponse, HttpResponse
from django.template.loader import render_to_string
from rest_framework import exceptions, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from base.utils import mime_type
from competition.exceptions import FreezingNotClosedResults
from competition.models import (Comment, Competition, CompetitionType, Event,
                                EventRegistration, Grade, LateTag, Problem,
                                Publication, PublicationType, Semester, Series,
                                Solution, Vote)
from competition.permissions import (CommentPermission,
                                     CompetitionRestrictedPermission,
                                     ProblemPermission)
from competition.serializers import (CommentSerializer, CompetitionSerializer,
                                     CompetitionTypeSerializer,
                                     EventRegistrationSerializer,
                                     EventSerializer, GradeSerializer,
                                     LateTagSerializer, ProblemSerializer,
                                     ProblemWithSolutionsSerializer,
                                     PublicationSerializer,
                                     PublicationTypeSerializer,
                                     SemesterSerializer,
                                     SemesterWithProblemsSerializer,
                                     SeriesWithProblemsSerializer,
                                     SolutionSerializer)
from competition.utils import sum_methods
from competition.utils.results import (generate_praticipant_invitations,
                                       rank_results)
from personal.models import Profile, School
from personal.serializers import ProfileExportSerializer, SchoolSerializer
from webstrom.settings import EMAIL_ALERT, EMAIL_NO_REPLY

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
        series_sum_func = getattr(sum_methods, series.sum_method or '',
                                  sum_methods.series_simple_sum)
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


class CompetitionViewSet(mixins.RetrieveModelMixin,
                         mixins.UpdateModelMixin,
                         mixins.ListModelMixin,
                         viewsets.GenericViewSet):
    """Naše aktivity"""
    queryset = Competition.objects.all()
    serializer_class = CompetitionSerializer
    permission_classes = (CompetitionRestrictedPermission,)

    @action(detail=False, url_path=r'slug/(?P<slug>\w+)')
    def slug(self, request: Request, slug: str = None) -> Response:
        competition: Competition = self.get_queryset().get(slug=slug)
        return Response(
            CompetitionSerializer(competition, many=False).data
        )


class CompetitionTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = CompetitionType.objects.all()
    serializer_class = CompetitionTypeSerializer


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

        send_mail(
            'Zverejnený komentár',
            render_to_string('competition/emails/comment_published.txt'),
            EMAIL_NO_REPLY,
            [comment.posted_by.email],
        )

        comment.save()

        return Response("Komentár bol publikovaný.", status=status.HTTP_200_OK)

    @action(methods=['post'], detail=True)
    def hide(self, request, pk=None):
        """Skrytie komentára"""
        comment = self.get_object()
        comment.hide(message=request.data.get('hidden_response'))

        send_mail(
            'Skrytý komentár',
            render_to_string('competition/emails/comment_hidden.txt'),
            EMAIL_NO_REPLY,
            [comment.posted_by.email],
        )

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
    permission_classes = (ProblemPermission,)
    MAX_SUBMITTED_SOLUTIONS = 10

    def perform_create(self, serializer):
        """
        Volá sa pri vytvarani objektu,
        checkuju sa tu permissions, ci user vie vytvorit problem v danej sutazi
        """
        if Problem.can_user_create(self.request.user, serializer.validated_data):
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
        also_publish = problem.can_user_modify(request.user)

        problem.add_comment(request.data['text'], request.user, also_publish)

        send_mail(
            'Nový komentár',
            render_to_string('competition/emails/comment_added.txt'),
            EMAIL_NO_REPLY,
            [EMAIL_ALERT],
        )

        return Response("Komentár bol pridaný", status=status.HTTP_201_CREATED)

    @action(methods=['get'], detail=True, permission_classes=[IsAdminUser])
    def stats(self, request, pk=None):
        """Vráti štatistiky úlohy (histogram, počet riešiteľov...)"""
        return Response(self.get_object().get_stats())

    @action(methods=['post'], detail=True, url_name='upload-solution', url_path='upload-solution')
    def upload_solution(self, request, pk=None):
        """Nahrá užívateľské riešenie k úlohe"""
        problem: Problem = self.get_object()
        if not problem.series.can_submit:
            raise exceptions.ValidationError(
                detail='Túto úlohu už nie je možné odovzdať.')
        event_registration = EventRegistration.get_registration_by_profile_and_event(
            request.user.profile, problem.series.semester)

        if 'file' not in request.FILES:
            raise exceptions.ParseError(detail='Request neobsahoval súbor')

        file = request.FILES['file']

        if file.size > 20971520:  # 20 MB
            raise exceptions.ParseError(
                detail='Riešenie prekročilo maximálnu povolenú veľkosť',
            )

        if mime_type(file) != 'application/pdf':
            raise exceptions.ParseError(
                detail='Riešenie nie je vo formáte pdf')
        late_tag = problem.series.get_actual_late_flag()
        existing_solutions = Solution.objects.filter(
            problem=problem, semester_registration=event_registration)
        if len(existing_solutions) > 0 and late_tag is not None and not late_tag.can_resubmit:
            raise exceptions.ValidationError(
                detail='Túto úlohu už nie je možné odovzdať znova.')
        solution = Solution.objects.create(
            problem=problem,
            semester_registration=event_registration,
            late_tag=late_tag,
            is_online=True
        )

        # delete solutions until there is less than allowed amount
        while len(existing_solutions) > self.MAX_SUBMITTED_SOLUTIONS - 1:
            Solution.objects.filter(
                problem=problem, semester_registration=event_registration)\
                .earliest('uploaded_at').delete()
        solution.solution.save(
            solution.get_solution_file_name(), file, save=True)

        return Response(status=status.HTTP_201_CREATED)

    @action(methods=['post'], detail=True, url_name='upload-model-solution',
            url_path='upload-model-solution',  permission_classes=[IsAdminUser])
    def upload_model_solution(self, request, pk=None):
        """Nahrá užívateľské riešenie k úlohe"""
        problem: Problem = self.get_object()
        if 'file' not in request.FILES:
            raise exceptions.ParseError(detail='Požiadavka neobsahovala súbor')
        file = request.FILES['file']
        if mime_type(file) != 'application/pdf':
            raise exceptions.ParseError(
                detail='Riešenie nie je vo formáte pdf')
        problem.solution_pdf.save(
            f'vzorak-{problem.pk}.pdf', file, save=True
        )

        return Response(status=status.HTTP_201_CREATED)

    @action(detail=True, url_path='my-solution')
    def my_solution(self, request, pk=None):
        """Vráti riešenie k úlohe pre práve prihláseného užívateľa"""
        problem: Problem = self.get_object()
        event_registration = EventRegistration.get_registration_by_profile_and_event(
            request.user.profile, problem.series.semester)
        solution: Solution = Solution.objects.filter(
            problem=problem, semester_registration=event_registration).latest('uploaded_at')
        file = solution.solution
        if not file:
            raise exceptions.NotFound(
                detail='Zatiaľ nebolo nahraté žiadne riešenie')
        return FileResponse(
            file, content_type='application/pdf')

    @action(detail=True, url_path='corrected-solution')
    def corrected_solution(self, request, pk=None):
        """Vráti opravené riešenie k úlohe pre práve prihláseného užívateľa"""
        problem: Problem = self.get_object()
        event_registration = EventRegistration.get_registration_by_profile_and_event(
            request.user.profile, problem.series.semester)
        solution: Solution = Solution.objects.filter(
            problem=problem, semester_registration=event_registration).latest('uploaded_at')
        file = solution.corrected_solution
        if not file:
            raise exceptions.NotFound(
                detail='Toto riešenie ešte nie je opravené')
        return FileResponse(
            file, content_type='application/pdf')

    @action(methods=['get'], detail=True, permission_classes=[IsAdminUser],
            url_path='download-solutions')
    def download_solutions(self, request, pk=None):
        """Vráti .zip archív všetkých užívateľských riešení k úlohe"""
        solutions = self.get_object().solution_set.all()
        # Open StringIO to grab in-memory ZIP contents
        stream = BytesIO()
        with zipfile.ZipFile(stream, 'w') as zipf:
            for solution in solutions:
                if solution.solution.name:
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
            raise exceptions.ParseError(detail='Nie je priložený súbor')

        zfile = request.data['file']

        if not zipfile.is_zipfile(zfile):
            raise exceptions.ParseError(
                detail='Priložený súbor nie je súbor s príponou zip.')

        with zipfile.ZipFile(zfile) as zfile:
            if zfile.testzip():
                raise exceptions.ParseError(detail='Súbor zip je poškodený')

            parsed_filenames = []
            errors = []

            # TODO: checks file are really pdfs
            for filename in filter(lambda filename: filename.endswith('.pdf'), zfile.namelist()):
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
                        'status': 'Nie je možné analyzovať súbor'
                    })
                    continue
                except EventRegistration.DoesNotExist:
                    errors.append({
                        'filename': filename,
                        'status': f'Registrácia používateľa s id {registration_pk} neexistuje'
                    })
                    continue
                except Solution.DoesNotExist:
                    errors.append({
                        'filename': filename,
                        'status': f'Riešenie s registračným id {registration_pk}'
                        f'a id úlohy {problem_pk} neexistuje'
                    })
                    continue

                parsed_filenames.append((filename, score, solution))

            if errors:
                return Response(errors, status=status.HTTP_400_BAD_REQUEST)

            for filename, score, solution in parsed_filenames:
                with zfile.open(filename) as corrected_solution:
                    solution.score = score
                    solution.corrected_solution = File(corrected_solution)

                    solution.save()

            return Response()


class ProblemAdministrationViewSet(ModelViewSetWithSerializerContext):
    queryset = Problem.objects.all()
    serializer_class = ProblemWithSolutionsSerializer
    permission_classes = (IsAdminUser,)

    @action(methods=['post'], detail=True, url_path='upload-points')
    def upload_points(self, request, pk=None):
        problem = self.get_object()
        solutions = request.data['solution_set']
        for solution_dict in solutions:
            solution = Solution.objects.get(pk=solution_dict['id'])
            if solution.problem != problem:
                continue
            solution.score = solution_dict['score']
            solution.save()
        return Response(status=status.HTTP_200_OK)


class SeriesViewSet(ModelViewSetWithSerializerContext):
    """
    Obsluhuje API endpoint pre Úlohy
    """
    queryset = Series.objects.all()
    serializer_class = SeriesWithProblemsSerializer
    permission_classes = (CompetitionRestrictedPermission,)
    http_method_names = ['get', 'head', 'put', 'patch', "post"]

    def perform_create(self, serializer):
        """
        Vola sa pri vytvarani objektu,
        checkuju sa tu permissions, ci user vie vytvorit semester v danej sutazi
        """
        if Series.can_user_create(self.request.user, serializer.validated_data):
            serializer.save()
        else:
            raise exceptions.PermissionDenied(
                'Nedostatočné práva na vytvorenie tohoto objektu')

    @staticmethod
    def __create_result_json(series: Series) -> dict:
        results = []
        for registration in series.semester.eventregistration_set.all():
            results.append(
                generate_result_row(registration, only_series=series)
            )
        results.sort(key=itemgetter('total'), reverse=True)
        return rank_results(results)

    @action(methods=['get'], detail=True)
    def results(self, request: Request, pk: Optional[int] = None):
        """Vráti výsledkovku pre sériu"""
        series = self.get_object()
        if series.frozen_results is not None:
            return series.frozen_results
        results = self.__create_result_json(series)
        return Response(results, status=status.HTTP_200_OK)

    @action(methods=['post'], detail=True, url_path='results/freeze')
    def freeze_results(self, request: Request, pk: Optional[int] = None):
        series: Series = self.get_object()
        try:
            series.freeze_results(self.__create_result_json(series))
        except FreezingNotClosedResults as exc:
            raise exceptions.MethodNotAllowed(
                method='series/results/freeze',
                detail='Séria nemá opravené všetky úlohy a teda sa nedá uzavrieť.') from exc
        try:
            series.semester.freeze_results()
        except FreezingNotClosedResults:
            pass
        return Response('Séria bola uzavretá', status=status.HTTP_200_OK)

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
        ).current().series_set.filter(frozen_results__isnull=True)\
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

    @action(methods=['get'], detail=True, url_path='file-solution')
    def file_solution(self, request, pk=None):
        """Stiahne riešenie"""
        solution = self.get_object()
        file = solution.solution
        if not file:
            raise exceptions.NotFound(
                detail='Zatiaľ nebolo nahraté žiadne riešenie')
        return FileResponse(
            file, content_type='application/pdf',
        )

    @action(methods=['get'], detail=True, url_path='file-corrected')
    def file_corrected(self, request, pk=None):
        """Stiahne opravenú verziu riešenia"""
        solution = self.get_object()
        file = solution.corrected_solution
        if not file:
            raise exceptions.NotFound(
                detail='Zatiaľ nebolo nahraté žiadne riešenie')
        return FileResponse(
            file, content_type='application/pdf',
        )

    @action(methods=['post'], detail=True,
            url_path='upload-solution-file',
            permission_classes=[IsAdminUser])
    def upload_solution_file(self, request, pk=None):
        solution: Solution = self.get_object()
        if 'file' not in request.FILES:
            raise exceptions.ParseError(detail='Požiadavka neobsahovala súbor')

        file = request.FILES['file']
        if mime_type(file) != 'application/pdf':
            raise exceptions.ParseError(
                detail='Riešenie nie je vo formáte pdf')
        solution.solution.save(
            solution.get_solution_file_name(), file, save=True
        )
        return Response(status=status.HTTP_201_CREATED)

    @action(methods=['post'], detail=True,
            url_path='upload-corrected-solution-file',
            permission_classes=[IsAdminUser])
    def upload_corrected_solution_file(self, request, pk=None):
        solution: Solution = self.get_object()
        if 'file' not in request.FILES:
            raise exceptions.ParseError(detail='Požiadavka neobsahovala súbor')

        file = request.FILES['file']
        if mime_type(file) != 'application/pdf':
            raise exceptions.ParseError(
                detail='Riešenie nie je vo formáte pdf')
        solution.corrected_solution.save(
            solution.get_corrected_solution_file_name(), file, save=True
        )
        return Response(status=status.HTTP_201_CREATED)


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
    http_method_names = ['get', 'head', 'put', 'patch', 'post']

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
        results = rank_results(results)
        return results

    @action(methods=['post'], detail=True, url_path='results/freeze')
    def freeze_results(self, request: Request, pk: Optional[int] = None):
        semester: Semester = self.get_object()
        try:
            semester.freeze_results(self.semester_results(semester))
        except FreezingNotClosedResults as exc:
            raise exceptions.MethodNotAllowed(
                method='series/results/freeze',
                detail='Semester nemá uzavreté všetky série a teda sa nedá uzavrieť.') from exc
        return Response('Semester bol uzavretý', status=status.HTTP_200_OK)

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
        participants = generate_praticipant_invitations(
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
        participants = generate_praticipant_invitations(
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

    def __get_participants(self):
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
        serializer = ProfileExportSerializer(profiles, many=True)
        return serializer

    @action(methods=['get'], detail=True)
    def participants(self, request, pk=None):
        """Vráti všetkých užívateľov zapojených do semestra"""
        serializer = self.__get_participants()
        return Response(serializer.data)

    @action(methods=['get'], detail=True, url_path='participants-export')
    def participants_export(self, request, pk=None):
        """Vráti všetkých užívateľov zapojených do semestra"""
        serializer = self.__get_participants()
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="export.csv"'
        header = ProfileExportSerializer.Meta.fields
        writer = csv.DictWriter(response, fieldnames=header)
        writer.writeheader()
        writer.writerows(serializer.data)
        return response

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
        if Event.can_user_create(self.request.user, serializer.validated_data):
            serializer.save()
        else:
            raise exceptions.PermissionDenied(
                'Nedostatočné práva na vytvorenie tohoto objektu')

    @action(methods=['post'], detail=True, permission_classes=[IsAuthenticated])
    def register(self, request, pk=None):
        """Registruje prihláseného užívateľa na akciu"""
        event: Event = self.get_object()
        profile = request.user.profile
        if not event.is_active:
            raise ValidationError('Súťaž aktuálne neprebieha.')
        if not event.can_user_participate(request.user):
            raise ValidationError(
                'Používateľa nie je možné registrovať - Zlá veková kategória')
        if EventRegistration.get_registration_by_profile_and_event(
                profile, event):
            raise ValidationError('Používateľ je už zaregistrovaný')
        EventRegistration.objects.create(
            event=event,
            school=profile.school,
            profile=profile,
            grade=Grade.get_grade_by_year_of_graduation(
                profile.year_of_graduation),
        )

        return Response(status=status.HTTP_201_CREATED)

    @action(
        methods=['get'],
        detail=True,
        permission_classes=[IsAuthenticated],
        url_path='can-participate'
    )
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

    @action(methods=['get'], detail=False, permission_classes=[IsAuthenticated])
    def active(self, request):
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


class PublicationTypeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = PublicationType.objects.all()
    serializer_class = PublicationTypeSerializer


class PublicationViewSet(viewsets.ModelViewSet):
    """Publikácie(výsledky, brožúrky, časopisy, ...)"""
    queryset = Publication.objects.all()
    serializer_class = PublicationSerializer
    permission_classes = (CompetitionRestrictedPermission,)

    def perform_create(self, serializer):
        '''
        Vola sa pri vytvarani objektu,
        checkuju sa tu permissions, ci user vie vytvorit publication v danom evente
        '''
        if Publication.can_user_create(self.request.user, serializer.validated_data):
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
    def upload_publication(self, request: Request):
        """Nahrá súbor publikácie"""
        if 'file' not in request.data:
            raise exceptions.ParseError(detail='Požiadavka neobsahovala súbor')

        file = request.data['file']
        if mime_type(file) not in ['application/pdf', 'application/zip']:
            raise exceptions.ParseError(detail='Nesprávny formát')

        event = Event.objects.filter(pk=int(request.data['event'])).first()
        publication_type = PublicationType.objects.get(
            name=request.data['publication_type'])
        order = int(request.data.get('order'))

        publication = Publication.objects.filter(
            event=event, order=order).first()
        if publication is None:
            publication = Publication(
                name=request.data.get('name'),
                file=file,
                event=event,
                order=order,
                publication_type=publication_type
            )
            publication.generate_name()
            publication.save()

        publication.file.save(publication.name, file)
        return Response(status=status.HTTP_201_CREATED)


class GradeViewSet(viewsets.ReadOnlyModelViewSet):
    """Ročníky riešiteľov (Z9,S1 ...)"""
    queryset = Grade.objects.filter(is_active=True).all()
    serializer_class = GradeSerializer


class LateTagViewSet(viewsets.ReadOnlyModelViewSet):
    """Omeškania"""
    queryset = LateTag.objects.all()
    serializer_class = LateTagSerializer
