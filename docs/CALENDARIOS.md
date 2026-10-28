# Calendarios extra: festivos, Fórmula 1 y fútbol

Además del calendario «RIM Y PABLO» (iCloud → Home Assistant), el panel enseña en **Hoy** y **Calendario** tres
calendarios que descarga él solo de fuentes públicas. No pasan por Home Assistant ni se escriben en el calendario de
Apple. Cada uno tiene su color, y «Lo próximo» sigue mirando solo el calendario de los dos.

| Calendario | Fuente | Se actualiza | Color |
|---|---|---|---|
| Festivos de Madrid capital | `app/festivos.yaml` (BOE, BOCM y Ayuntamiento) | Con cada versión | Rojo; el número del día también |
| Fórmula 1 | API pública [Jolpica](https://api.jolpi.ca) (continuación de Ergast): libres, clasificación, sprint y carrera | Cada 6 h | Negro |
| Real Madrid y Barça | Un `.ics` público por equipo ([fixtur.es](https://fixtur.es)), todas las competiciones | Cada 3 h | Morado y azul |

## Festivos

Son 14 al año: los nacionales (BOE), los de la Comunidad de Madrid (decreto en el BOCM) y los dos locales del
Ayuntamiento (San Isidro y La Almudena). **Hay que añadir cada año** en `app/festivos.yaml` cuando se publiquen,
normalmente en octubre del año anterior. Si falta un año que el panel enseña, `/api/salud` lo avisa en
`calendarios_extra.festivos`. Las pruebas comprueban que cada año tenga 14 y dos locales.

## Partidos

Si el Real Madrid y el Barça juegan entre ellos, el partido sale una vez (misma hora y dos palabras en común en el
título). Si una fuente deja de funcionar se cambia la URL en `config.yaml`, sin tocar código:

```yaml
calendarios_extra:
  festivos: true
  f1: true
  equipos:
    - {nombre: Real Madrid, ics: "https://ics.fixtur.es/v2/real-madrid.ics", color: "#7A5BC2"}
    - {nombre: Barça, ics: "https://ics.fixtur.es/v2/fc-barcelona.ics", color: "#004D98"}
```

Para quitar algo: `f1: false` o `equipos: []`. Sin la sección, todo está activado con estos dos equipos.

## Si algo no sale

`/api/salud` → `calendarios_extra` dice, por fuente, si va bien y el último error. Si una falla, el panel sigue
enseñando su última copia buena y el resto de calendarios. Para comprobar una URL de equipo, ábrela en el navegador
desde casa: tiene que descargar un fichero que empieza por `BEGIN:VCALENDAR`.
