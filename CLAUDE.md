# Contexto para Claude Code

Lee esto antes de tocar nada. Resume lo decidido en las conversaciones previas; el detalle está en `docs/`.

## Qué es

Panel para la tablet de la cocina de Pablo y Rim (Redmi Pad Pro, horizontal, ~1280×800 CSS px, Fully Kiosk Browser).
Web servida por un contenedor en ZimaOS (repositorio pablorodriguezm/panel-cocina-v2), desplegado con Portainer desde este repositorio (`docs/DESPLIEGUE.md`).

## Decisiones (no las cambies sin preguntar)

- **Web en Docker, no app Android.** Los repos de referencia (Planify-Dashboard de eusonlito y
  marco-familiar-dashboard de leontdi) son apps Kotlin para un marco de 1 GB; aquí no hace falta. Ver `docs/DECISIONES.md`.
- **Calendario y Recordatorios de Apple** siguen siendo donde se gestiona todo; el panel solo los enseña.
  - Calendario compartido «RIM Y PABLO»: iCloud → integración CalDAV de Home Assistant → este servicio.
  - Recordatorios (listas «Compra», «Casa»…): no están en CalDAV desde iOS 13, ningún servidor puede leerlos.
    Los envía un Atajo del iPhone a `POST /api/recordatorios` (`docs/RECORDATORIOS.md`). No propongas pyicloud.
- **Home Assistant** es el pegamento (calendario, Tesla, trayectos con Waze). La tablet nunca habla con HA.
- **Luz:** tarifa PVPC por horas. Precio de la API pública de REE; recomendaciones de mejores horas (coche 4 h,
  lavavajillas y lavadora 2 h) que solo aconsejan, no encienden nada.
- **Coche:** solo el Tesla.
- **Aire:** solo el Daikin «climate.daikinap69395_room_temperature» (a veces sin corriente); los de Salón y H. Diego no van.
- **Precio de la luz:** el PVPC de REE coincide con el sensor `sensor.esios_pvpc` de HA. El día del cambio de hora
  hay 25 horas (dos «02:00»). En la interfaz, el precio de ahora tiene que verse antes que la media.
- **Casa** (app/house.py): calefacción Netatmo (termostato de la caldera y válvulas), aire Daikin, temperaturas de
  las estancias y la música del Echo Dot de la cocina. Es lo único que da órdenes a Home Assistant: solo a las
  entidades de config.yaml, con consigna acotada, modos y presets permitidos, y reproducir/pausar/volumen.
- **Usuarios:** pantalla de bloqueo con avatar de Pablo y de Rim, **sin PIN**. Lo común igual para los dos;
  lo personal (de momento el trayecto al trabajo, cada uno a un destino distinto) según quién entra.
- **Menú semanal** (app/menu.py, `docs/MENU.md`): comida y cena saludables de un recetario fijo
  (`app/recetario.yaml`, para 2 personas), elegidas con un plan equilibrado por día. Solo se enseña en el panel
  (Hoy, Calendario y Tareas), no se escribe en el calendario de Apple. Sus ingredientes de la semana se pasan a la
  Compra tocándolos; el Atajo los recoge (`POST /api/recordatorios/recoger`) y los añade a Recordatorios.
- **Estructura como el marco original:** barra de navegación a la derecha (avatar, Hoy, Calendario, Tiempo,
  Casa, Energía, Consumo, Tareas, Actualizar, Dormir y la hora) con una vista por sección. Las capturas de referencia están en
  github.com/pablorodriguezm/panel-cocina/tree/main/docs/capturas. No volver a una sola pantalla.
- **Estilo:** paleta y tipografía de los repos de referencia (crema `#F7EEE2`, tarjetas `#FFFDF9`, Geist,
  cabecera con el cielo según la hora). Al usuario le gustan; mantenlos.

## Cómo se trabaja

- Español en código, comentarios, commits y documentación.
- Nunca se trabaja en `main`: rama + pull request. Al fusionar, GitHub Actions publica la imagen en ghcr.io,
  escribe su etiqueta en `deploy/portainer-compose.yml` (commit `[skip ci]`) y Portainer CE redespliega al verlo.
  No toques a mano la línea `image:` de ese fichero.
- Despliegue real: ZimaOS en 192.168.1.34 (Portainer :9000, panel :8090), Home Assistant en 192.168.1.202.
  La configuración vive en el servidor en /DATA/AppData/panel-cocina/config/config.yaml.
- Secretos solo en variables de Portainer o `.env` (ignorado): `HA_TOKEN`, `PANEL_TOKEN`. `config/config.yaml`
  tampoco se sube.
- Antes de un PR: `python -m pytest -q`. Para ver la interfaz sin Home Assistant:
  `PANEL_CONFIG=config/config.example.yaml PANEL_DATA=/tmp/panel PANEL_DEMO=1 uvicorn app.main:app --port 8090`
- Cambios visuales: comprueba a 1280×800 y enseña capturas. También se abre desde el iPhone: comprueba que nada
  se corte a 390×844 (vertical) y 844×390 (horizontal). Lo del móvil va en `@media` al final de `web/styles.css`;
  la tablet en horizontal no entra en ninguna de esas reglas.

## Wiki (Outline)

El resumen para casa está en wiki.pablorodriguezm.es → colección «Repositorio Docker» → «Panel de cocina», con una
página hija por tema (Despliegue y operación, Configuración, Consumo eléctrico, Integración con Recordatorios, Menú
semanal, Acceso desde el móvil y Registro de cambios). Tono de documentación técnica: ficha inicial, resumen,
tablas y resolución de problemas; sin secretos. Tras fusionar un cambio, actualiza «Registro de cambios» y la página
del tema con la API de Outline (`documents.search` para encontrarla, `documents.update`; clave en `OUTLINE_API_KEY`).

## Pendiente

- Tachar cosas de la compra desde la tablet (el Atajo las completaría en Recordatorios, como ya recoge lo que se
  pasa desde el menú): sin decidir.
- Foto en los avatares y fotos del Synology en la pantalla de bloqueo.
- Horario de pantalla y brillo con Fully Kiosk.
- Más cosas por persona.
