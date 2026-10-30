# E2E de la UI

```bash
python3 -m pytest tests/ -q                      # backend
SIFID_URL=http://127.0.0.1:8790 \
SIFID_TOKEN=$(grep -h token ~/.sifidesk/token* 2>/dev/null | head -1) \
node tests/e2e/chat_full.mjs                     # UI
```

Necesita `playwright` con Chromium. Si `node` no lo encuentra desde este directorio:

```bash
NODE_PATH=$(npm root -g) node tests/e2e/chat_full.mjs
# o, en la workspace del asistente, donde está instalado:
cd ~/.openclaw/workspace && node /mnt/datos/proyectos/sifi-desk/tests/e2e/chat_full.mjs
```
