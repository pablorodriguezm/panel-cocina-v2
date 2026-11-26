# Podcasts: tu Overcast en el panel

La pestaña **TV → Podcasts** reproduce los podcasts de tu cuenta de Overcast en la tablet. Ves tus podcasts y los
capítulos «para seguir», empiezas donde lo dejaste en el iPhone, y lo que escuchas en la cocina se guarda en
Overcast: luego sigues en el iPhone por el mismo sitio.

## Cómo funciona

Overcast no tiene API pública y no deja mostrar su web dentro de otra página: responde `X-Frame-Options: DENY` y
`frame-ancestors 'none'`. Por eso el servidor del panel hace lo mismo que su web, con tu cuenta:

| Paso | Qué hace el servidor |
|---|---|
| Sesión | Inicia sesión como el formulario de overcast.fm y guarda la cookie de sesión en `/data/overcast.json`, no la contraseña. Si caduca, vuelve a entrar solo. |
| Catálogo | Lee `overcast.fm/podcasts`: los capítulos «para seguir» y tus podcasts, cada 3 min como mucho. Los capítulos de un podcast, de su página, cada 10 min. |
| Reproducir | Al tocar un capítulo, lee su página: la dirección del audio, por dónde ibas, tu velocidad y su versión de sincronización. La tablet reproduce el audio directamente. |
| Progreso | Cada 15 s sonando, al pausar y al cerrar la página, manda por dónde vas con la misma llamada que su reproductor web (`POST /podcasts/set_progress/<id>`: segundos, velocidad y versión). Al acabar el capítulo lo marca como escuchado. |

- **Secretos:** la tablet nunca recibe la contraseña ni la cookie. Solo puede pedir capítulos (`/+código`) y páginas
  de podcasts (`/itunes…` o `/p…`), nada más de tu cuenta.
- **Es una vía no oficial:** si Overcast cambia su web, deja de funcionar hasta adaptarla. Entonces sale en
  **Avisos** («Podcasts: …») y en `/api/salud` → `podcasts`.

## En la pantalla

- **Lista:** «📌 Fijados», «Para seguir» y «Mis podcasts». Al tocar un podcast salen sus capítulos (● los nuevos) y
  «‹ Mis podcasts» para volver.
- **Fijar arriba:** el botón 📌 de cada podcast (o «📌 Fijar arriba» en sus capítulos) lo pone en «Fijados», arriba
  del todo, en el orden en que se fijan; tocándolo otra vez se quita. Se guarda en el servidor
  (`/data/podcasts-fijados.json`), así que se ve igual en la tablet y en el móvil.
- **Reproductor:** carátula, barra para moverse, −15 s, reproducir o pausar, +30 s y la velocidad (empieza en la que
  tengas en Overcast).
- **Sigue sonando al cambiar de vista.** Abajo, junto al botón ⏲️, sale una pastilla 🎧 con el capítulo para pausar o
  seguir desde cualquier sitio.
- Mientras suena, la pantalla no se bloquea. Al poner un canal de TV, el podcast se pausa.

## Puesta en marcha

En Portainer → stack panel-cocina → Environment variables, añadir `OVERCAST_EMAIL` y `OVERCAST_CLAVE`, y pulsar
*Update the stack*. Copia en Bitwarden → ZIMA_OS. Sin esas variables, la pestaña Podcasts no sale.

## Si algo no va

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| «Podcasts: Overcast no acepta el correo o la contraseña» | Datos mal copiados, o la cuenta entra con otro método (Apple, código) | Revisar las variables. La cuenta tiene que tener contraseña en overcast.fm/account |
| «…la página de tus podcasts ha cambiado» | Overcast ha cambiado su web | Avisar para adaptar `app/podcasts.py` |
| «No se puede reproducir el audio de este capítulo» | El audio del podcast no responde o es solo para suscriptores | Probarlo en la app |
| En el iPhone no sigue por donde ibas | El progreso se guarda cada 15 s y al pausar | Pausar antes de dejarlo; la app de Overcast sincroniza al abrirse |
