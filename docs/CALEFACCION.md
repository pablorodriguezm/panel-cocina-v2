# Calefacción: ¿gas o aire?

La pestaña **Energía** dice en cada momento qué sale más barato para calentar la casa, si la caldera de gas o el aire
acondicionado en modo calor, y la previsión hora a hora hasta donde haya precio de la luz (hoy, y mañana desde que
REE lo publica, sobre las 20:15). Solo aconseja: no enciende nada.

## Cómo se calcula

Se compara lo que cuesta **cada kWh de calor que entra en casa**, solo con lo que depende del uso. El término fijo
del gas y la potencia contratada de la luz se pagan igual se use o no.

| | € por kWh de calor |
|---|---|
| Caldera | (término variable TUR + impuesto sobre el gas) × 1,21 ÷ rendimiento de la caldera |
| Aire | PVPC de esa hora × (1 + impuesto eléctrico) × 1,21 ÷ COP con la temperatura exterior de esa hora |

- **Precio de la luz:** el PVPC de REE que ya usa el panel (energía, peajes y cargos, sin impuestos), más el
  impuesto eléctrico (5,11 %) y el IVA.
- **Temperatura:** la previsión horaria de Open-Meteo.
- **Precio del gas:** `app/gas.yaml`, el término variable de la TUR por trimestre (BOE), más el impuesto sobre
  hidrocarburos (0,00234 €/kWh) y el IVA. Comprobado con las facturas de Curenergía de 2026.
- **Precio de empate:** el PVPC por encima del cual empieza a compensar el gas con la temperatura de ahora.

## Los equipos de casa

| Equipo | Dato | Fuente |
|---|---|---|
| Caldera Bosch Condens 2300i W | Rendimiento estacional ηs 94 % (etiqueta ErP); se usa **0,90** porque con radiadores a 70-80 °C condensa menos | Ficha del fabricante |
| Aire Daikin ADEAS100A (ADEA100A + AZAS100MV), de conductos: salón y tres habitaciones | COP **4,63 a 7 °C** (10,8 kW con 2,33 kW) y **2,42 a −10 °C**; SCOP 3,81 | Certificado Eurovent |

El COP de cada hora sale de la recta entre los dos puntos del fabricante (con un máximo de 5) por un **factor de uso
real de 0,90** (pérdidas en los conductos y desescarches).

| Fuera | COP real | El gas compensa con la luz (PVPC) por encima de |
|---|---|---|
| 7 °C | 4,2 | 0,24 €/kWh |
| 0 °C | 3,4 | 0,19 €/kWh |
| −5 °C | 2,8 | 0,16 €/kWh |

En Madrid el aire gana casi siempre; el gas solo compensa en horas punta caras de días fríos.

## Ajustes

Todo es opcional en `config.yaml`; sin la sección se usan los valores de arriba:

```yaml
calefaccion:
  tarifa_gas: TUR.1             # la de app/gas.yaml (TUR.1 hasta 5.000 kWh/año, TUR.2 hasta 15.000)
  # precio_gas_eur_kwh: 0.0525  # o un precio a mano (sin impuestos), si no es TUR
  rendimiento_caldera: 0.90
  cop: [[-10, 2.42], [7, 4.63]] # puntos (°C, COP) del fabricante
  factor_real: 0.90
```

## Mantenimiento

**Cada trimestre** (1 de enero, abril, julio y octubre) hay que añadir el precio nuevo de la TUR a `app/gas.yaml`:
sale en el BOE y en la primera factura del trimestre («Energía facturada … €/kWh»). Si pasan más de 95 días sin
actualizarlo, `/api/salud` lo avisa en `precio_gas`.

## Gasto real del aire

El Shelly Pro 3EM mide el circuito de climatización, que solo lleva el Daikin (el aparato «Climatización» de
`consumo.aparatos`; otro nombre, con `calefaccion.aparato_aire`). El panel apunta cada día, en el volumen de datos
(`aire.json`), lo que ha gastado de verdad:

| Dato | Cómo sale |
|---|---|
| kWh del día | Historial de potencia del circuito en Home Assistant, integrado por horas |
| € del día | kWh de cada hora × PVPC de esa hora, con impuestos |
| Temperatura media y grados-día | Open-Meteo; grados-día = lo que la media de cada hora queda por debajo de 18 °C |

La tarjeta lo enseña debajo de la previsión: hoy, ayer y los últimos 7 días. La primera vez rellena la última semana
con el historial de Home Assistant.

### Para qué sirve: afinar el COP

El Shelly mide la luz que entra al aire, no el calor que da: **el COP no se puede medir directamente**. Lo que sí
sale, a partir de 7 días con calefacción, son los **kWh de luz por grado-día** (cuánta luz pide la casa por cada
grado de frío). Para convertirlo en un rendimiento real hace falta la misma cuenta con gas:

1. Un periodo de solo caldera (sin aire): kWh de gas de la factura ÷ grados-día de ese periodo × 0,90 = calor por
   grado-día que necesita la casa.
2. COP real ≈ ese calor por grado-día ÷ los kWh de luz por grado-día del aire.
3. `factor_real` = COP real ÷ COP de catálogo a la temperatura media de esos días.

Es una aproximación (el sol, el viento y la temperatura de consigna cambian de un periodo a otro), y solo vale con
periodos claros de «solo aire» y «solo caldera». El paso 1 aún no está automatizado: se hace con una factura.
