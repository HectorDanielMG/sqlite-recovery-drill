# Seguridad

RestoreGuard está pensado para que una persona operadora ejecute copias y ensayos de restauración en entornos controlados.

## Manejo de copias

- Una copia contiene los datos completos de la base de origen. Protégela con permisos de sistema de archivos adecuados y almacénala en un volumen separado.
- La herramienta no cifra archivos ni manifiestos. Usa almacenamiento cifrado si los datos lo requieren.
- El SHA-256 del manifiesto ayuda a detectar corrupción o cambios accidentales; no está firmado y no autentica el origen del archivo.
- `restore` no reemplaza un destino existente sin `--overwrite`. Revisa la ruta antes de habilitar esa opción.
- La política de retención elimina copias antiguas administradas en la carpeta de salida. Mantén esa carpeta dedicada a artefactos de RestoreGuard.

## Reportar una vulnerabilidad

No publiques detalles explotables en un issue público. Usa la opción de reporte privado de vulnerabilidades del repositorio en GitHub cuando esté habilitada; si no está disponible, contacta al propietario del repositorio en privado antes de divulgar el problema.

## Alcance

RestoreGuard opera sobre archivos SQLite locales. No incluye cifrado, administración de secretos, transferencia remota, autenticación ni verificación criptográfica de la identidad del manifiesto.
