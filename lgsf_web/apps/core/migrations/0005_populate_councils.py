from django.db import migrations

# (code, name, territory)
COUNCILS = [
    ("RCT", "Rhondda Cynon Taf County Borough Council", "WLS"),
    ("TAM", "Tameside Metropolitan Borough Council", "ENG"),
    ("TRF", "Trafford Metropolitan Borough Council", "ENG"),
    ("WGN", "Wigan Metropolitan Borough Council", "ENG"),
    ("RCH", "Rochdale Metropolitan Borough Council", "ENG"),
    ("SLF", "Salford City Council", "ENG"),
    ("BUR", "Bury Metropolitan Borough Council", "ENG"),
    ("OLD", "Oldham Metropolitan Borough Council", "ENG"),
    ("MAN", "Manchester City Council", "ENG"),
    ("SKP", "Stockport Metropolitan Borough Council", "ENG"),
    ("AGY", "Isle of Anglesey County Council", "WLS"),
    ("BGE", "Bridgend County Borough Council", "WLS"),
    ("CRF", "City of Cardiff Council", "WLS"),
    ("CWY", "Conwy County Borough Council", "WLS"),
    ("DEN", "Denbighshire County Council", "WLS"),
    ("FLN", "Flintshire County Council", "WLS"),
    ("GWN", "Gwynedd Council", "WLS"),
    ("MON", "Monmouthshire County Council", "WLS"),
    ("MTY", "Merthyr Tydfil County Borough Council", "WLS"),
    ("PEM", "Pembrokeshire County Council", "WLS"),
    ("POW", "Powys County Council", "WLS"),
    ("SWA", "City and County of Swansea Council", "WLS"),
    ("WRX", "Wrexham County Borough Council", "WLS"),
    ("NTL", "Neath Port Talbot County Borough Council", "WLS"),
    ("CMN", "Carmarthenshire County Council", "WLS"),
    ("NWP", "Newport City Council", "WLS"),
]


def create_councils(apps, schema_editor):
    Council = apps.get_model("core", "Council")
    for code, name, territory in COUNCILS:
        Council.objects.update_or_create(
            code=code, defaults={"name": name, "territory": territory}
        )


def delete_councils(apps, schema_editor):
    Council = apps.get_model("core", "Council")
    Council.objects.filter(code__in=[c[0] for c in COUNCILS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_council"),
    ]

    operations = [
        migrations.RunPython(create_councils, delete_councils),
    ]
