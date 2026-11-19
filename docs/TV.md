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
vuelve a poner al entrar en la pestaña. Con la tele puesta **no se bloquea** a los 2 minutos; al salir de la pestaña
la emisión se para.

## De dónde salen las emisiones

Las direcciones m3u8 cambian de vez en cuando. El panel las toma de la lista pública de
[TDTChannels](https://github.com/LaQuay/TDTChannels) (`TELEVISION.md`), que revisa cada 6 h, y prueba cada una en
orden; si ninguna responde, usa una dirección de reserva fija. Si la lista no se puede descargar, siguen valiendo las
de reserva y `/api/tv` lo dice en `error`.

## El intermediario `/api/tv/hls`

Casi ninguna cadena permite reproducir su emisión desde otra web (CORS), así que el panel la pide por la tableta y
la reenvía. Para que no sirva para pedir cualquier otra cosa:

- Solo pide a servidores que estén en la lista de canales o que esas listas m3u8 enlacen (sublistas, segmentos y
  claves), y caducan a las 6 h.
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

## Si algo no se ve

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| «No se puede ver ahora mismo: la cadena no responde» | La emisión ha cambiado de dirección o está caída | Esperar a la siguiente revisión de TDTChannels (6 h) o poner `urls` en `config.yaml` |
| RTVE no carga | La emisión está restringida a España y el servidor sale por otro país (VPN) | Que el contenedor salga por la conexión de casa |
| Antena 3 o laSexta: «Actualmente sin emisión» al pulsar «Directo» | El navegador no deja guardar cookies al reproductor incrustado (Safari en el iPhone lo bloquea siempre) | En la tablet: Fully Kiosk → Ajustes → Web Content Settings → activar *Enable Third-Party Cookies*. En el iPhone no hay arreglo: el enlace «ábrelo en Atresplayer» de debajo del reproductor abre su web |
| Antena 3 o laSexta en negro | El bloqueador de anuncios de la red (Pi-hole) corta el reproductor | Permitir los dominios de Atresplayer en el Pi-hole |
| Telecinco o Cuatro | No se pueden incrustar | «Abrir en su web» las abre en el navegador de la tablet |
