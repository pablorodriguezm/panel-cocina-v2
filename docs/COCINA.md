# Cocina: temporizadores y fogón olvidado

Dos ayudas para cocinar con la tablet al lado: temporizadores y un aviso si la placa o el horno se quedan encendidos.
Funcionan también con la pantalla bloqueada, y el Echo de la cocina los anuncia.

## Temporizadores

- **Botón ⏲️:** en la tablet, en la barra de la derecha, entre «Dormir» y la hora. En el iPhone, abajo a la derecha
  en vertical y abajo a la izquierda en horizontal.
- **Empezar uno:** se elige un nombre si se quiere (Pasta, Arroz, Huevos, Horno, Legumbres, Verduras) y un tiempo:
  1, 3, 5, 8, 10, 12, 15, 20, 30 o 45 min, 1 h, 1,5 h u otro a mano. Puede haber hasta 8 a la vez.
- **Cuenta atrás:** cada temporizador sale como una pastilla con lo que queda. Al tocarla se suman 1, 5 o 10 min o
  se quita.
- **Al terminar:**
  - la tablet pita cada pocos segundos y enseña «¡Listo!» con **+1 min** y **Parar**;
  - el Echo anuncia «El temporizador Pasta ha terminado»;
  - si nadie lo para, desaparece solo a los 15 minutos.
- **Dónde viven:** en el servidor (`/data/cocina.json`). Los dos dispositivos ven los mismos y no se pierden si se
  reinicia el contenedor.

## Fogón u horno olvidado

El servidor lee cada 30 s la potencia del circuito de la cocina del Shelly (placa y horno: el aparato «Cocina» de
la vista Consumo, o `cocina.potencia`).

- **Cuándo cuenta como encendido:** con más de **150 W de media en 10 minutos**. Con la media, el horno, que se
  enciende y se apaga para mantener la temperatura, no parece apagado; y un cazo de dos minutos no cuenta.
- **Desde cuándo:** se cuenta desde el principio de esos 10 minutos.

| Tiempo encendido | Qué pasa |
|---|---|
| 1 h | **Aviso:** una franja amarilla arriba («La placa o el horno lleva 1 h encendido») con dos pitidos y anuncio del Echo |
| 2 h | **Aviso fuerte:** a pantalla completa, pitando hasta que se toque «Ya lo miro», y anuncio del Echo |
| De 0:00 a 6:00 | Aviso fuerte a los **15 min** |

- **Con un temporizador del panel en marcha no avisa:** se da por hecho que alguien está cocinando. Si al terminar el
  temporizador sigue encendido y ha pasado el tiempo, el aviso salta entonces.
- **«Vale» y «Ya lo miro»:** callan la tablet para ese aviso. El siguiente nivel vuelve a sonar.
- **Al apagar:** cuando la media baja de 150 W, todo se pone a cero.

## Anuncios por el Echo

Es la única orden a Home Assistant que no viene de la vista Casa. Siempre usa el mismo servicio y el mismo altavoz, y
los textos los pone el panel, nunca la tablet. Por defecto:
- **servicio:** `notify.alexa_media` (integración Alexa Media Player);
- **altavoz:** el Echo de la vista Casa (`casa.musica.entidad`);
- **tipo:** `announce` (con el sonido de aviso de Alexa).

Si el Echo no responde, los avisos siguen saliendo en la tablet, y en **Avisos** sale «El Echo no anuncia los avisos
de la cocina».

## Ajustes

Todo es opcional en `config.yaml`:

```yaml
cocina:
  potencia: sensor.shellypro3em_a0dd6ca16ae8_em1_power   # por defecto, el aparato «Cocina» de consumo
  umbral_w: 150
  ventana_min: 10
  aviso_min: 60
  fuerte_min: 120
  noche: [0, 6]            # de 0:00 a 6:00…
  noche_min: 15            # …aviso fuerte a los 15 min
  anuncios: true           # false: sin Echo, solo la tablet
  anuncio:
    servicio: notify.alexa_media
    objetivo: media_player.echo_dot_cocina
    tipo: announce         # o tts, sin el sonido de aviso
```

## Si algo no va

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| Avisos: «Sin el sensor de la cocina…» | El sensor no existe o no responde | Revisar `cocina.potencia` o el aparato «Cocina» de `consumo` |
| Avisos: «El Echo no anuncia…» | El servicio no existe (otra integración de Alexa) o el token de HA no puede usarlo | Probar el servicio en HA → Herramientas para desarrolladores → Acciones y ajustar `cocina.anuncio` |
| La tablet no pita | El navegador solo deja sonar tras un primer toque | Tocar la pantalla una vez (al entrar con el avatar ya vale); en Fully Kiosk, activar *Autoplay Audio* |
| Avisa con un guiso largo | El guiso pasa de 1 h | Poner un temporizador del panel con lo que le queda: mientras corra, no avisa |

Estado en `/api/salud` → `cocina`: el sensor, el último anuncio, el último error y el nivel de aviso actual.
