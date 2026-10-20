import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_alter_decision_council"),
        (
            "councillors",
            "0003_remove_enrichedcouncillor_ee_division_id_and_more",
        ),
    ]

    operations = [
        migrations.RenameField(
            model_name="scrapedcouncillor",
            old_name="council_id",
            new_name="council",
        ),
        migrations.AlterField(
            model_name="scrapedcouncillor",
            name="council",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="scraped_councillors",
                to="core.council",
            ),
        ),
    ]
