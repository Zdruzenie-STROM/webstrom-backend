from django_typomatic import ts_interface
from rest_framework import serializers

from personal.serializers import ProfileShortSerializer, SchoolShortSerializer
from competition import models


class ModelWithParticipationSerializer(serializers.ModelSerializer):
    can_participate = serializers.SerializerMethodField('get_can_participate')
    is_registered = serializers.SerializerMethodField('get_is_registered')

    def get_can_participate(self, obj):
        if 'request' in self.context and hasattr(self.context['request'].user, 'profile'):
            return obj.can_user_participate(self.context['request'].user)
        return None

    def get_event(self, obj):
        return obj

    def get_is_registered(self, obj):
        if 'request' in self.context and hasattr(self.context['request'].user, 'profile'):
            return models.EventRegistration.get_registration_by_profile_and_event(
                self.context['request'].user.profile, self.get_event(obj)
            ) is not None
        return None


@ts_interface(context='competition')
class UnspecifiedPublicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.UnspecifiedPublication
        fields = '__all__'


@ts_interface(context='competition')
class SemesterPublicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.SemesterPublication
        fields = '__all__'


@ts_interface(context='competition')
class RegistrationLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.RegistrationLink
        fields = '__all__'


@ts_interface(context='competition')
class EventSerializer(ModelWithParticipationSerializer):
    unspecifiedpublication_set = UnspecifiedPublicationSerializer(many=True)
    registration_links = RegistrationLinkSerializer(many=True)

    class Meta:
        model = models.Event
        fields = '__all__'


@ts_interface(context='competition')
class CompetitionSerializer(serializers.ModelSerializer):
    event_set = EventSerializer(many=True)

    class Meta:
        model = models.Competition
        fields = '__all__'


@ts_interface(context='competition')
class EventRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.EventRegistration
        fields = ['school', 'grade', 'profile']
    school = SchoolShortSerializer(many=False)
    grade = serializers.SlugRelatedField(
        slug_field='tag', many=False, read_only=True)
    profile = ProfileShortSerializer(many=False)


@ts_interface(context='competition')
class ProblemSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Problem
        fields = '__all__'
        read_only_fields = ['series']

    submitted = serializers.SerializerMethodField(
        'submitted_solution')

    def submitted_solution(self, obj):
        if 'request' in self.context:
            if (
                self.context['request'].user.is_anonymous or
                not hasattr(self.context['request'].user, 'profile')
            ):
                return None

            semester_registration = models.EventRegistration.get_registration_by_profile_and_event(
                self.context['request'].user.profile, obj.series.semester)

            try:
                solution = obj.solution_set.get(
                    semester_registration=semester_registration)
            except models.Solution.DoesNotExist:
                return None
            return SolutionSerializer(solution).data
        return None


@ts_interface(context='competition')
class CommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Comment
        fields = '__all__'

    posted_by_name = serializers.SerializerMethodField('get_posted_by_name')
    edit_allowed = serializers.SerializerMethodField('can_edit')

    def get_posted_by_name(self, obj):
        return obj.user.get_full_name()

    def can_edit(self, obj):
        if 'request' in self.context:
            return obj.can_user_modify(self.context['request'].user)
        return None


@ts_interface(context='competition')
class SolutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Solution
        fields = '__all__'


# class ProblemStatsSerializer(serializers.Serializer):
#    historgram = HistrogramItemSerializer(many=True)
#    num_solutions = serializers.IntegerField()
#   mean = serializers.FloatField()
#

@ts_interface(context='competition')
class SeriesSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Series
        exclude = ['sum_method']


@ts_interface(context='competition')
class SeriesWithProblemsSerializer(ModelWithParticipationSerializer):
    problems = ProblemSerializer(many=True)
    can_submit = serializers.SerializerMethodField('get_can_submit')

    class Meta:
        model = models.Series
        exclude = ['sum_method']
        read_only_fields = ['semester']

    def get_can_submit(self, obj):
        return obj.can_submit

    def get_event(self, obj):
        return obj.semester

    def create(self, validated_data):
        problem_data = validated_data.pop('problems')
        series = models.Series.objects.create(**validated_data)
        for data in problem_data:
            models.Problem.objects.create(series=series, **data)
        return series


@ts_interface(context='competition')
class SemesterSerializer(serializers.ModelSerializer):
    series_set = SeriesSerializer(many=True)

    class Meta:
        model = models.Semester
        fields = '__all__'

    def create(self, validated_data):
        series_data = validated_data.pop('series_set')
        semester = models.Semester.objects.create(**validated_data)
        for series in series_data:
            models.Series.objects.create(semester=semester, **series)
        return semester


@ts_interface(context='competition')
class SemesterWithProblemsSerializer(ModelWithParticipationSerializer):
    series_set = SeriesWithProblemsSerializer(many=True)
    semesterpublication_set = SemesterPublicationSerializer(many=True)
    unspecifiedpublication_set = UnspecifiedPublicationSerializer(many=True)

    class Meta:
        model = models.Semester
        fields = '__all__'
        read_only_fields = ['semesterpublication_set',
                            'unspecifiedpublication_set']

    def create(self, validated_data):
        all_series_data = validated_data.pop('series_set')
        late_tags = validated_data.pop('late_tags')
        validated_data.pop('semesterpublication_set')
        validated_data.pop('unspecifiedpublication_set')
        semester = models.Semester.objects.create(**validated_data)
        for series_data in all_series_data:
            problems_data = series_data.pop('problems')
            series = models.Series.objects.create(
                semester=semester, **series_data)
            for problem in problems_data:
                models.Problem.objects.create(series=series, **problem)
        for tag in late_tags:
            semester.late_tags.add(tag)
        return semester


@ts_interface(context='competition')
class LateTagSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.LateTag
        exclude = ['comment']


@ts_interface(context='competition')
class GradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Grade
        exclude = ['is_active']
