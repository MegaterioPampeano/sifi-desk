# Lo que necesita `core/service/app.py` para montar la biblioteca

`core/library/**` no toca `core/service/**` (otro frente está trabajando ahí). Para
exponer la API de la biblioteca, agregar en `core/service/app.py`:

```python
from library import api as library_api
```

y, después de crear la app (junto a los demás `include_router`):

```python
app.include_router(library_api.router)
```

No hace falta configurar nada más: el router ya trae `prefix="/library"`, y toma el
directorio de datos de `SIFI_LIBRARY_DIR` (default `~/.sifidesk/library`). En la edición
`stable` todos los endpoints contestan `403` con un detalle legible, así que montarlo
siempre es seguro.

Opcional, si el servicio quiere reutilizar el guard de edición en otros routers:

```python
from library.edition import require_dev  # levanta EditionError en stable
```

Prueba de humo (con `SIFI_EDITION=dev`):

```bash
curl -s localhost:8000/library/stats | python3 -m json.tool
curl -s 'localhost:8000/library/search?q=dsrna%20delivery&limit=3' | python3 -m json.tool
```
