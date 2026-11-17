"""Recorrido didáctico exclusivo de la base local de demostración.

Las mutaciones pasan por los servicios de negocio. Los PDF se cargan fuera de
una transacción externa porque cada servicio protege su propia transacción.
No se envían correos ni se produce una autorización para operaciones reales.
"""
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.models import Max
from django.urls import reverse
from django.utils import timezone

MOTIVO = "DEMOSTRACIÓN aislada del recorrido de compras desde el consolidado FR-GDS-11"


def _exigir_demostracion(carpeta_salida):
    if getattr(settings, "MODO_DEMOSTRACION", False) is not True:
        raise ValidationError("Este recorrido solo se permite con settings_demo.")
    directorio = Path(settings.DIRECTORIO_DEMOSTRACION).resolve()
    base = Path(settings.DATABASES["default"]["NAME"]).resolve()
    salida = Path(carpeta_salida).resolve()
    privados = Path(settings.MEDIA_ROOT).resolve()
    if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.sqlite3":
        raise ValidationError("La demostración requiere su base SQLite independiente.")
    if not all(ruta.is_relative_to(directorio) for ruta in (base, salida, privados)):
        raise ValidationError("Base, PDF y salida deben permanecer dentro de la demostración.")
    if base == (Path(settings.BASE_DIR) / "db.sqlite3").resolve():
        raise ValidationError("No se permite cargar ejemplos en la base habitual.")
    if connection.in_atomic_block:
        raise ValidationError("Ejecute el recorrido fuera de una transacción externa para proteger los PDF.")
    salida.mkdir(parents=True, exist_ok=True)
    return salida


def _pdf(nombre, explicacion):
    from reportlab.pdfgen import canvas

    contenido = BytesIO()
    documento = canvas.Canvas(contenido)
    documento.setTitle(nombre)
    documento.setFont("Helvetica-Bold", 13)
    documento.drawString(40, 800, "DOCUMENTO DE DEMOSTRACION SIN VALIDEZ COMERCIAL")
    documento.setFont("Helvetica", 11)
    documento.drawString(40, 770, explicacion)
    documento.drawString(40, 745, "Proveedor, oferta, firma y movimiento ficticios para recorrer el sistema.")
    documento.save()
    return SimpleUploadedFile(nombre, contenido.getvalue(), content_type="application/pdf")


def _parametro(clave, valor, actor):
    from parametros.models import Parametro
    from parametros.servicios import cambiar_valor

    parametro = Parametro.objects.get(clave=clave)
    if parametro.valor != valor:
        cambiar_valor(parametro, valor, actor=actor, motivo=MOTIVO)


