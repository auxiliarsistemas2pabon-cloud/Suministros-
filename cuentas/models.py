from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower


def normalizar_correo(correo):
    """Correo sin espacios y todo en minúsculas (también el usuario local)."""
    return (correo or "").strip().lower()


class Rol(models.TextChoices):
    COORDINADOR = "coordinador", "Coordinador"
    ADMINISTRADOR = "administrador", "Administrador"
    DESARROLLADOR = "desarrollador", "Desarrollador"
    PROVEEDOR = "proveedor", "Proveedor"


# Roles con acceso a todo el negocio.
ROLES_ADMIN = (Rol.ADMINISTRADOR, Rol.DESARROLLADOR)

# El administrador técnico de Django ("lo técnico") es exclusivo del desarrollador.
MENSAJE_SOLO_DESARROLLADOR = "Solo los desarrolladores pueden acceder al administrador técnico."


class UsuarioManager(BaseUserManager):
    use_in_migrations = True

    def _crear_usuario(self, correo, password, **campos):
        if not correo:
            raise ValueError("El correo es obligatorio.")
        usuario = self.model(correo=normalizar_correo(correo), **campos)
        usuario.set_password(password)
        usuario.full_clean()
        usuario.save(using=self._db)
        return usuario

    def create_user(self, correo, password=None, **campos):
        campos.setdefault("is_staff", False)
        campos.setdefault("is_superuser", False)
        return self._crear_usuario(correo, password, **campos)

    def create_superuser(self, correo, password=None, **campos):
        campos.setdefault("rol", Rol.DESARROLLADOR)
        campos.setdefault("is_staff", True)
        campos.setdefault("is_superuser", True)
        if campos["rol"] != Rol.DESARROLLADOR:
            raise ValueError("El superusuario debe tener rol desarrollador.")
        if campos["is_staff"] is not True or campos["is_superuser"] is not True:
            raise ValueError("El superusuario debe tener is_staff=True e is_superuser=True.")
        return self._crear_usuario(correo, password, **campos)

    def get_by_natural_key(self, correo):
        # Permite ingresar con cualquier combinación de mayúsculas.
        return self.get(correo=normalizar_correo(correo))


