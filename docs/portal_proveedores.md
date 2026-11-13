# Portal de proveedores · A14

## Uso

1. En el ingreso, seleccione «registrarse en el portal», o abra `/portal/registro/`.
2. Diligencie NIT, razón social, tipo de persona, contacto, dirección, correo y
   contraseña. El correo será su nombre de ingreso.
3. Ingrese al sistema. `/portal/` muestra únicamente su ficha, sus envíos y los
   documentos incorporados a su ficha. Las correcciones de datos se solicitan a la clínica.
4. Seleccione «Enviar un documento PDF», elija tipo y fechas y adjunte el archivo.
   Cada envío queda pendiente de revisión; una corrección se presenta como otro envío.
5. Descargue sus PDF desde los enlaces del portal. No hay rutas públicas a los archivos.

El resultado del registro es el mismo para un alta válida y para un NIT o correo
ya registrado, sin mostrar fichas ni correos existentes. No se inicia una sesión
automáticamente. Si sus datos ya están registrados, debe contactar a la clínica.

## Activación y alcance

- `portal.activar_cuenta_al_registrar` (D-03), editable en Configuración → Parámetros:
  Sí por defecto. No deja la cuenta inactiva hasta que administración la active
  desde Configuración → Usuarios. Activar la cuenta no aprueba al proveedor:
  la ficha siempre nace en estado «Registrado».
- Los proveedores acceden únicamente a su ficha y a sus documentos, incluso al
  modificar los identificadores de las URL. Un archivo ajeno devuelve 404; los
  roles internos reciben 403 en las vistas privadas del portal.
- Una ficha inactiva conserva la consulta de su historial, pero no admite nuevos
  envíos. La inactivación de la ficha no desactiva automáticamente sus usuarios.
- Los PDF admiten extensión `.pdf`, cabecera `%PDF-` y hasta 10 MB. Se almacenan
  en `archivos_privados/envios/AAAA/MM/<uuid>.pdf`. La descarga es un adjunto privado
  con `nosniff` y `no-store`.
- `EnvioProveedor` vive en la app proveedores; portal no tiene modelos propios.
  El envío no crea un `DocumentoProveedor` hasta su aceptación en A15.
- Las cargas de PDF deben ejecutarse fuera de transacciones externas. Ante un fallo
  del servicio se revierte el registro y se elimina el PDF nuevo.
- El borrado de archivos se realiza al confirmar la transacción y solo cuando no
  hay otra referencia desde un documento o envío. Esto prepara la reutilización
  del mismo PDF al aceptar un envío en la bandeja administrativa.

## Protección del registro y publicación

El formulario público tiene CSRF, validación de contraseñas, campo trampa y un límite
por IP compartido entre sesiones: 5 intentos por 900 segundos de forma predeterminada.
`PORTAL_REGISTRO_INTENTOS` y `PORTAL_REGISTRO_VENTANA` permiten ajustar estos límites
desde el entorno; deben ser enteros positivos. El contador incluye cargas inválidas
y no almacena la IP en texto claro. Al excederlo devuelve 429 con `Retry-After`.
Sin proxy configurado se usa `REMOTE_ADDR`; no se confía en un `X-Forwarded-For` arbitrario.

Antes de publicar el portal en internet se requiere completar el captcha, la
verificación del correo y HTTPS indicados en A14. También debe configurarse una
caché compartida entre todos los procesos para que el límite por IP sea global.
La caché local de desarrollo comparte sesiones del mismo proceso, pero no varios
procesos. Con un proxy de confianza, configure los encabezados según README;
la extracción de IP actual supone un único proxy.

## Revisión administrativa

**A15 ya está implementado**. La clínica revisa los envíos en la bandeja
administrativa y decide aceptarlos o descartarlos con motivo. El resultado aparece
en su historial; al aceptar se incorpora el documento a su ficha. Si el PDF de un
descarte no se conserva según la política vigente, el historial sigue disponible.
La [guía de la bandeja](bandeja_envios.md) describe las acciones administrativas.
