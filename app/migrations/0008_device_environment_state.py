# -*- coding: utf-8 -*-
# Generated by Django 1.11.4 on 2018-03-26 00:02
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0007_auto_20180325_2318'),
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='environment_state',
            field=django.contrib.postgres.fields.jsonb.JSONField(default=None),
            preserve_default=False,
        ),
    ]
