# -*- coding: utf-8 -*-
# Generated by Django 1.11.4 on 2018-08-28 14:45
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0008_connectmodel'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='statemodel',
            options={'verbose_name': 'State', 'verbose_name_plural': 'States'},
        ),
    ]