# TV: la tele por internet en el panel

La pestaña **TV** de la barra deja ver los canales principales sin salir del panel. Se inspira en
[cibernicola/tdt-local](https://github.com/cibernicola/tdt-local), pero va dentro del propio servicio: no hay que
instalar nada más.

| Canal | Cómo se ve | Nota |
|---|---|---|
| La 1, La 2, 24h, Teledeporte, Clan | Emisión abierta de RTVE (m3u8) con hls.js | Solo desde España |
| TVG | Emisión abierta de la CRTVG (m3u8) | |
| Antena 3, laSexta | Reproductor oficial de Atresplayer incrustado | Con sus anuncios y su aviso de cookies |
| La Séptima | Directo de su canal de YouTube incrustado | |
| Telecinco, Cuatro | Botón «Abrir en su web» | Mediaset no deja incrustar su reproductor |

Tocar un canal lo pone; la pantalla completa es la del propio reproductor. El panel recuerda el último canal y lo
vuelve a poner al entrar en la pestaña. Con la tele puesta **no se bloquea** a los 2 minutos.

**Al cambiar de pestaña la tele no se para:** se queda en pequeño en una esquina (abajo a la izquierda en la tablet,
encima de la barra en el iPhone), con **⤢** para volver a TV y **✕** para quitarla. Vale para todos los canales,
también Atresplayer y YouTube: el reproductor vive fuera de las pestañas y solo cambia de posición, así que no se
recarga. Se para al poner un podcast, al quitarla con ✕ o al volver a la pantalla de bloqueo.

## De dónde salen las emisiones

Las direcciones m3u8 cambian de vez en cuando. El panel las toma de la lista pública de
[TDTChannels](https://github.com/LaQuay/TDTChannels) (`TELEVISION.md`), que revisa cada 6 h, y prueba cada una en
orden; si ninguna responde, usa una dirección de reserva fija. Si la lista no se puede descargar, siguen valiendo las
de reserva y `/api/tv` lo dice en `error`.

## El intermediario `/api/tv/hls`

Casi ninguna cadena permite reproducir su emisión desde otra web (CORS), así que el panel la pide por la tableta y
la reenvía. Para que no sirva para pedir cualquier otra cosa:

- Solo pide direcciones que ha dado el propio panel: las de la lista de canales y las que enlazan esas listas m3u8
  (sublistas, segmentos y claves). Cada una va **firmada** (`?u=…&s=…`, HMAC-SHA256 con una clave aleatoria guardada
  en `/data/tv-clave.bin`); sin firma válida, 403.
- Como la clave está en `/data`, los enlaces siguen valiendo tras un redespliegue: la tele no se corta al
  actualizar el contenedor. Si aun así un canal falla con todas sus direcciones, la pestaña vuelve a pedir la lista
  de canales una vez y lo reintenta antes de dar el aviso.
- Nunca a direcciones de la red de casa ni de la propia máquina (se comprueba la IP de cada nombre).
- Las redirecciones se siguen a mano y se comprueba cada salto.

## Elegir los canales

Sin nada en `config.yaml` salen los de la tabla. Para cambiarlos, `tv.canales` sustituye la lista entera:

```yaml
tv:
  canales:
    - {id: la1, nombre: La 1, tipo: hls, tdt: La 1, reserva: "https://rtvelivestream.rtve.es/rtvesec/la1/la1_main_dvr.m3u8"}
    - {id: antena3, nombre: Antena 3, tipo: atres, slug: antena3}
    - {id: laseptima, nombre: La Séptima, tipo: youtube, canal_youtube: UCOCGPFW1UqPP9zdol7vEK1A}
    - {id: telecinco, nombre: Telecinco, tipo: web, web: "https://www.mediasetinfinity.es/directo/telecinco/"}
    - {id: mio, nombre: Otro, tipo: hls, urls: ["https://ejemplo.es/directo.m3u8"]}
```

`tdt` es el nombre exacto del canal en TDTChannels; `urls` fija las direcciones sin usar la lista.

## Podcasts

Con `OVERCAST_EMAIL` y `OVERCAST_CLAVE`, la lista tiene una pestaña más, **Podcasts**: tu cuenta de Overcast con el
progreso sincronizado. Ver [PODCASTS.md](PODCASTS.md).

## Mi lista (IPTV privada)

Si en el stack de Portainer están `IPTV_SERVIDOR` (`http://servidor:puerto`), `IPTV_USUARIO` e `IPTV_CLAVE` (copia
en Bitwarden → ZIMA_OS), la lista de canales tiene dos pestañas: **Abiertos** (los de arriba) y **Mi lista**. Sin
esas variables, todo sigue como antes.

- El panel usa la API de Xtream Codes (`player_api.php`) cada 6 h (cada 10 min si falla): grupos y canales **en
  directo**, sin películas ni series.
- «Mi lista» tiene buscador (sin tildes ni mayúsculas, todas las palabras) y un selector de grupo. Enseña los 150
  primeros que encajan; con más, hay que afinar la búsqueda. Recuerda la pestaña, el grupo y el último canal.
- Se ve en HLS (`/live/usuario/clave/<id>.m3u8`) a través del intermediario.
- **La clave no sale del servidor:** la tablet solo recibe el número de cada canal. Las direcciones que llevan la
  clave (la emisión y, en muchos servidores, cada segmento) van **cifradas** (`/api/tv/hls?k=…`, con la misma clave de
  `/data`; no se pueden leer ni retocar, y también sobreviven a un reinicio). Los
  errores se guardan sin usuario ni clave, y httpx ya no apunta las direcciones que pide en el registro del contenedor.
- Los logos solo salen si son https (una página https no puede enseñar imágenes http).
- Cuenta como una conexión de tu suscripción mientras se ve. Muchas solo permiten una a la vez.
- `/api/salud` → `tv_mi_lista` dice cuántos canales hay, el último error, el estado de la cuenta y cuándo caduca. Si
  falla o caduca en 10 días o menos, sale en **Avisos**.

## Si algo no se ve

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| «No se puede ver ahora mismo: la cadena no responde» | La emisión ha cambiado de dirección o está caída | Esperar a la siguiente revisión de TDTChannels (6 h) o poner `urls` en `config.yaml` |
| RTVE no carga | La emisión está restringida a España y el servidor sale por otro país (VPN) | Que el contenedor salga por la conexión de casa |
| Antena 3 o laSexta: «Actualmente sin emisión» al pulsar «Directo» | El navegador no deja guardar cookies al reproductor incrustado (Safari en el iPhone lo bloquea siempre) | En la tablet: Fully Kiosk → Ajustes → Web Content Settings → activar *Enable Third-Party Cookies*. En el iPhone no hay arreglo: el enlace «ábrelo en Atresplayer» de debajo del reproductor abre su web |
| Antena 3 o laSexta: «sin emisión» con el panel abierto por `http://192.168.1.34:8090` | Su directo va protegido (DRM) y el navegador solo lo reproduce dentro de una página https | Abrir el panel por `https://panel.pablorodriguezm.es` (proxy inverso del Synology, solo red de casa) |
| «Mi lista» no aparece | Falta alguna de las tres variables `IPTV_…` | Ponerlas en Portainer y actualizar el stack |
| «Mi lista: el servidor no acepta el usuario o la clave» | Datos mal copiados o cuenta caducada | Revisar las variables; `/api/salud` → `tv_mi_lista` |
| Un canal de «Mi lista» no arranca | El servidor no da HLS para ese canal, o ya hay otra conexión abierta con tu cuenta | Cerrar la otra app; si solo da `.ts`, avisar para añadir mpegts.js |
| Antena 3 o laSexta en negro | El bloqueador de anuncios de la red (Pi-hole) corta el reproductor | Permitir los dominios de Atresplayer en el Pi-hole |
| Telecinco o Cuatro | No se pueden incrustar | «Abrir en su web» las abre en el navegador de la tablet |
