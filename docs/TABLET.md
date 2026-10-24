# La tablet (Redmi Pad Pro)

La tablet solo muestra la web del panel a pantalla completa. Se recomienda **Fully Kiosk Browser** (Play Store).
Algunas opciones, como el bloqueo total del quiosco, son de la versión PLUS, de pago único.

## Fully Kiosk Browser

- **Start URL:** `http://<ip-de-zimaos>:8090`
- **Web Content Settings:** sin zoom, sin barra de direcciones.
- **Device Management:** mantener la pantalla encendida, arrancar al encender la tablet y volver a primer plano si se sale.
- **Kiosk Mode (PLUS):** bloquea la barra de estado y los botones con un PIN de administrador.
- **Screen Off Timer / Scheduler:** horario de pantalla (apagarla de noche) y brillo.
- **Motion detection (opcional):** encender la pantalla al acercarse a la cocina con la cámara frontal.
- **Remote Administration (opcional):** permite controlarla desde Home Assistant con la integración Fully Kiosk Browser.

## HyperOS

Si HyperOS cierra la app en segundo plano:

- Ajustes → Apps → Fully Kiosk → **Ahorro de batería: Sin restricciones** y **Inicio automático** activado.
- En la multitarea, bloquea la tarjeta de Fully Kiosk (mantener pulsado → candado).

## Red

- Reserva en el router una IP fija para ZimaOS: la tablet apunta a ella.
- La tablet tiene que estar en la misma red que ZimaOS (o llegar a ella).
- Si siempre está enchufada, activa en Ajustes → Batería la **protección de batería** (carga hasta el 80 %) si tu versión de HyperOS la tiene.
