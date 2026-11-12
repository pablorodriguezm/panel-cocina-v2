# Menú semanal

El panel propone cada semana una comida y una cena saludables (cocina mediterránea sencilla) y la lista de lo que
hace falta comprar. Solo se ve en el panel: no se escribe en el calendario de Apple.

## Dónde se ve

- **Hoy y Calendario:** al pie de cada día, 🍽️ la comida y 🌙 la cena. Al tocarlo se abre con los ingredientes.
- **Tareas → Ingredientes del menú:** todo lo de la semana (o de la siguiente), sumado y por secciones del súper.
  Tocar un ingrediente lo pasa a la Compra; el Atajo lo lleva a Recordatorios ([RECORDATORIOS.md](RECORDATORIOS.md)).
  Lo que ya parece estar en la Compra sale como «ya en la lista». Lo de la despensa de siempre (aceite, sal,
  especias…) no sale.

## Cómo se elige

`app/menu.py` sigue un plan fijo por día para que la semana quede equilibrada:

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
