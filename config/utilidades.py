"""Utilidades de validación compartidas por los modelos del proyecto."""

from django.core.exceptions import ValidationError


def normalizar_espacios(texto):
    """Quita espacios al inicio y al final y deja un solo espacio entre palabras."""
    return " ".join((texto or "").split())


def validar_unico_sin_mayusculas(instancia, campo, mensaje):
    """Error junto al campo si otro registro tiene el mismo valor sin distinguir
    mayúsculas. Complementa un UniqueConstraint(Lower(campo)) en la base: al
    marcar el campo con error, Django no repite el mensaje como error general."""
    valor = getattr(instancia, campo)
    if not valor:
        return
    repetidos = type(instancia)._default_manager.filter(**{f"{campo}__iexact": valor})
    if instancia.pk:
        repetidos = repetidos.exclude(pk=instancia.pk)
    if repetidos.exists():
        raise ValidationError({campo: mensaje})


def agregar_errores(formulario, error):
    """Lleva al formulario un ValidationError lanzado por un servicio: cada mensaje
    junto a su campo si el formulario lo tiene, o como error general si no."""
    if hasattr(error, "error_dict"):
        for campo, mensajes in error.message_dict.items():
            formulario.add_error(campo if campo in formulario.fields else None, mensajes)
    else:
        formulario.add_error(None, error.messages)
