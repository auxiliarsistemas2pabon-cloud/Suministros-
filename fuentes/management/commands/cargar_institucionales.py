import json
from pathlib import Path

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from cuentas.models import Usuario
from fuentes.servicios import cargar, preparar


class Command(BaseCommand):
    help = "Carga fuentes reales y cortes de numeración sin crear firmas, compras ni proveedores ficticios."

    def add_arguments(self, parser):
        parser.add_argument("directorio", type=Path)
        parser.add_argument("--corte", type=Path, required=True)
        parser.add_argument("--actor-id", type=int, required=True)
        parser.add_argument("--motivo", required=True)
        parser.add_argument("--verificar", action="store_true", help="Valida los archivos sin guardar datos.")

    def handle(self, *args, **options):
        try:
            actor = Usuario.objects.get(pk=options["actor_id"])
            corte = json.loads(options["corte"].read_text(encoding="utf-8"))
            fuentes = preparar(options["directorio"], corte)
            if options["verificar"]:
                self.stdout.write(f"Fuentes válidas: {len(fuentes)}; series verificadas: {len(corte['series'])}.")
                return
            resultado = cargar(fuentes, corte, actor=actor, motivo=options["motivo"])
        except (OSError, ValueError, KeyError, Usuario.DoesNotExist, ValidationError, PermissionDenied) as error:
            raise CommandError(str(error)) from None
        self.stdout.write(self.style.SUCCESS(json.dumps(resultado, ensure_ascii=False)))
