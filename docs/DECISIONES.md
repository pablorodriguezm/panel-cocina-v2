# Decisiones

## Por qué web en Docker y no la app Android del repositorio original

Los dos repositorios de referencia son una app nativa (Kotlin + Jetpack Compose) pensada para un marco de 1920×1200
con Android 10 y 1 GB de RAM. Allí se descartó una web por memoria y calor. La Redmi Pad Pro no tiene esos límites,
y una web en ZimaOS tiene ventajas:

- Un único sitio que mantener: un cambio en el servidor llega a la tablet sin compilar ni instalar APKs.
- Los secretos (token de Home Assistant) se quedan en el servidor; la tablet no guarda nada.
- Se puede abrir desde cualquier navegador para probar.

## Qué se ha tomado de cada repositorio

| De | Qué | Dónde |
|---|---|---|
| Planify-Dashboard (Lito) | Paleta crema, tarjetas casi blancas, fuente Geist, color solo donde informa | `web/styles.css` |
| Planify-Dashboard (Lito) | Caché «stale-if-error»: con un fallo se sigue viendo lo último | `app/cache.py` |
| Planify-Dashboard (Lito) | Modo demostración con fechas relativas a hoy | `app/demo.py` |
| marco-familiar-dashboard | Cabecera con el cielo según la hora (noche, amanecer, día, atardecer) | `web/app.js`, `styles.css` |
| marco-familiar-dashboard | PVPC desde REE y «mejores horas» (coche 4 h, lavavajillas y lavadora 2 h, tramo a evitar) | `app/energy.py` |
| marco-familiar-dashboard | Batería del coche como un «gauge» de Home Assistant, azul mientras carga | `web/app.js` |
| marco-familiar-dashboard | Home Assistant como pegamento y el panel sin acceso directo a él | `app/sources.py` |

## Qué no se ha tomado

La preparación del marco (eMMC, quiosco con Device Owner, cortafuegos, ADB), Planify, los turnos de Shifter, el menú
del cole, los partidos, TaskMate y el espejo Alexa ⇄ Bring!.

## Usuarios

Ninguno de los dos repositorios tiene usuarios como tal: lo más parecido son los niños de TaskMate (círculos de
color con la inicial). Aquí se añade una pantalla de bloqueo con un avatar por persona, sin PIN. Lo común se ve
igual para los dos; lo de cada uno (de momento, el trayecto) depende de quién ha entrado.

## Calendario y Recordatorios de Apple

Se gestionan en las apps de Apple y el panel solo los enseña.

- **Calendario:** iCloud sigue sirviendo los calendarios por CalDAV, así que Home Assistant los lee con su
  integración CalDAV y el panel los toma de ahí.
- **Recordatorios:** desde iOS 13 no están en CalDAV y no hay forma de leerlos desde un servidor. Por eso los envía
  un Atajo del iPhone a `POST /api/recordatorios`, y el panel guarda la última copia de cada lista en disco.
  Se descartaron `pyicloud` y similares: usan APIs no oficiales, piden 2FA cada cierto tiempo y se rompen.
