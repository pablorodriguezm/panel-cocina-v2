# Precio de la luz en la app de Shelly

La app de Shelly calcula lo que cuestan los consumos que miden sus contadores (el Pro 3EM del cuadro y los
enchufes) con la tarifa que tenga configurada. Con la **Tarifa en vivo**, el panel le manda cada hora el PVPC de
esa hora, así que los costes de la app salen con el precio real de cada hora.

## Cómo funciona

- Cada minuto el panel mira si ha cambiado la hora; si ha cambiado, hace un `POST` a la URL de la Tarifa en vivo con
  `{"price": "0.18934"}`: el PVPC de esa hora en €/kWh.
- Por defecto va **con impuestos** (impuesto eléctrico e IVA), que es lo que se paga por cada kWh. Sin los términos
  fijos (potencia, contador), que no dependen del consumo.
- Si el envío falla, se reintenta a los 5 minutos.
- En el modo demostración no se envía nada.

## Puesta en marcha

1. En la app de Shelly: **Consumo → Tarifa eléctrica → Tarifa en vivo** y copiar la **URL de solicitud**. Lleva el
   token de la cuenta al final: es un **secreto** (con ella se puede cambiar la tarifa).
2. En Portainer → Stacks → panel-cocina → **Environment variables**: añadir `SHELLY_TARIFA_URL` con esa URL y
   **Update the stack**. Guardar también la URL en Bitwarden (ZIMA_OS → `SHELLY_TARIFA_URL`).
3. Comprobar en `http://<ip-de-zimaos>:8090/api/salud` → `shelly_tarifa`: `activo: true` y, al cambiar la hora,
   `ultimo_envio` con la hora y el precio enviado.
4. En la app de Shelly, la tarifa debe mostrar ese mismo precio.

## Ajustes

En `config.yaml`, opcional:

```yaml
shelly_tarifa:
  con_impuestos: true   # false: manda el PVPC sin impuestos, como sale en «Luz hoy»
```

## Si no llega

| Síntoma | Causa probable | Solución |
|---|---|---|
| `shelly_tarifa.activo: false` | Falta la variable | Añadir `SHELLY_TARIFA_URL` en Portainer y actualizar el stack. |
| Error 401/403/404 | Token caducado o regenerado | Copiar la URL nueva de la app y cambiar la variable. |
| «Sin precio de la luz» | REE aún no ha respondido | Se reintenta solo; ver `luz` en `/api/salud`. |
