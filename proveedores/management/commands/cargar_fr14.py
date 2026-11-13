"""Carga auditada del catálogo FR14 desde un CSV UTF-8."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from cuentas.models import ROLES_ADMIN, Usuario
from proveedores import servicios
from proveedores.models import VersionMatriz


class Command(BaseCommand):
    help = "Carga el catálogo FR14 sin duplicados. Exige actor administrativo activo y motivo."

    def add_arguments(self, parser):
        parser.add_argument("--matriz", type=int, default=1, help="Número de versión en borrador (por defecto 1).")
        parser.add_argument("archivo", help="Ruta del CSV UTF-8.")
        parser.add_argument("--actor", required=True, help="Correo de un administrador o desarrollador activo.")
        parser.add_argument("--motivo", required=True, help="Motivo que se conservará en la bitácora.")

    def handle(self, *args, **options):
        actor = Usuario.objects.filter(correo__iexact=options["actor"].strip(), activo=True, rol__in=ROLES_ADMIN).first()
        if actor is None:
            raise CommandError("El actor debe ser un administrador o desarrollador activo existente.")
        version = VersionMatriz.objects.filter(numero=options["matriz"]).first()
        if version is None:
            raise CommandError("La versión indicada no existe.")
        try:
            with open(options["archivo"], "rb") as archivo:
                resumen = servicios.cargar_fr14(archivo, actor=actor, motivo=options["motivo"], version=version)
        except (OSError, PermissionDenied) as error:
            raise CommandError(str(error)) from None
        except ValidationError as error:
            raise CommandError("\n".join(error.messages)) from None
        self.stdout.write(self.style.SUCCESS(
            "Carga completada: " + ", ".join(f"{clave}={valor}" for clave, valor in resumen.items())
        ))