class Usuario(AbstractBaseUser, PermissionsMixin):
    correo = models.EmailField(
        "correo electrónico",
        max_length=254,
        unique=True,
        error_messages={"unique": "Ya existe un usuario con este correo."},
    )
    nombre = models.CharField("nombre completo", max_length=150)
    activo = models.BooleanField(
        "activo",
        default=True,
        help_text="Desmarque esta casilla en lugar de borrar el usuario.",
    )
    is_staff = models.BooleanField(
        "acceso al administrador técnico",
        default=False,
        help_text="Solo para desarrolladores (junto con superusuario).",
    )
    rol = models.CharField("rol", max_length=20, choices=Rol.choices)
    area = models.ForeignKey(
        "areas.Area",
        verbose_name="área",
        on_delete=models.PROTECT,
        related_name="usuarios",
        null=True,
        blank=True,
        help_text="Obligatoria para coordinadores; vacía para proveedores.",
    )
    proveedor = models.ForeignKey(
        "proveedores.Proveedor",
        verbose_name="proveedor",
        on_delete=models.PROTECT,
        related_name="usuarios",
        null=True,
        blank=True,
        help_text="Ficha del proveedor al que pertenece. Obligatoria para el rol proveedor; vacía para los demás.",
    )
    debe_cambiar_clave = models.BooleanField("debe cambiar la clave", default=False)
    fecha_creacion = models.DateTimeField("fecha de creación", auto_now_add=True)

    objects = UsuarioManager()

    USERNAME_FIELD = "correo"
    EMAIL_FIELD = "correo"
    REQUIRED_FIELDS = ["nombre"]

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ["nombre", "correo"]
        constraints = [
            # Respaldo en la base de datos de las validaciones de clean(),
            # por si alguien escribe con .update() o SQL directo.
            # Con el correo siempre en minúsculas, unique=True ya impide
            # duplicados sin distinguir mayúsculas.
            models.CheckConstraint(
                condition=Q(correo=Lower("correo")),
                name="usuario_correo_en_minusculas",
                violation_error_message="El correo debe guardarse en minúsculas.",
            ),
            models.CheckConstraint(
                condition=Q(rol__in=Rol.values),
                name="usuario_rol_valido",
                violation_error_message="El rol no es válido.",
            ),
            models.CheckConstraint(
                condition=~Q(rol=Rol.COORDINADOR) | Q(area__isnull=False),
                name="usuario_coordinador_con_area",
                violation_error_message="Un coordinador debe tener un área asignada.",
            ),
            models.CheckConstraint(
                condition=~Q(rol=Rol.PROVEEDOR) | Q(area__isnull=True),
                name="usuario_proveedor_sin_area",
                violation_error_message="Un proveedor no puede tener área.",
            ),
            models.CheckConstraint(
                condition=(Q(rol=Rol.PROVEEDOR) & Q(proveedor__isnull=False))
                | (~Q(rol=Rol.PROVEEDOR) & Q(proveedor__isnull=True)),
                name="usuario_proveedor_con_ficha",
                violation_error_message=(
                    "Un usuario con rol proveedor debe tener la ficha de su proveedor, y los demás roles no pueden tenerla."
                ),
            ),
            models.CheckConstraint(
                condition=Q(rol=Rol.DESARROLLADOR) | Q(is_staff=False, is_superuser=False),
                name="usuario_staff_solo_desarrollador",
                violation_error_message=MENSAJE_SOLO_DESARROLLADOR,
            ),
        ]

    def __str__(self):
        return f"{self.nombre} <{self.correo}>"

    # Django y django-axes consultan is_active; el campo del negocio es "activo".
    @property
    def is_active(self):
        return self.activo

    @is_active.setter
    def is_active(self, valor):
        self.activo = valor

    @property
    def es_admin(self):
        return self.rol in ROLES_ADMIN

    @property
    def puede_usar_admin_tecnico(self):
        return bool(
            self.is_active and self.is_staff and self.is_superuser and self.rol == Rol.DESARROLLADOR
        )

    def get_full_name(self):
        return self.nombre

    def get_short_name(self):
        return self.nombre

    def clean(self):
        super().clean()
        self.correo = normalizar_correo(self.correo)
        errores = {}
        if self.rol == Rol.COORDINADOR and not self.area_id:
            errores["area"] = "Un coordinador debe tener un área asignada."
        if self.rol == Rol.PROVEEDOR and self.area_id:
            errores["area"] = "Un proveedor no puede tener área."
        if self.area_id and not self.area.activa and "area" not in errores:
            area_anterior = (
                Usuario.objects.filter(pk=self.pk).values_list("area_id", flat=True).first() if self.pk else None
            )
            if area_anterior != self.area_id:
                errores["area"] = "El área seleccionada está inactiva. Elija un área activa."
        if self.rol == Rol.PROVEEDOR and not self.proveedor_id:
            errores["proveedor"] = "Un usuario con rol proveedor debe estar asociado a la ficha de su proveedor."
        elif self.rol and self.rol != Rol.PROVEEDOR and self.proveedor_id:
            errores["proveedor"] = "Solo los usuarios con rol proveedor se asocian a un proveedor; deje este campo vacío."
        elif self.proveedor_id and not self.proveedor.activo:
            proveedor_anterior = (
                Usuario.objects.filter(pk=self.pk).values_list("proveedor_id", flat=True).first() if self.pk else None
            )
            if proveedor_anterior != self.proveedor_id:
                errores["proveedor"] = "El proveedor seleccionado está inactivo. Elija un proveedor activo."
        if self.rol and self.rol != Rol.DESARROLLADOR and (self.is_staff or self.is_superuser):
            # El error va en "rol" (la causa), que está en todos los formularios;
            # is_staff/is_superuser no existen en los formularios del panel.
            errores.setdefault(
                "rol",
                "Solo los desarrolladores pueden acceder al administrador técnico o ser superusuarios. "
                "Para asignar este rol, quite primero ese acceso desde el administrador técnico.",
            )
        if errores:
            raise ValidationError(errores)

    def save(self, *args, **kwargs):
        self.correo = normalizar_correo(self.correo)
        super().save(*args, **kwargs)
