# SQLite Recovery Drill

**Copias SQLite verificables y ensayos de restauración desde la terminal.** RestoreGuard crea snapshots consistentes usando la API de backup de SQLite, comprime cada copia, registra un manifiesto SHA-256, verifica `PRAGMA integrity_check` y restaura a una ruta aislada. Cada operación emite JSON para que pueda integrarse con scripts y pipelines.

Proyecto de portafolio enfocado en continuidad operativa y recuperación de datos. Se alinea con experiencia en administración de infraestructura de alta disponibilidad y diagnóstico de incidencias. Funciona con Python 3.10 o superior y usa solo la biblioteca estándar.

## Funciones

- Snapshot coherente de bases SQLite, incluso si la base utiliza WAL.
- Compresión gzip y manifiesto con SHA-256, tamaño, fecha ISO 8601 con zona horaria y duración de la copia.
- Verificación de checksum y de integridad SQLite antes de aceptar un artefacto.
- Ensayo de restauración en otra ruta, con validación y reemplazo atómico del destino.
- Protección contra sobrescritura accidental; `--overwrite` la hace explícita.
- Retención configurable de copias generadas por la herramienta.
- Salida JSON y códigos de salida adecuados para automatización.
- Pruebas automatizadas con `unittest` y sin dependencias de ejecución externas.

## Inicio rápido

### Instalar en modo editable

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install -e .
```

### Crear una base de demostración

```bash
python examples/create_demo_db.py --output /tmp/restoreguard-demo/orders.sqlite3
```

El ejemplo usa datos sintéticos y se niega a sobrescribir el archivo si ya existe.

### Crear y verificar una copia

```bash
restoreguard backup /tmp/restoreguard-demo/orders.sqlite3 \
  --output /tmp/restoreguard-demo/backups \
  --keep-last 3
restoreguard list --directory /tmp/restoreguard-demo/backups
restoreguard verify /tmp/restoreguard-demo/backups/ARCHIVO.sqlite3.gz
```

Sustituye `ARCHIVO.sqlite3.gz` por la ruta que devuelve `backup` o `list`. También puedes usar `python -m restoreguard` en lugar del comando instalado.

### Ensayar la restauración

```bash
restoreguard restore /tmp/restoreguard-demo/backups/ARCHIVO.sqlite3.gz \
  /tmp/restoreguard-demo/restored/orders.sqlite3
```

El destino debe ser nuevo. Para reemplazar un archivo existente, agrega `--overwrite`. La restauración verifica primero el manifiesto, el hash y la integridad; escribe en un archivo temporal y solo publica el destino después de validar la base.

## Comandos

| Comando | Acción |
| --- | --- |
| `restoreguard backup DB --output DIR --keep-last N` | Crea una copia consistente y aplica retención |
| `restoreguard verify BACKUP` | Comprueba SHA-256, tamaño e integridad SQLite |
| `restoreguard restore BACKUP DESTINO [--overwrite]` | Verifica y restaura en una ruta aislada |
| `restoreguard list --directory DIR` | Lista artefactos con manifiesto válido |

Cada comando correcto imprime un objeto JSON en stdout. Los errores se escriben en stderr y devuelven un código distinto de cero. La duración de la copia y de cada restauración se mide en la ejecución correspondiente; el proyecto no publica cifras de rendimiento precalculadas.

## Pruebas

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

La suite cubre snapshots consistentes, verificación de integridad, detección de cambios en el archivo, protección y reemplazo explícito del destino y retención.

Atajos equivalentes:

```bash
make install
make test
```

## Formato de los artefactos

Cada copia produce dos archivos asociados:

- `*.sqlite3.gz`: snapshot comprimido.
- `*.sqlite3.gz.manifest.json`: versión del manifiesto, nombre del artefacto, fecha UTC, SHA-256, tamaños, duración de creación e integridad.

El SHA-256 detecta corrupción o cambios accidentales; el manifiesto no está firmado y por sí solo no prueba quién creó la copia. Guarda los artefactos en otro volumen o ubicación remota para protegerlos ante la pérdida del disco de origen. La herramienta no estima RPO porque una base SQLite genérica no garantiza un timestamp de negocio con el que medir la antigüedad de los datos.

## Estructura

```text
src/restoreguard/       motor y CLI
tests/                  pruebas automatizadas
examples/               base sintética de demostración
```

## Licencia

MIT. Consulta [LICENSE](LICENSE).

Consulta [SECURITY.md](SECURITY.md) para las recomendaciones de manejo y reporte de vulnerabilidades.