def _proveedores_y_fr14(admin, hoy):
    from bitacora.servicios import registrar
    from cuentas.models import Rol, Usuario
    from proveedores import matrices_servicios, servicios
    from proveedores.evaluacion_servicios import finalizar_evaluacion
    from proveedores.models import CategoriaProveedor, Peso, Proveedor, Requisito, TipoDocumento, VersionMatriz
    from proveedores.respuestas_servicios import guardar_respuesta

    categoria = servicios.guardar_catalogo(
        CategoriaProveedor(nombre="Tecnología DEMOSTRACIÓN", descripcion="Categoría ficticia del recorrido didáctico"),
        actor=admin, motivo=MOTIVO,
    )
    version = VersionMatriz.objects.create(
        numero=(VersionMatriz.objects.aggregate(n=Max("numero"))["n"] or 0) + 1,
        notas="Matriz ficticia de demostración; no sustituye los requisitos oficiales de la clínica.",
    )
    requisitos = []
    for numero, texto in enumerate((
        "DEMOSTRACIÓN Confirmación ficticia de capacidad de suministro",
        "DEMOSTRACIÓN Confirmación ficticia de respaldo documental",
    ), 1):
        requisito = Requisito(version=version, numero=numero, grupo="calidad", texto=texto)
        requisito = servicios.guardar_catalogo(requisito, actor=admin, motivo=MOTIVO)
        servicios.guardar_catalogo(Peso(requisito=requisito, categoria=categoria, valor=1), actor=admin, motivo=MOTIVO)
        requisitos.append(requisito)
    registrar("demo.matriz_preparada", actor=admin, objeto=version,
              nuevo={"requisitos": [r.pk for r in requisitos]}, motivo=MOTIVO)
    matrices_servicios.publicar_version(version, desde=hoy, actor=admin, motivo=MOTIVO)
    tipo = servicios.guardar_catalogo(TipoDocumento(nombre="Soporte ficticio DEMOSTRACIÓN", requiere_vencimiento=True),
                                     actor=admin, motivo=MOTIVO)
    resultados = []
    for orden, nombre in enumerate(("Tecnología Alfa DEMOSTRACIÓN", "Tecnología Beta DEMOSTRACIÓN"), 1):
        proveedor = servicios.guardar_proveedor(Proveedor(
            nit=str(800900000 + orden), razon_social=nombre, tipo_persona="juridica",
            contacto_nombre="Contacto ficticio", contacto_correo=f"proveedor{orden}@ejemplo.test",
            contacto_telefono="6015550100", direccion="Dirección ficticia de demostración",
            categoria=categoria,
        ), actor=admin, motivo=MOTIVO)
        usuario = Usuario.objects.create_user(
            correo=f"proveedor{orden}@demostracion.local", password=None,
            nombre=f"Proveedor {orden} DEMOSTRACIÓN", rol=Rol.PROVEEDOR,
            proveedor=proveedor, debe_cambiar_clave=False,
        )
        envio = servicios.crear_envio(
            proveedor=proveedor, actor=usuario, tipo=tipo, fecha_expedicion=hoy,
            fecha_vencimiento=hoy + timedelta(days=365),
            archivo=_pdf(f"soporte-proveedor-{orden}.pdf", nombre), motivo=MOTIVO,
        )
        aceptado = servicios.revisar_envio(envio, aceptar=True, actor=admin, motivo=MOTIVO)
        evaluacion = matrices_servicios.crear_evaluacion(proveedor, categoria, hoy, actor=admin, motivo=MOTIVO)
        for requisito in requisitos:
            guardar_respuesta(evaluacion, requisito, respuesta="si", observacion=MOTIVO,
                              confirma_na=False, documento=aceptado.documento, actor=admin, motivo=MOTIVO)
        evaluacion = finalizar_evaluacion(evaluacion, actor=admin, motivo=MOTIVO)
        proveedor = servicios.cambiar_estado(proveedor, "aprobado", actor=admin, motivo=MOTIVO)
        resultados.append({"proveedor": proveedor, "usuario": usuario, "evaluacion": evaluacion})
    # Un envío queda pendiente para que administración pueda probar la bandeja.
    pendiente = servicios.crear_envio(
        proveedor=resultados[1]["proveedor"], actor=resultados[1]["usuario"], tipo=tipo,
        fecha_expedicion=hoy, fecha_vencimiento=hoy + timedelta(days=365),
        archivo=_pdf("revision-pendiente-demo.pdf", "Documento ficticio pendiente de revisión administrativa"), motivo=MOTIVO,
    )
    return resultados, pendiente


