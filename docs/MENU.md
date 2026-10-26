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

De cada grupo sale una receta al azar con la semana como semilla: el mismo menú en la tablet y en el móvil, y
también tras un reinicio. No se repite plato en la semana y, si se puede, tampoco el ingrediente principal.

## Recetario

Las recetas están en `app/recetario.yaml`, con las cantidades para 2 personas. Para añadir o cambiar platos se edita
ese fichero (por PR, como el resto). El mismo ingrediente se escribe siempre igual para que la lista lo sume.

En `config.yaml` (opcional):

```yaml
menu:
  personas: 2           # escala las cantidades
  lista_compra: Compra  # a qué lista de Recordatorios van los ingredientes (por defecto, la primera)
```
