# Copias de seguridad de ZimaOS

Cada noche, un stack aparte («copias») guarda en el Synology todo lo que hace falta para reconstruir los servicios
de ZimaOS. El panel de cocina vigila que la copia se haga y avisa si deja de hacerse.

## Qué se copia

| Qué | Cómo |
|---|---|
| Bases de datos PostgreSQL (TeslaMate, Outline, Immich y cualquier otra) | Volcado con `pg_dumpall` justo antes de empaquetar; se encuentran solas |
| `/DATA/AppData` (configuración y datos de todas las apps, incluido el `config.yaml` del panel) | Tal cual |
| Volúmenes de Docker (datos del panel, paneles de Grafana, Portainer…) | Tal cual |

**No se copia:** las fotos de Immich (por decisión: están también en otro sitio), las carpetas internas de PostgreSQL
(van en los volcados, que es lo que se puede restaurar con garantías) y las cachés.

**No está en ZimaOS** y por tanto no entra: Home Assistant (Raspberry, 192.168.1.202; tiene sus propias copias en
Ajustes → Sistema → Copias de seguridad) y lo que corre en el propio Synology.

El resultado es un fichero `zimaos-AAAA-MM-DDTHH-MM.tar.gz` por noche en la carpeta compartida del Synology. Se
conservan 14 días.

## Puesta en marcha (una vez)

### 1. En el Synology (DSM)

1. Panel de control → **Carpeta compartida** → Crear: `copias-zimaos`, en el **Volumen 1** (el que tiene
   redundancia; el Volumen 2 está casi lleno y no la tiene).
2. Panel de control → **Usuario y grupo** → Crear usuario `copias` con una contraseña larga, con permiso de
   lectura y escritura **solo** en `copias-zimaos`. Guarda la contraseña en Bitwarden (ZIMA_OS → `COPIAS_SMB_PASSWORD`).
3. Panel de control → **Servicios de archivos** → SMB: activado, protocolo mínimo SMB2 y máximo SMB3.

### 2. En Portainer (ZimaOS)

1. Averigua dónde guarda Docker los volúmenes: Portainer → **Host** (o `docker info`) → *Docker Root Dir*. Si no es
   `/var/lib/docker`, apunta la ruta: hará falta la variable `DOCKER_VOLUMES` (esa ruta + `/volumes`).
2. Stacks → **Add stack** → Repository, como el del panel:
   - Repository URL: `https://github.com/pablorodriguezm/panel-cocina-v2`, referencia `refs/heads/main`
   - Compose path: `deploy/copias-compose.yml`
   - Variables: `SMB_USER=copias`, `SMB_PASSWORD=…`, `PANEL_TOKEN=…` (el mismo del panel) y, si hace falta,
     `DOCKER_VOLUMES`.
3. Deploy. Tienen que quedar dos contenedores en marcha: `copias` y `copias-volcado`.

### 3. Primera copia, a mano

Portainer → contenedor `copias` → **Console** → `/bin/sh` → escribe `backup` y pulsa Intro. En el registro tiene que
salir «Volcando …» por cada base de datos y «Stored copy of backup». Comprueba en el Synology que el fichero está
en `copias-zimaos` y cuánto ocupa.

En `http://192.168.1.34:8090/api/salud` → `copias` tiene que poner `vigilada: true`.

## Vigilancia

Al terminar bien, la copia avisa al panel (`POST /api/copias/ok`). Si pasan más de 36 horas sin aviso, el panel lo
enseña en el botón de **Avisos**. Si una base de datos no se puede volcar, la copia de esa noche **falla entera** y
no avisa: mejor una alarma que una copia incompleta que parece buena. El motivo está en los registros del
contenedor `copias`.

## Restaurar

Probado con una base de datos de ejemplo: volcado → paquete → restauración en un PostgreSQL nuevo.

1. Copia el `.tar.gz` del Synology al servidor y descomprímelo: `tar xzf zimaos-….tar.gz` (sale una carpeta `backup/`).
2. **Ficheros:** copia `backup/AppData/<app>` a `/DATA/AppData/<app>` y los volúmenes que hagan falta desde
   `backup/volumenes/<volumen>/_data`.
3. **Bases de datos:** arranca solo el contenedor de PostgreSQL del stack (vacío) y carga su volcado:

   ```sh
   gunzip -c backup/bases-de-datos/teslamate-db.sql.gz | docker exec -i teslamate-db psql -U teslamate -d postgres
   ```

   Después arranca el resto del stack.
4. **Claves:** están en Bitwarden (ZIMA_OS), no en la copia.

**Haz una prueba de restauración** de vez en cuando (por ejemplo, la de TeslaMate en un contenedor de PostgreSQL
aparte): una copia que nunca se ha restaurado no es de fiar.

## Límites

- Las apps que guardan en ficheros SQLite (FreshRSS, Wallos, Pi-hole, Karakeep, Portainer) se copian en marcha. A las
  3:30 casi no escriben, pero una copia concreta podría salir inconsistente; con 14 días hay margen para coger otra.
- La copia está en casa: protege de que falle ZimaOS, no de un robo o un incendio. Para eso haría falta una segunda
  copia fuera (Hyper Backup del Synology a la nube, por ejemplo).
- La hora es 02:30 UTC (03:30 en invierno, 04:30 en verano).
