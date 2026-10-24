# Home Assistant: lo que necesita el panel

El panel lee de Home Assistant con un token de larga duración. Todo lo que aparece aquí se configura en HA; el
panel solo necesita saber el nombre de cada entidad (`config/config.yaml`).

## Usuario y token

1. Ajustes → Personas → Usuarios → **Añadir usuario** `panel-cocina`, sin administrador.
2. Inicia sesión con él, ve a Perfil → Seguridad → **Tokens de acceso de larga duración** y crea uno.
3. Pégalo en `.env` como `HA_TOKEN=…`.

## Calendario de Apple («RIM Y PABLO»)

Integración **CalDAV** (Ajustes → Dispositivos y servicios → Añadir integración → CalDAV):

- URL: `https://caldav.icloud.com`
- Usuario: el Apple ID
- Contraseña: una **contraseña específica de app** (appleid.apple.com → Inicio de sesión y seguridad), nunca la del Apple ID.

Crea una entidad por calendario. Busca la del compartido (algo como `calendar.rim_y_pablo`) y ponla en
`calendario.entidad`.

## Lista de la compra y tareas

No pasan por Home Assistant: los Recordatorios de Apple no se pueden leer desde un servidor. Los envía un Atajo del
iPhone directamente al panel. Ver [RECORDATORIOS.md](RECORDATORIOS.md).

## Tesla

Cualquiera de las integraciones del coche sirve (Tesla Fleet, Teslemetry, Tessie…). Los nombres de las entidades
cambian según la integración y el nombre del coche: míralos en Ajustes → Dispositivos → el coche, y cópialos en
`coche.entidades`. Lo que no exista, déjalo vacío.

| Clave | Qué espera |
|---|---|
| `bateria` | % de batería |
| `autonomia` | km |
| `cargando` | `on`/`charging` mientras carga |
| `enchufado` | `on` si el cable está conectado |
| `potencia_carga` | kW (o W, se convierte) |
| `limite_carga` | % del límite de carga |
| `cuentakilometros` | km |
| `ruedas` | presión de cada rueda |

## Trayectos al trabajo

Integración **Waze Travel Time**, una por persona: origen casa, destino su trabajo. Cada una crea un sensor en minutos
(p. ej. `sensor.trayecto_pablo`), que va en `usuarios[].trayecto`. El panel enseña los minutos y la ruta.

## Precio de la luz y tiempo

No pasan por Home Assistant: el panel pide el PVPC a Red Eléctrica y el tiempo a Open-Meteo, las dos sin clave.
