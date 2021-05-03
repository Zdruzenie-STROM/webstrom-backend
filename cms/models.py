from django.contrib.sites.models import Site
from django.db import models
from django.utils.timezone import now


class Post(models.Model):
    class Meta:
        verbose_name = 'príspevok'
        verbose_name_plural = 'príspevky'
        ordering = ['-added_at', ]

    caption = models.CharField(verbose_name='nadpis', max_length=50)
    short_text = models.CharField(
        verbose_name='krátky text',
        help_text='Krátky 1-2 vetový popis.',
        max_length=200)
    details = models.TextField(
        verbose_name='podrobnosti k príspevku',
        help_text='Dlhší text, ktorý sa zobrazí po rozkliknutí.',
        blank=True)
    added_at = models.DateTimeField(verbose_name='pridané',
                                    auto_now_add=True,
                                    editable=False)
    show_after = models.DateTimeField(verbose_name='zobrazuj od')
    disable_after = models.DateTimeField(verbose_name='zobrazuj do')
    sites = models.ManyToManyField(Site)

    def is_visible(self):
        return now() > self.show_after and now() < self.disable_after
    is_visible.short_description = "Viditeľný"
    is_visible = property(is_visible)

    def __str__(self):
        return f'{self.pk}-{self.caption}'


class PostLink(models.Model):
    class Meta:
        verbose_name = 'link k príspevku'
        verbose_name_plural = 'linky k príspevkom'

    post = models.ForeignKey(
        Post,
        verbose_name='Relevantný príspevok',
        related_name='links',
        on_delete=models.CASCADE)
    caption = models.CharField(
        verbose_name='názov',
        help_text='Nápis, ktorý po kliknutí presmeruje na link. Maximálne 2 slová.',
        max_length=25)
    url = models.CharField(verbose_name='URL', max_length=100,
                           help_text='URL stránky kam má preklik viesť')

    def __str__(self):
        return f'{self.post}-{self.caption}'


class MenuItem(models.Model):
    class Meta:
        verbose_name = 'položka v menu'
        verbose_name_plural = 'položky v menu'
        ordering = ['-priority', ]

    caption = models.CharField(
        verbose_name='názov',
        help_text='Nápis, ktorý sa zobrazí v menu. Maximálne 2 slová.',
        max_length=25)
    url = models.CharField(verbose_name='URL',
                           max_length=100,
                           help_text='URL stránky kam má preklik viesť')
    priority = models.SmallIntegerField(
        verbose_name='priorita',
        help_text='Priorita, čím väčšie, tým vyššie v menu.')
    sites = models.ManyToManyField(Site)

    # TODO: Pridať oprávnenia a umožniť tak vedúcovské položky v menu
    # zobrazované aj možno niekde inde