def crear_recorrido(*, usuarios, linea, carpeta_salida):
    """Crea un único recorrido completo en una base demo ya migrada.

    El padre prepara una línea aprobada con al menos cuatro unidades autorizadas.
    Las cuentas de proveedores se crean sin clave utilizable; el comando padre
    puede asignar después la misma clave temporal que usa el resto de la demo.
    """
    salida = _exigir_demostracion(carpeta_salida)
    from compras import (
        aprobacion_orden_servicios, calificacion_servicios, cierre_servicios,
        contrato_servicios, cotizacion_servicios, criterios_servicios,
        decision_cotizacion_servicios, decision_servicios, oferta_servicios,
        orden_servicios, recepcion_servicios, servicios,
    )
    from compras.models import Necesidad, TarifaImpuesto, TipoCotizacion, TipoPoliza, VersionCriterios
    from compras.orden_pdf import generar
    from parametros.catalogo import CLIENTE_ORDEN, NIT_CLIENTE_ORDEN
    from seguimientos.models import ResultadoCierre, Seguimiento, TipoEvento
    from seguimientos import servicios as seguimientos

    admin, aprobador = usuarios["admin"], usuarios["aprobador"]
    if admin.pk == aprobador.pk or admin.rol != "administrador" or aprobador.rol != "administrador":
        raise ValidationError("El ejemplo exige dos administradores distintos.")
    if linea.proyeccion.estado != "aprobada" or linea.cantidad_autorizada is None or linea.cantidad_autorizada < 4:
        raise ValidationError("Seleccione una línea de proyección aprobada con cuatro unidades autorizadas.")
    if Necesidad.objects.filter(objeto__startswith="DEMOSTRACIÓN Compra de cuatro equipos").exists():
        raise ValidationError("Este recorrido ya existe en la demostración; no se duplicó.")
    hoy = timezone.localdate()
    proveedores, pendiente = _proveedores_y_fr14(admin, hoy)
    _parametro(CLIENTE_ORDEN, "CLÍNICA DE DEMOSTRACIÓN SIN VALIDEZ COMERCIAL", admin)
    _parametro(NIT_CLIENTE_ORDEN, "DEMO-NO-VALIDO", admin)

    necesidad = servicios.crear_necesidad(
        objeto="DEMOSTRACIÓN Compra de cuatro equipos de cómputo AIO",
        area=linea.proyeccion.area, fecha=hoy, lineas=[(linea.pk, Decimal(4))],
        cantidad_base=Decimal(4), unidad_base=str(linea.unidad), actor=admin, motivo=MOTIVO,
    )
    version = VersionCriterios.objects.get(numero=1)
    criterios_servicios.publicar_version(version, desde=hoy, actor=admin, motivo=MOTIVO)
    lista = servicios.crear_lista(necesidad, fecha=hoy, actor=admin, motivo=MOTIVO)
    participantes = [servicios.agregar_participante(lista, p["proveedor"], actor=admin, motivo=MOTIVO) for p in proveedores]
    celdas = [
        {"participante": participante.pk, "criterio": criterio.pk,
         "cumplimiento": Decimal(5 if indice == 0 else 3), "observacion": MOTIVO}
        for indice, participante in enumerate(participantes)
        for criterio in version.criterios.all()
    ]
    calificacion_servicios.guardar_matriz(lista, celdas, actor=admin, motivo=MOTIVO)
    decision_servicios.guardar_decision(
        lista, [{"participante": p.pk, "cantidad_autorizada": "2", "observacion": MOTIVO,
                 "justificacion_eleccion": "Comparación didáctica de dos proveedores elegibles; precios y datos ficticios."}
                for p in participantes], actor=admin, motivo=MOTIVO,
    )
    lista = cierre_servicios.cerrar_lista(lista, actor=admin, motivo=MOTIVO, justificacion_documental=MOTIVO)
    origen = necesidad.origenes.get(linea=linea)
    cotizacion = cotizacion_servicios.crear_cotizacion(
        necesidad=necesidad, fecha=hoy, tipo=TipoCotizacion.objects.get(nombre="Compra"),
        objeto="DEMOSTRACIÓN Comparación de cuatro equipos AIO", lista_elegibles=lista,
        cierre_esperado_id=lista.cierres.first().pk,
        lineas=[{"descripcion": linea.producto_servicio, "unidad": linea.unidad,
                 "cantidad": Decimal(4), "especificacion": "Especificación ficticia para el recorrido; verificar en una compra real.",
                 "origen": origen}], actor=admin, motivo=MOTIVO,
    )
    tarifa = TarifaImpuesto.objects.get(nombre="Exento/No gravado")
    ofertas = []
    for indice, proveedor in enumerate(proveedores):
        oferta = oferta_servicios.guardar_oferta(
            cotizacion, cotizacion.invitados.get(proveedor=proveedor["proveedor"]),
            contacto_nombre="Contacto ficticio de demostración", contacto_correo=f"oferta{indice+1}@ejemplo.test",
            contacto_telefono="6015550100", fecha=hoy,
            precios=[{"linea": cotizacion.lineas.get().pk,
                      "precio_unitario": Decimal("2400000") if indice == 0 else Decimal("2500000"),
                      "tarifa": tarifa}],
            archivo=_pdf(f"oferta-{indice+1}-demo.pdf", "Oferta ficticia para cuatro equipos AIO; tarifa cero solo para demostración"),
            actor=admin, motivo=MOTIVO,
        )
        ofertas.append(oferta)
    cotizacion = contrato_servicios.guardar_requiere(cotizacion, requiere_contrato=True, actor=admin, motivo=MOTIVO)
    decision = decision_cotizacion_servicios.proponer_decision(
        cotizacion, modalidad="completa", oferta_id=ofertas[0].pk,
        recomendacion="DEMOSTRACIÓN Se elige la oferta ficticia de menor total entre los dos oferentes.",
        justificacion_verificaciones=MOTIVO, actor=admin, motivo=MOTIVO,
    )
    contrato = contrato_servicios.guardar_contrato(
        decision, numero="CT-DEMO-001", supervisor=usuarios["coordinador"], cargo="Supervisor de demostración",
        fecha_inicio=hoy, fecha_fin=hoy + timedelta(days=30),
        forma_pago="DEMOSTRACIÓN Pago a treinta días, sin compromiso real", valor=ofertas[0].total,
        archivo=_pdf("contrato-demo.pdf", "Contrato ficticio sin obligación ni validez comercial"),
        actor=admin, motivo=MOTIVO,
    )
    poliza = contrato_servicios.guardar_poliza(
        contrato, tipo=TipoPoliza.objects.get(nombre="Cumplimiento"), aseguradora="Aseguradora ficticia DEMOSTRACIÓN",
        numero="P-DEMO-001", valor_asegurado=ofertas[0].total, vigencia_desde=hoy,
        vigencia_hasta=hoy + timedelta(days=365),
        archivo=_pdf("poliza-demo.pdf", "Póliza ficticia que no constituye cobertura ni garantía real"),
        actor=admin, motivo=MOTIVO,
    )
    decision = decision_cotizacion_servicios.aprobar_decision(decision, actor=aprobador, motivo=MOTIVO)
    orden, = orden_servicios.crear_orden_desde_decision(
        decision, fecha_elaboracion=hoy, fecha_esperada_entrega=hoy + timedelta(days=7), actor=admin, motivo=MOTIVO,
    )
    orden = aprobacion_orden_servicios.solicitar(orden, actor=admin, motivo=MOTIVO, revision_esperada=orden.revision)
    orden = aprobacion_orden_servicios.votar(orden, decision="aprueba", actor=aprobador, motivo=MOTIVO)
    ruta_pdf = salida / "orden-demostracion.pdf"
    ruta_pdf.write_bytes(generar(orden.documento_emision))
    envio_orden = aprobacion_orden_servicios.registrar_envio(
        orden, fecha_envio=timezone.now(), actor=admin,
        motivo="DEMOSTRACIÓN Evidencia de envío registrada; no se envió ningún correo.",
        archivo=_pdf("evidencia-envio-demo.pdf", "Evidencia ficticia de comunicación sin envío real"),
    )
    seguimiento = Seguimiento.objects.filter(orden=orden).first()
    if seguimiento is None:
        seguimiento = seguimientos.crear(orden=orden, actor=admin, motivo=MOTIVO)
    seguimientos.agregar_evento(
        seguimiento, tipo=TipoEvento.objects.get(codigo="comunicacion"), fecha=timezone.now(),
        nota="DEMOSTRACIÓN Confirmación ficticia de disponibilidad y entrega.", actor=admin, motivo=MOTIVO,
    )
    linea_orden = orden.lineas.get()
    recepciones = []
    for tipo, recibida, devuelta, nota in (
        ("recepcion", "2", "0", "DEMOSTRACIÓN Primera entrega parcial de dos equipos"),
        ("devolucion", "0", "1", "DEMOSTRACIÓN Devolución de un equipo de la entrega parcial"),
        ("recepcion", "3", "0", "DEMOSTRACIÓN Reposición y entrega final; cuatro equipos netos recibidos"),
    ):
        orden.refresh_from_db()
        recepciones.append(recepcion_servicios.registrar_recepcion(
            orden, fecha=hoy, tipo=tipo,
            lineas=[{"id": linea_orden.pk, "cantidad": recibida, "devuelta": devuelta, "rechazada": "0", "observacion": nota}],
            actor=admin, motivo=nota, revision_esperada=orden.revision,
            archivo=_pdf(f"recepcion-{len(recepciones)+1}-demo.pdf", nota),
        ))
    seguimiento.refresh_from_db()
    seguimiento = seguimientos.cerrar(
        seguimiento, resultado=ResultadoCierre.objects.get(codigo="cumplido"), fecha=hoy,
        actor=admin, motivo="DEMOSTRACIÓN Cierre con cuatro equipos netos recibidos y sin saldo pendiente",
        revision_esperada=seguimiento.revision,
    )
    orden.refresh_from_db()
    pasos = [
        {"titulo": "Proveedor y documentos", "url": reverse("proveedores:detalle", args=[proveedores[0]["proveedor"].pk])},
        {"titulo": "Evaluación FR-GDS-14", "url": reverse("proveedores:evaluacion_detalle", args=[proveedores[0]["evaluacion"].pk])},
        {"titulo": "Necesidad desde la proyección", "url": reverse("compras:necesidad_detalle", args=[necesidad.pk])},
        {"titulo": "Lista de elegibles cerrada", "url": reverse("compras:lista_detalle", args=[lista.pk])},
        {"titulo": "Cotización y ofertas", "url": reverse("compras:cotizacion_detalle", args=[cotizacion.pk])},
        {"titulo": "Comparación y adjudicación", "url": reverse("compras:cotizacion_comparar", args=[cotizacion.pk])},
        {"titulo": "Contrato y póliza", "url": reverse("compras:contrato", args=[cotizacion.pk, decision.pk])},
        {"titulo": "Orden aprobada y PDF", "url": reverse("compras:orden_detalle", args=[orden.pk])},
        {"titulo": "Recepciones y devolución", "url": reverse("compras:recepcion_detalle", args=[orden.pk, recepciones[-1].pk])},
        {"titulo": "Seguimiento y cierre", "url": reverse("seguimientos:detalle", args=[seguimiento.pk])},
    ]
    return {
        "necesidad_id": necesidad.pk, "lista_id": lista.pk, "cotizacion_id": cotizacion.pk,
        "decision_id": decision.pk, "contrato_id": contrato.pk, "poliza_id": poliza.pk,
        "orden_id": orden.pk, "orden_estado": orden.estado, "orden_consecutivo": orden.consecutivo,
        "total_orden": str(orden.total), "seguimiento_id": seguimiento.pk,
        "seguimiento_cerrado": seguimiento.cerrado, "recepciones_ids": [r.pk for r in recepciones],
        "envio_orden_id": envio_orden.pk, "envio_pendiente_id": pendiente.pk,
        "proveedores": [{"id": p["proveedor"].pk, "nombre": p["proveedor"].razon_social,
                         "usuario_id": p["usuario"].pk, "correo": p["usuario"].correo,
                         "evaluacion_id": p["evaluacion"].pk} for p in proveedores],
        "pdf_orden": str(ruta_pdf.relative_to(Path(settings.DIRECTORIO_DEMOSTRACION).resolve())),
        "cantidades": {"proyectadas": linea.total_anual, "compra": 4, "recibidas_netas": 4, "devueltas": 1},
        "pasos": pasos,
    }
