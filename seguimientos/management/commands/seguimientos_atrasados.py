from datetime import date
from django.core.management.base import BaseCommand, CommandError
from seguimientos.models import Seguimiento
from seguimientos.servicios import tablero


class Command(BaseCommand):
    help = "Lista seguimientos atrasados; no envía comunicaciones."

    def add_arguments(self, parser):
        parser.add_argument("--fecha", type=date.fromisoformat)

    def handle(self, *args, **options):
        for seguimiento in Seguimiento.objects.filter(cerrado=False).select_related("orden"):
            if tablero(seguimiento, hoy=options.get("fecha"))["estado"] == "atrasado":
                self.stdout.write(f"{seguimiento.pk}\t{seguimiento.nit}\t{seguimiento.razon_social}")
