# Generated by Django 4.2.16 on 2024-11-24 11:59

import django.core.validators
from django.db import migrations, models
import personal.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='County',
            fields=[
                ('code', models.AutoField(primary_key=True, serialize=False, verbose_name='kód')),
                ('name', models.CharField(max_length=30, verbose_name='názov')),
            ],
            options={
                'verbose_name': 'kraj',
                'verbose_name_plural': 'kraje',
            },
        ),
        migrations.CreateModel(
            name='District',
            fields=[
                ('code', models.AutoField(primary_key=True, serialize=False, verbose_name='kód')),
                ('name', models.CharField(max_length=30, verbose_name='názov')),
                ('abbreviation', models.CharField(max_length=2, verbose_name='skratka')),
            ],
            options={
                'verbose_name': 'okres',
                'verbose_name_plural': 'okresy',
            },
        ),
        migrations.CreateModel(
            name='School',
            fields=[
                ('code', models.AutoField(primary_key=True, serialize=False, verbose_name='kód')),
                ('name', models.CharField(max_length=100, verbose_name='názov')),
                ('abbreviation', models.CharField(max_length=10, verbose_name='skratka')),
                ('street', models.CharField(max_length=100, verbose_name='ulica')),
                ('city', models.CharField(max_length=100, verbose_name='obec')),
                ('zip_code', models.CharField(max_length=6, verbose_name='PSČ')),
                ('email', models.CharField(blank=True, max_length=50, verbose_name='email')),
                ('district', models.ForeignKey(on_delete=models.SET(personal.models.unspecified_district), to='personal.district', verbose_name='okres')),
            ],
            options={
                'verbose_name': 'škola',
                'verbose_name_plural': 'školy',
            },
        ),
        migrations.CreateModel(
            name='Profile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('first_name', models.CharField(max_length=150, verbose_name='krstné meno')),
                ('last_name', models.CharField(max_length=150, verbose_name='priezvisko')),
                ('year_of_graduation', models.PositiveSmallIntegerField(verbose_name='rok maturity')),
                ('phone', models.CharField(blank=True, help_text='Telefonné číslo v medzinárodnom formáte (napr. +421 123 456 789).', max_length=32, null=True, validators=[django.core.validators.RegexValidator(message='Zadaj telefónne číslo vo formáte +421 123 456 789 alebo 0912 345 678.', regex='^(\\+\\d{1,3}\\d{9})$')], verbose_name='telefónne číslo')),
                ('parent_phone', models.CharField(blank=True, help_text='Telefonné číslo v medzinárodnom formáte (napr. +421 123 456 789).', max_length=32, null=True, validators=[django.core.validators.RegexValidator(message='Zadaj telefónne číslo vo formáte +421 123 456 789 alebo 0912 345 678.', regex='^(\\+\\d{1,3}\\d{9})$')], verbose_name='telefónne číslo na rodiča')),
                ('school', models.ForeignKey(on_delete=models.SET(personal.models.unspecified_school), to='personal.school', verbose_name='škola')),
            ],
            options={
                'verbose_name': 'profil',
                'verbose_name_plural': 'profily',
            },
        ),
    ]
