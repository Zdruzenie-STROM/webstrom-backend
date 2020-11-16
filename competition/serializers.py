from rest_framework import serializers
from competition import models
from profile.serializers import ProfileShortSerializer, SchoolShortSerializer


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Event
        fields = '__all__'


class EventRegistrationSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.EventRegistration
        fields = ['school', 'grade', 'profile']
    school = SchoolShortSerializer(many=False)
    grade = serializers.SlugRelatedField(
        slug_field='tag', many=False, read_only=True)
    profile = ProfileShortSerializer(many=False)


class ProblemSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Problem
        fields = '__all__'


class VoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Vote
        fields = '__all__'


class SolutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Solution
        fields = '__all__'
    votes = VoteSerializer(many=True)


# class ProblemStatsSerializer(serializers.Serializer):
#    historgram = HistrogramItemSerializer(many=True)
#    num_solutions = serializers.IntegerField()
#   mean = serializers.FloatField()
#

class SeriesSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Series
        exclude = ['sum_method']


class SeriesWithProblemsSerializer(serializers.ModelSerializer):
    problems = ProblemSerializer(many=True)

    class Meta:
        model = models.Series
        exclude = ['sum_method']

    def create(self, validated_data):
        problem_data = validated_data.pop('problems')
        series = models.Series.objects.create(**validated_data)
        for data in problem_data:
            models.Problem.objects.create(series=series, **data)
        return series


class SemesterSerializer(serializers.ModelSerializer):
    series_set = SeriesSerializer(many=True)

    class Meta:
        model = models.Semester
        fields = '__all__'


class SemesterWithProblemsSerializer(serializers.ModelSerializer):
    series_set = SeriesWithProblemsSerializer(many=True)

    class Meta:
        model = models.Semester
        fields = '__all__'
