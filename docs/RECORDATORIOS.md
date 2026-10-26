# Recordatorios de Apple: compra y tareas

La lista de la compra y las tareas se siguen gestionando en **Recordatorios**, como siempre. El panel solo las enseña.

## Por qué hace falta un Atajo

Desde iOS 13, los Recordatorios «actualizados» ya no están en el CalDAV de iCloud: Apple los guarda en un sitio al
que solo acceden sus propias apps. Ni Home Assistant ni este servidor pueden leerlos. El calendario sí sigue en
CalDAV, por eso ese va por Home Assistant y los Recordatorios no.

La solución es que un **iPhone envíe las listas al panel** con un Atajo. Si la lista está compartida entre Pablo y
Rim, basta con que el Atajo esté en un iPhone, aunque mejor en los dos.

## 1. La clave del panel

En `.env` del servidor, `PANEL_TOKEN` con una clave larga (`openssl rand -hex 24`). El Atajo la manda en cada envío.

## 2. El Atajo «Enviar Recordatorios al panel»

App Atajos → «+» → añade estas acciones, en este orden (una vez por cada lista: Compra, Casa…):

1. **Buscar recordatorios** → *Lista* es **Compra** y *Está completado* es **falso**. Ordenar por fecha de creación.
2. **Combinar texto** → *Recordatorios* con **Nueva línea**. Queda un recordatorio por línea.
3. **Obtener contenido de URL**:
   - URL: `http://<ip-de-zimaos>:8090/api/recordatorios`
   - Método: **POST**
   - Cabeceras: `X-Panel-Token` → la clave de `.env`
   - Cuerpo de la solicitud: **JSON**, con dos campos de texto:
     - `lista` → `Compra` (el nombre tal cual está en Recordatorios)
     - `items` → la variable *Texto combinado*

Para la lista «Casa», repite las tres acciones en el mismo Atajo cambiando el nombre.

Pruébalo con ▶︎: el panel responde `{"ok": true, …}`. Si la lista no está en `config.yaml`, la respuesta lo avisa.

### Lo que se pasa a la compra desde el panel

En Tareas, la lista «Ingredientes del menú» deja tocar un ingrediente para pasarlo a la Compra. Sale en la Compra
de la tablet al momento (con la etiqueta «desde el panel»), pero para que llegue a Recordatorios el Atajo tiene que
recogerlo. Añade estas acciones **al principio** del Atajo, antes de «Buscar recordatorios»:

1. **Obtener contenido de URL**:
   - URL: `http://<ip-de-zimaos>:8090/api/recordatorios/recoger`
   - Método: **POST**
   - Cabeceras: `X-Panel-Token` → la misma clave
2. **Obtener valor de diccionario** → *Valor* de **items** en *Contenido de URL*.
3. **Repetir con cada** elemento de *Valor de diccionario*:
   - **Añadir nuevo recordatorio** → *Elemento de repetición* en la lista **Compra**.
4. Fin de la repetición. Después siguen las acciones de siempre (buscar, combinar y enviar).

El panel entrega cada cosa una sola vez; en cuanto el Atajo envía la lista de la Compra, deja de enseñarla como
«desde el panel» porque ya viene de Recordatorios. Mientras el Atajo no la haya recogido, tocarla otra vez en la
tablet la quita.

## 3. Que se envíe solo

Atajos → **Automatización** → «+» → *Crear automatización personal*:

- **App → Recordatorios → «Se cierra»** → *Ejecutar inmediatamente* → el Atajo de arriba. Así, cada vez que alguien
  apunta algo y sale de Recordatorios, el panel se actualiza.
- **Hora del día**, un par de veces al día, por si algo se cambió desde otro sitio (el Mac, Siri, el Apple Watch).

Ponlo en los dos iPhones. Hace falta estar en la wifi de casa para llegar a ZimaOS; fuera de casa el envío falla sin
más, y se repite al volver.

## Si la tablet dice que la lista no está al día

El panel guarda cuándo llegó cada lista. Si pasan más de 12 h sin noticias, lo indica debajo de la lista. Abre
Recordatorios en el iPhone y ciérralo para forzar un envío.

## Más adelante

- Marcar como comprado desde la tablet: igual que lo pasado desde el menú, el panel apuntaría lo marcado y el
  Atajo lo completaría en Recordatorios antes de leer la lista.
- Fechas y notas: con un bloque **Repetir con cada** que arme un diccionario `{titulo, notas, vence}` por recordatorio,
  el panel ya las acepta (`items` como lista de diccionarios).
