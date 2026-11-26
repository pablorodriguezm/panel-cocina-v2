# Menú semanal

El panel enseña el menú de cada semana y la lista de lo que hace falta comprar. Por defecto sigue los **planes
nutricionales** de Pablo, con las cinco tomas del día. Solo se ve en el panel: no se escribe en el calendario de Apple.

## Planes nutricionales (modo por defecto)

Los dos planes de la nutricionista (del 23 de enero y del 27 de febrero) están en `app/planes.yaml` y se siguen **tal
cual, en semanas alternas**: la semana del 23 de noviembre de 2026 el de enero, la siguiente el de febrero, y así.

- **Tomas:** desayuno, media mañana, comida, merienda y cena. En Hoy y Calendario salen la comida y la cena; al
  tocarlas se ven las cinco, cada una con sus ingredientes y su botón **Cambiar**.
- **Cantidades:** los planes solo traen el nombre del plato. Las cantidades son para 2 personas, a ración normal, y
  están en `app/recetario.yaml` (las recetas que empiezan por `plan-`).
- **Compra:** todas las tomas, desayunos y tentempiés incluidos, entran en los ingredientes de la semana. El café va
  con lo de la despensa de siempre y no sale.
- **Platos con jamón o lomo:** se quedan como están. Rim no come cerdo y los adapta o se los salta.
- **Opciones:** en «Almendras o yogur griego ligero» y «Yogur griego ligero o café», la compra lleva la primera
  opción.
- **«Libre»** (la cena del sábado del plan de febrero): sin plato ni compra.
- **Cambiar un plato:** la comida y la cena se cambian por otra del mismo grupo (también del recetario); un desayuno,
  por otro desayuno; una media mañana o una merienda, por otro tentempié.

Para empezar los turnos en otra semana, o volver al menú sorteado:

```yaml
menu:
  planes_desde: 2026-11-30   # la semana de ese lunes toca el primer plan
  # modo: recetario          # comida y cena sorteadas del recetario, como antes
```

## Dónde se ve

- **Hoy y Calendario:** al pie de cada día, 🍽️ la comida y 🌙 la cena. Al tocarlo se abre con los ingredientes.
- **Tareas → Ingredientes del menú:** todo lo de la semana (o de la siguiente), sumado y por secciones del súper.
  Tocar un ingrediente lo pasa a la Compra; el Atajo lo lleva a Recordatorios ([RECORDATORIOS.md](RECORDATORIOS.md)).
  Lo que ya parece estar en la Compra sale como «ya en la lista». Lo de la despensa de siempre (aceite, sal,
  especias…) no sale.

## Menú sorteado (modo recetario)

Con `menu.modo: recetario`, `app/menu.py` sigue un plan fijo por día para que la semana quede equilibrada:

| | Lun | Mar | Mié | Jue | Vie | Sáb | Dom |
|---|---|---|---|---|---|---|---|
| Comida | legumbre | pescado | carne blanca | legumbre | pasta, arroz o cereal | legumbre | carne roja |
| Cena | verdura | huevo | pescado | carne blanca | pescado | huevo | verdura |

De cada grupo sale una receta de la estación al azar con la semana como semilla: el mismo menú en la tablet y en el móvil, y
también tras un reinicio. No se repite plato en la semana y, si se puede, tampoco el ingrediente principal.

## Cambiar un plato

Al tocar el menú de un día (de hoy en adelante) sale un botón **Cambiar** junto a la comida y a la cena: pone el
siguiente plato del mismo grupo y de la estación que no esté ya en la semana, y la lista de ingredientes se rehace.
Tocando varias veces se da la vuelta hasta el plato original. Los cambios se guardan en el servidor (los ven los dos
y sobreviven a un reinicio). Lo que ya se hubiera pasado a la compra del plato anterior no se quita solo.

## Temporada

Las recetas pueden llevar `temporada: [primavera, verano]` u `[otoño, invierno]`; sin ella salen todo el año. La
semana toma la estación de su jueves (diciembre-febrero invierno, marzo-mayo primavera…): guisos y cremas con frío,
ensaladas y gazpacho con calor. Las pruebas comprueban que en cada estación cada grupo tenga recetas de sobra.

Al añadir o quitar recetas, el menú de la semana en curso puede cambiar una vez (el sorteo depende de la lista).

## Recetario

Las recetas están en `app/recetario.yaml`, con las cantidades para 2 personas. Para añadir o cambiar platos se edita
ese fichero (por PR, como el resto). El mismo ingrediente se escribe siempre igual para que la lista lo sume.

En `config.yaml` (opcional):

```yaml
menu:
  personas: 2           # escala las cantidades
  lista_compra: Compra  # a qué lista de Recordatorios van los ingredientes (por defecto, la primera)
```
