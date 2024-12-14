from django.core.management import BaseCommand

from data_migration.data_dump import dump_data


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument("db", type=str)

    def handle(self, *args, **options):
        dump_data(options['db'])
