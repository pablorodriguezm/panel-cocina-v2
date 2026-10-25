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

## Consumo de la casa

Pon los **mismos sensores que el panel de Energía** de HA (Ajustes → Paneles → Energía → «Consumo de la red
eléctrica»): así el panel da los mismos kWh. Si son varios, van en lista y se suman.

En casa son dos, porque el cargador no pasa por el Shelly del cuadro:

| | Potencia (W) → `potencia_total` | Energía (kWh) → `energia_total` |
|---|---|---|
| Shelly (la casa sin el cargador) | su sensor de potencia | su sensor de energía |
| V2C Trydan (el coche) | `charge_power` | `charge_energy` |

El `charge_energy` del Trydan vuelve a cero en cada carga; el panel no lo cuenta como consumo negativo. Ojo con el
`house_power` del Trydan: no incluye la carga del coche, así que solo no da el total.

Si no hay `energia_total`, «Hoy, hora a hora» se calcula integrando el historial de la potencia (el recorder de HA
tiene que guardar esos sensores, como hace por defecto). La potencia de carga también puede ir en `aparatos`.

## Precio de la luz y tiempo

No pasan por Home Assistant: el panel pide el PVPC a Red Eléctrica y el tiempo a Open-Meteo, las dos sin clave.
