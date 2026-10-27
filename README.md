# ZeroPrice 🩵

Radar de precios rotos y stock que corre solo en GitHub, sin servidor.
Revisa tus fichas cada 15 minutos, publica la lista con precio y enlace,
y te avisa por Telegram **solo cuando algo está a 0 €**.

## Cómo funciona

1. `radar.py` lee `stores.yaml` y busca el precio en cada ficha.
2. Genera `docs/index.html` (turquesa, con precio, stock y enlace a la ficha).
3. Si hay un 0 €, envía un mensaje a Telegram con el enlace.
4. GitHub Actions guarda el resultado en el repo en cada revisión.

## Puesta en marcha (10 minutos)

### 1. Crea el repositorio
En GitHub: New repository → nombre `zeroprice` → sube todos estos archivos
(a la raíz, tal cual, con la carpeta `.github` incluida).

### 2. Activa el panel web
Settings → Pages → Build and deployment → Deploy from a branch →
Branch: `main`, carpeta `/docs` → Save.
Tu radar quedará en `https://TU_USUARIO.github.io/zeroprice/`.

### 3. Conecta Telegram (sin poner claves en el código)
1. En Telegram, habla con `@BotFather` → `/newbot` → guarda el token que te da.
2. Habla con `@userinfobot` → te devuelve tu ID numérico (ese es tu chat ID).
3. En GitHub: repo → Settings → Secrets and variables → Actions → New repository secret:
   - `TELEGRAM_BOT_TOKEN` = el token de BotFather
   - `TELEGRAM_CHAT_ID` = tu ID numérico
4. Escribe a tu bot cualquier mensaje (por ejemplo "hola") para que pueda escribirte.

### 4. Añade tus tiendas
Edita `stores.yaml` con una entrada por ficha: nombre, tienda y URL.
El radar detecta el precio solo en la mayoría de tiendas; si alguna no lo
detecta, añade su `price_selector` (el CSS del precio en esa tienda).

### 5. Comprueba que corre
Actions → ZeroPrice radar → Run workflow. En unos minutos verás el
resultado y el panel actualizado. A partir de ahí corre solo cada 15 min.

## Qué detecta

| Estado | Significado | Telegram |
|---|---|---|
| 🚨 PRECIO 0 € | Precio exactamente a 0 € | ✅ Sí |
| ⚠️ PRECIO ROTO | Caída ≥ 50 % frente a la última revisión | No, solo se marca en el panel |
| AGOTADO / SIN PRECIO / ERROR | Stock o fallo de lectura | No |

## Límites honestos

- No es tiempo real al segundo: GitHub Actions programa cada 15 min y
  puede retrasarse unos minutos. Para un chollo a 0 € suele bastar, pero
  un precio roto puede durar minutos.
- Algunas tiendas bloquean bots (Cloudflare y similares): esas fichas
  saldrán como ERROR o SIN PRECIO. No hay truco limpio para forzarlas.
- GitHub pausa los workflows programados si un repo no tiene actividad
  en 60 días: basta con entrar y lanzarlo a mano una vez para reactivarlo.
- Respeta las condiciones de cada tienda: esto es para tu uso personal,
  con una revisión cada 15 min por ficha, no un bombardeo.
